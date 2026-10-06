"""네이버 스포츠 API 클라이언트 (공식 문서가 없는 비공개 API이므로 구조가 바뀔 수 있음)."""
import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta

API = "https://api-gw.sports.naver.com"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) doosan-tracker",
    "Referer": "https://m.sports.naver.com/",
    "Accept": "application/json",
}
log = logging.getLogger(__name__)


class ApiError(RuntimeError):
    pass


def _get(path: str, params: dict | None = None, retries: int = 3) -> dict:
    url = API + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=20) as resp:
                body = json.load(resp)
            if not body.get("success", True):
                raise ApiError(f"API 실패 응답: {url} → {body.get('code')}")
            return body["result"]
        except urllib.error.HTTPError as e:
            if 400 <= e.code < 500 and e.code != 429:  # 없는 선수 등 다시 해도 같은 요청 오류는 바로 포기
                raise ApiError(f"요청 실패: {url}: {e}") from None
            last_err = e
            log.warning("요청 실패 (%d/%d) %s: %s", attempt, retries, url, e)
            time.sleep(2 * attempt)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, KeyError) as e:
            last_err = e
            log.warning("요청 실패 (%d/%d) %s: %s", attempt, retries, url, e)
            time.sleep(2 * attempt)
    raise ApiError(f"요청 실패: {url}: {last_err}")


def fetch_schedule(start: date, end: date) -> list[dict]:
    """start~end(포함) 기간의 KBO 전체 경기 목록. 한 달 단위로 나눠 요청한다."""
    games: list[dict] = []
    cur = start
    while cur <= end:
        chunk_end = min(cur + timedelta(days=30), end)
        result = _get("/schedule/games", {
            "fields": "basic,schedule,baseball",
            "upperCategoryId": "kbaseball",
            "categoryId": "kbo",
            "fromDate": cur.isoformat(),
            "toDate": chunk_end.isoformat(),
            "size": 500,
        })
        games.extend(result.get("games", []))
        cur = chunk_end + timedelta(days=1)
        if cur <= end:
            time.sleep(0.2)  # 여러 달을 한꺼번에 받을 때 서버에 부담을 주지 않도록
    return games


def fetch_record(game_id: str) -> dict:
    """경기 기록(박스스코어). 반환값은 recordData 객체."""
    return _get(f"/schedule/games/{game_id}/record")["recordData"]


def fetch_lineups(game_id: str) -> dict:
    """문자중계에 실린 양 팀 출전 선수 (그 경기 당시 등번호 포함). {"home": {"batter": [...], "pitcher": [...]}, "away": ...}"""
    relay = _get(f"/schedule/games/{game_id}/relay").get("textRelayData") or {}
    return {"home": relay.get("homeLineup") or {}, "away": relay.get("awayLineup") or {}}


def fetch_player(season: int, player_id: str) -> dict:
    """선수 프로필(현재 기준)과 그 시즌 기록. {"player": {...}, "hitterStats": {...}, "pitcherStats": {...}}"""
    return _get(f"/statistics/categories/kbo/seasons/{season}/players/{player_id}")
