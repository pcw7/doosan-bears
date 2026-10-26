"""사용법:
    python -m doosan_tracker sync                 # 새로 끝난 경기 수집 + CSV/리포트 갱신 (자동 실행용)
    python -m doosan_tracker sync --from 2026-03-01 --to 2026-10-06 --force   # 기간 지정 재수집
    python -m doosan_tracker report               # 리포트만 다시 생성
    python -m doosan_tracker status               # DB 현황 확인
    python -m doosan_tracker info --all           # 모든 시즌 선수 정보(등번호·프로필)와 순위표 수집 (처음 한 번)
"""
import argparse
import logging
import os
import re
import sys
import urllib.request
from datetime import date, datetime, timedelta

from . import db, export, league, naver, players, preview, report
from .config import CSV_DIR, DB_PATH, LOG_PATH, SITE_DIR, SITE_URL, STALE_HOURS
from .sync import restore, sync


def setup_logging() -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    handlers = [logging.FileHandler(LOG_PATH, encoding="utf-8")]
    if sys.stderr is not None:  # pythonw(작업 스케줄러)로 실행하면 콘솔이 없음
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8")
        handlers.append(logging.StreamHandler(sys.stderr))
    logging.basicConfig(level=logging.INFO, handlers=handlers,
                        format="%(asctime)s %(levelname)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S")


def publish(conn) -> None:
    seasons = report.render_all(conn, SITE_DIR)
    if not seasons:
        logging.info("저장된 경기가 없어 리포트를 건너뜁니다")
        return
    files = export.export_csv(conn, CSV_DIR, seasons)
    logging.info("CSV %d개 → %s", len(files), CSV_DIR)
    logging.info("리포트 %d개 시즌 (%d~%d) → %s", len(seasons), seasons[-1], seasons[0], SITE_DIR)


def live_last_sync() -> datetime | None:
    """배포된 사이트에 실린 마지막 수집 성공 시각 (읽지 못하면 None)."""
    try:
        with urllib.request.urlopen(SITE_URL, timeout=20) as resp:
            m = re.search(r'"lastSync":"([^"]+)"', resp.read().decode("utf-8"))
        return datetime.fromisoformat(m.group(1)) if m else None
    except Exception:
        logging.warning("배포된 사이트에서 마지막 수집 시각을 읽지 못했습니다")
        return None


def naver_down(err: Exception) -> int:
    """네이버 일정 API에 닿지 않을 때(시간 초과·차단). 2026-10-26 GitHub 서버에서만 네이버 응답이 끊긴 적이 있어,
    실행마다 실패 메일이 가지 않도록 이번 실행은 건너뛰고(수집·커밋·배포 없음) 사이트는 지난 배포를 그대로 둔다.
    마지막 성공이 STALE_HOURS를 넘었으면 하루 한 번(17시 첫 실행)만 실패로 표시해 알린다."""
    logging.warning("네이버 응답 없음 — 이번 실행은 수집·배포를 건너뜁니다: %s", err)
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as f:
            f.write("skip=true\n")
        print("::warning::네이버 응답 없음 — 이번 실행은 수집·배포를 건너뜀 (사이트는 지난 배포 그대로)")
    last, now = live_last_sync(), datetime.now()
    if last and now - last > timedelta(hours=STALE_HOURS):
        logging.error("네이버에 %s 이후로 %d시간 넘게 접속하지 못했습니다", last.strftime("%Y-%m-%d %H:%M"), STALE_HOURS)
        if now.hour == 17 and now.minute < 20:  # 알림 메일은 하루 한 번
            return 1
    return 0


def update_info(conn, all_seasons: bool) -> None:
    """선수 정보·리그 순위표 갱신. 실패해도 경기 기록 수집·배포는 계속되도록 경고만 남긴다."""
    seasons = report.seasons(conn)
    for s in seasons if all_seasons else seasons[:1]:
        for name, fn in (("선수 정보", lambda: players.update(conn, s, current=s == seasons[0])),
                         ("순위표", lambda: league.update(s, current=s == seasons[0]))):
            try:
                fn()
            except Exception:
                logging.exception("%d %s 갱신 실패", s, name)


def status(conn) -> None:
    for row in conn.execute("""
            SELECT season, stage, COUNT(*) n, SUM(status='FINAL') final,
                   SUM(result='W') w, SUM(result='L') l, SUM(result='D') d, MAX(game_date) last
            FROM games GROUP BY season, stage ORDER BY season, stage"""):
        print(f"{row['season']} {row['stage']:<11} 경기 {row['n']:>3} (종료 {row['final']:>3})  "
              f"{row['w']}승 {row['l']}패 {row['d']}무  마지막 {row['last']}")
    print("마지막 동기화:", db.get_meta(conn, "last_sync"))
    seasons = report.seasons(conn)
    if seasons:
        print(f"{seasons[0]} 순위:", db.get_meta(conn, f"standings:{seasons[0]}"))


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="doosan_tracker", description="두산 베어스 경기/선수 기록 자동 수집")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sync", help="경기 기록 수집")
    s.add_argument("--from", dest="start", type=date.fromisoformat, help="시작일 YYYY-MM-DD")
    s.add_argument("--to", dest="end", type=date.fromisoformat, help="종료일 YYYY-MM-DD")
    s.add_argument("--force", action="store_true", help="이미 저장된 경기도 다시 수집")
    s.add_argument("--no-report", action="store_true", help="CSV/리포트 생성 생략")
    sub.add_parser("report", help="CSV/HTML 리포트만 생성 (모든 시즌)")
    sub.add_parser("status", help="DB 현황")
    info = sub.add_parser("info", help="선수 정보(등번호·프로필)와 리그 순위표 수집")
    info.add_argument("--all", action="store_true", help="지난 시즌까지 모든 시즌 (처음 한 번)")
    args = p.parse_args(argv)

    if sys.stdout is not None and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    setup_logging()
    conn = db.connect(DB_PATH)
    try:
        if args.cmd == "sync":
            try:
                stats = sync(conn, args.start, args.end, args.force)
            except naver.ApiError as e:  # 일정 조회부터 실패 = 네이버에 닿지 않음 (경기별 실패는 sync 안에서 셈)
                return naver_down(e)
            update_info(conn, all_seasons=False)
            try:
                preview.update(conn)
            except Exception:
                logging.exception("다음 경기 미리보기 갱신 실패")
            if not args.no_report:
                publish(conn)
            return 1 if stats["failed"] else 0
        restore(conn)  # DB가 없거나 스키마가 바뀌어 비었으면 data/games 원본에서 채움
        if args.cmd == "report":
            publish(conn)
        elif args.cmd == "status":
            status(conn)
        elif args.cmd == "info":
            update_info(conn, all_seasons=args.all)
        return 0
    except Exception:
        logging.exception("실행 중 오류")
        return 2
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
