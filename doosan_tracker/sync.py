"""일정 확인 → 종료된 두산 경기의 박스스코어 수집 → 원본 보관(data/games) + DB 저장."""
import logging
import time
from collections import Counter
from datetime import date, timedelta

from . import archive, db, naver, parse
from .config import LOOKAHEAD_DAYS, LOOKBACK_DAYS, REQUEST_DELAY, TEAM_CODE

log = logging.getLogger(__name__)
DONE = ("FINAL", "CANCELLED")


def default_window(conn, today: date) -> tuple[date, date]:
    """마지막으로 저장된 종료 경기 며칠 전부터 오늘 이후 며칠까지.
    DB가 비어 있으면 올해 3월 1일부터 (= 첫 실행 시 시즌 전체 자동 백필)."""
    last = db.last_final_date(conn)
    start = date.fromisoformat(last) - timedelta(days=LOOKBACK_DAYS) if last else date(today.year, 3, 1)
    return start, today + timedelta(days=LOOKAHEAD_DAYS)


def store(conn, schedule: dict, record: dict | None) -> dict:
    """종료 경기(record 있음) 또는 취소 경기(record 없음)를 DB에 저장."""
    game = parse.schedule_to_game(schedule, TEAM_CODE)
    if record is None:
        with conn:
            db.save_game(conn, game)
        return game

    extra, batting, pitching, standings = parse.parse_record(game, record, TEAM_CODE)
    game.update(extra)
    ts, os_ = game["team_score"], game["opponent_score"]
    game["result"] = "W" if ts > os_ else "L" if ts < os_ else "D"
    db.save_final_game(conn, game, batting, pitching)

    # 박스스코어의 순위는 그 경기 직후 기준 → 시즌별로 가장 마지막 정규시즌 경기의 값을 남긴다 (지난 시즌은 최종 순위)
    if standings and game["stage"] == "regular":
        key = f"standings:{game['season']}"
        prev = db.get_meta(conn, key)
        if not prev or prev.get("game_date", "") <= game["game_date"]:
            db.set_meta(conn, key, {
                "rank": standings.get("rank"), "w": standings.get("w"), "l": standings.get("l"),
                "d": standings.get("d"), "pct": standings.get("wra"), "game_date": game["game_date"],
            })
    return game


def restore(conn) -> int:
    """data/games 의 원본 중 DB에 없는 경기를 채운다 (DB를 지워도 여기서 다시 만들어짐)."""
    known = {r["game_id"] for r in conn.execute(
        f"SELECT game_id FROM games WHERE status IN {DONE}")}
    n = 0
    for game_id, path in archive.entries():
        if game_id not in known:
            doc = archive.read(path)
            store(conn, doc["schedule"], doc["record"])
            n += 1
    if n:
        log.info("보관된 원본에서 %d경기 복원", n)
    return n


def sync(conn, start: date | None = None, end: date | None = None, force: bool = False) -> Counter:
    restore(conn)
    today = date.today()
    d_start, d_end = default_window(conn, today)
    start, end = start or d_start, end or d_end
    log.info("일정 조회: %s ~ %s", start, end)

    games = [g for g in naver.fetch_schedule(start, end)
             if TEAM_CODE in (g["homeTeamCode"], g["awayTeamCode"])]
    games.sort(key=lambda g: g.get("gameDateTime") or g["gameDate"])

    stats = Counter()
    for g in games:
        game = parse.schedule_to_game(g, TEAM_CODE)
        prev = db.game_status(conn, game["game_id"])

        if prev in DONE and not force:
            stats["unchanged"] += 1
            continue
        if game["status"] == "CANCELLED":
            archive.write(game["season"], game["game_id"], g, None, db.now())
            store(conn, g, None)
            stats["pending"] += 1
            continue
        if game["status"] != "FINAL":
            with conn:
                db.save_game(conn, game)
            stats["pending"] += 1
            continue

        try:
            record = naver.fetch_record(game["game_id"])
        except naver.ApiError as e:
            log.error("박스스코어 수집 실패 %s: %s", game["game_id"], e)
            stats["failed"] += 1
            continue

        archive.write(game["season"], game["game_id"], g, record, db.now())
        game = store(conn, g, record)
        stats["saved"] += 1
        log.info("저장: %s %s %s %d-%d %s",
                 game["game_date"], "vs" if game["home_away"] == "H" else "@",
                 game["opponent_name"], game["team_score"], game["opponent_score"], game["result"])
        time.sleep(REQUEST_DELAY)

    db.set_meta(conn, "last_sync", db.now())
    log.info("완료: 신규 저장 %d, 기존 %d, 예정/진행/취소 %d, 실패 %d",
             stats["saved"], stats["unchanged"], stats["pending"], stats["failed"])
    return stats
