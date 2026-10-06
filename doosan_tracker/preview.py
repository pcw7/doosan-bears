"""다음 경기 미리보기: 선발 투수 매치업, 시즌 상대 전적, 양 팀 최근 5경기, 순위.

경기 전날·당일에 선발이 발표되는 등 자주 바뀌는 정보라 git에 커밋하지 않고 DB(meta 'previews')에만 두고
실행할 때마다 다가오는 경기 2개를 새로 받는다.
"""
import logging
from datetime import date

from . import db, naver

log = logging.getLogger(__name__)
RESULT = {"승": "W", "패": "L", "무": "D"}


def _starter(s: dict | None) -> dict | None:
    info = (s or {}).get("playerInfo")
    if not info:
        return None  # 선발 미발표
    cur, vs = s.get("currentSeasonStats") or {}, s.get("currentSeasonStatsOnOpponents") or {}
    return {
        "name": info.get("name"), "no": info.get("backnum"), "pid": info.get("pCode"),
        "season": {"g": cur.get("gameCount"), "w": cur.get("w"), "l": cur.get("l"), "era": cur.get("era")},
        "vs": {"g": vs.get("gameCount"), "w": vs.get("w"), "l": vs.get("l"), "era": vs.get("era")},
    }


def _compact(pv: dict, home_away: str) -> dict:
    side, opp = ("home", "away") if home_away == "H" else ("away", "home")
    me, them = ("h", "a") if home_away == "H" else ("a", "h")
    sv = pv.get("seasonVsResult") or {}
    # 최근 경기: API는 최신순 → 화면에서 왼쪽(오래된 것)→오른쪽(최근) 순으로 보이게 뒤집는다
    recent = lambda key: [RESULT.get(g.get("result"), "D") for g in (pv.get(key) or [])[:5]][::-1]
    standing = lambda key: {k: (pv.get(key) or {}).get(k) for k in ("rank", "w", "l", "d")}
    return {
        "team_starter": _starter(pv.get(f"{side}Starter")),
        "opp_starter": _starter(pv.get(f"{opp}Starter")),
        "vs": {"w": sv.get(f"{me}w"), "l": sv.get(f"{me}l"), "d": sv.get(f"{me}d")},
        "team_recent": recent(f"{side}TeamPreviousGames"),
        "opp_recent": recent(f"{opp}TeamPreviousGames"),
        "team_standing": standing(f"{side}Standings"),
        "opp_standing": standing(f"{opp}Standings"),
    }


def update(conn, limit: int = 2) -> None:
    games = conn.execute("""
        SELECT game_id, home_away FROM games WHERE status = 'SCHEDULED' AND game_date >= ?
        ORDER BY game_date, start_time LIMIT ?""", (date.today().isoformat(), limit)).fetchall()
    previews = {}
    for g in games:
        try:
            previews[g["game_id"]] = _compact(naver.fetch_preview(g["game_id"]), g["home_away"])
        except naver.ApiError as e:
            log.warning("경기 미리보기 수집 실패 %s: %s", g["game_id"], e)
    db.set_meta(conn, "previews", previews)
