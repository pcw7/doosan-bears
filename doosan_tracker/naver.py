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
    return games


def fetch_record(game_id: str) -> dict:
    """경기 기록(박스스코어). 반환값은 recordData 객체."""
    return _get(f"/schedule/games/{game_id}/record")["recordData"]
