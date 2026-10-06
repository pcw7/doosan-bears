"""KBO 리그 순위표 (10개 팀 전체). 네이버 팀 기록 API에서 받아 data/standings/<시즌>.json.enc 에 암호화해 저장한다.

{"as_of": "2026-10-06", "teams": [{"rank": 1, "id": "KT", "name": "KT", "g": 141, "w": 87, "l": 49, "d": 5,
                                   "pct": 0.64, "gb": 0.0, "streak": "7승", "last5": "WWDWW"}, ...]}
진행 중 시즌은 실행할 때마다 받되 순위가 실제로 바뀌었을 때만 저장한다 (as_of = 바뀐 것을 확인한 날).
지난 시즌은 최종 순위라 처음 한 번만 받는다.
"""
import json
import logging
from datetime import date

from . import archive, naver
from .config import DATA_DIR

log = logging.getLogger(__name__)
STANDINGS_DIR = DATA_DIR / "standings"


def path_for(season: int):
    return STANDINGS_DIR / f"{season}{archive.SUFFIX}"


def load(season: int) -> dict | None:
    p = path_for(season)
    return archive.load_json(p) if p.exists() else None


def table(season: int) -> dict | None:
    """정규시즌 순위표. 네이버 순위는 끝난 시즌이면 포스트시즌 결과까지 반영한 '최종 순위'라
    (예: 2015년 정규시즌 3위 두산이 우승해 1위) 승률로 다시 줄 세우고 게임차도 1위 기준으로 다시 계산한다.
    승률이 같으면 네이버 순서를 따른다 (2021년 KT·삼성 동률 → 1위 결정전 승자 KT가 앞)."""
    d = load(season)
    if not d:
        return None
    pct = lambda t: t["w"] / (t["w"] + t["l"]) if t["w"] + t["l"] else 0
    teams = sorted((dict(t) for t in d["teams"]), key=lambda t: -pct(t))  # 정렬은 안정적이라 동률이면 원래 순서 유지
    top = teams[0]
    for i, t in enumerate(teams, 1):
        t["rank"] = i
        t["gb"] = ((top["w"] - t["w"]) + (t["l"] - top["l"])) / 2
    return {**d, "teams": teams}


def update(season: int, current: bool) -> bool:
    old = load(season)
    if old and not current:
        return False
    try:
        rows = naver.fetch_team_stats(season)
    except naver.ApiError as e:
        log.warning("%d 순위표 수집 실패: %s", season, e)
        return False
    teams = [{
        "rank": t.get("ranking"), "id": t.get("teamId"), "name": t.get("teamShortName") or t.get("teamName"),
        "g": t.get("gameCount"), "w": t.get("winGameCount"), "l": t.get("loseGameCount"), "d": t.get("drawnGameCount"),
        "pct": t.get("wra"), "gb": t.get("gameBehind"),
        "streak": t.get("continuousGameResult"), "last5": t.get("lastFiveGames"),
    } for t in rows]
    teams.sort(key=lambda t: (t["rank"] or 99, -(t["pct"] or 0)))
    if not teams or (old and json.dumps(old["teams"], sort_keys=True) == json.dumps(teams, sort_keys=True)):
        return False
    archive.save_json(path_for(season), {"as_of": date.today().isoformat(), "teams": teams})
    log.info("%d 순위표 저장 (%d개 팀)", season, len(teams))
    return True
