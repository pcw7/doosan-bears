"""시즌별 선수 정보: 등번호(문자중계 라인업)와 프로필·사진·WAR(네이버 선수 API).

data/players/<시즌>.json.enc 에 암호화해 저장한다.
{
  "numbers":  {선수ID: {"no": "7", "date": "2026-10-05"}},   # 그 시즌 두산에서 단 등번호 (가장 최근 경기 기준)
  "lineup_games": [경기ID, ...],                               # 등번호를 확인하려고 문자중계를 받은 경기
  "profiles": {선수ID: {...}},                                 # 사진·생년월일·키/몸무게·투타·출신·드래프트·연봉·WAR
}
등번호는 경기마다 문자중계(경기당 약 140KB)를 받아야 알 수 있어, 최근 경기부터 보면서 번호를 모르는 선수가
나온 경기만 받는다 (시즌당 15~30경기). 진행 중 시즌은 새 경기마다 받아 번호 변경도 반영하고,
그 경기에 나온 선수의 프로필(WAR 등)만 다시 받는다. 프로필은 현재 기준이라 지난 시즌은 처음 한 번만 받는다.
"""
import json
import logging
import time

from . import archive, naver
from .config import PLAYERS_DIR, REQUEST_DELAY, TEAM_CODE

log = logging.getLogger(__name__)


def path_for(season: int):
    return PLAYERS_DIR / f"{season}{archive.SUFFIX}"


def load(season: int) -> dict:
    p = path_for(season)
    data = archive.load_json(p) if p.exists() else {}
    data.setdefault("numbers", {})
    data.setdefault("lineup_games", [])
    data.setdefault("profiles", {})
    return data


def _season_games(conn, season: int) -> list[tuple[str, str, str, set]]:
    """(경기ID, 날짜, 두산 쪽 home/away, 두산 출전 선수ID 집합) — 최근 경기부터."""
    players = {}
    for gid, pid in conn.execute("""
            SELECT game_id, player_id FROM batting WHERE team_code=:t
            UNION SELECT game_id, player_id FROM pitching WHERE team_code=:t""", {"t": TEAM_CODE}):
        players.setdefault(gid, set()).add(pid)
    games = conn.execute("""
        SELECT game_id, game_date, home_away FROM games
        WHERE season=? AND status='FINAL' ORDER BY game_date DESC, start_time DESC""", (season,)).fetchall()
    return [(g["game_id"], g["game_date"], "home" if g["home_away"] == "H" else "away", players.get(g["game_id"], set()))
            for g in games if g["game_id"] in players]


def _profile(raw: dict) -> dict:
    p = raw.get("player") or {}
    prof = json.loads(p.get("profile") or "{}") if p.get("profile") else {}
    hit, pit = raw.get("hitterStats") or {}, raw.get("pitcherStats") or {}
    return {
        "name": p.get("playerName"),
        "image": prof.get("image") or None,
        "birth": p.get("dateOfBirth"),
        "height": p.get("height"),
        "weight": p.get("weight"),
        "type": p.get("playerPlayType"),
        "career": p.get("career"),
        "draft": p.get("draftInfo"),
        "salary": p.get("salary"),
        "team": p.get("teamId"),
        "position": prof.get("position") or None,  # 현재 기준 ('내야수' 등) — 대타로만 나온 선수의 포지션 대신
        "retired": p.get("isRetire"),
        # 그 시즌 공식 기록 (이적 선수는 다른 팀 기록 포함)
        "hitter": {"g": hit.get("hitterGameCount"), "war": hit.get("hitterWar"), "wrc": hit.get("hitterWrcPlus")} if hit else None,
        "pitcher": {"g": pit.get("pitcherGameCount"), "war": pit.get("pitcherWar")} if pit else None,
    }


def update(conn, season: int, current: bool) -> bool:
    """그 시즌 두산 출전 선수의 등번호·프로필을 채운다. 내용이 바뀌었을 때만 저장하고 True.
    (저장할 때마다 암호문이 달라져 git 커밋이 생기므로, 바뀐 게 없으면 파일을 건드리지 않는다)"""
    data = load(season)
    before = json.dumps(data, sort_keys=True, ensure_ascii=False)
    refresh = set()  # 새 경기에 나온 선수 → 프로필(WAR 등)을 다시 받는다
    games = _season_games(conn, season)
    all_players = set().union(*(g[3] for g in games)) if games else set()

    # 1) 등번호: 진행 중 시즌은 새 경기마다 받아 번호 변경까지 반영, 지난 시즌은 번호를 모르는 선수가 나온 경기만
    fetched = set(data["lineup_games"])
    last_date = max((n["date"] for n in data["numbers"].values()), default="")
    unknown = all_players - set(data["numbers"])
    for gid, gdate, side, players in games:
        new_game = current and last_date and gdate > last_date  # 처음 채울 때는 모든 경기를 '새 경기'로 보지 않는다
        if gid in fetched or not (new_game or players & unknown):
            continue
        try:
            lineup = naver.fetch_lineups(gid)[side]
        except naver.ApiError as e:
            log.warning("문자중계 라인업 수집 실패 %s: %s", gid, e)
            continue
        data["lineup_games"].append(gid)
        appeared = {str(p.get("pcode")) for p in (lineup.get("batter") or []) + (lineup.get("pitcher") or [])}
        for p in (lineup.get("batter") or []) + (lineup.get("pitcher") or []):
            pid, no = str(p.get("pcode") or ""), str(p.get("backnum") or "").strip()
            old = data["numbers"].get(pid)
            if pid and no and (not old or old["date"] <= gdate):
                data["numbers"][pid] = {"no": no, "date": gdate}
        unknown -= appeared
        if new_game:
            refresh |= appeared
        time.sleep(REQUEST_DELAY)
        if not unknown and not current:
            break

    # 2) 프로필: 처음 보는 선수, 그리고 진행 중 시즌의 새 경기에 나온 선수 (경기를 뛰면 WAR 등이 바뀜)
    data.pop("profiles_date", None)  # 예전 형식(하루 한 번 전원 갱신)의 흔적
    for pid in sorted(all_players):
        if pid in data["profiles"] and pid not in refresh:
            continue
        try:
            data["profiles"][pid] = _profile(naver.fetch_player(season, pid))
        except naver.ApiError as e:
            log.warning("선수 정보 수집 실패 %s %s: %s", season, pid, e)
            continue
        time.sleep(0.2)

    if json.dumps(data, sort_keys=True, ensure_ascii=False) == before:
        return False
    archive.save_json(path_for(season), data)
    log.info("%d 선수 정보: %d명 (등번호 %d명, 문자중계 %d경기)", season, len(all_players),
             len(set(data["numbers"]) & all_players), len(data["lineup_games"]))
    return True
