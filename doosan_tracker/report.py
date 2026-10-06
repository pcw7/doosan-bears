"""HTML 대시보드 생성: 데이터를 JSON으로 만들어 templates/report.html에 끼워 넣는다."""
import json
import shutil
from datetime import date, datetime
from pathlib import Path

from . import db, stats
from .config import ROUND_NAMES, TEAM_CODE, TEAM_NAME

TEMPLATE = Path(__file__).parent / "templates" / "report.html"
STAGE_LABELS = [("regular", "정규시즌"), ("postseason", "포스트시즌"), ("exhibition", "시범경기")]


def _games(conn, season: int) -> list[dict]:
    games = [dict(r) for r in conn.execute(
        "SELECT * FROM games WHERE season=? AND stage != 'allstar' ORDER BY game_date, start_time, game_id", (season,))]
    bat, pit = {}, {}
    for r in conn.execute("""
            SELECT b.* FROM batting b JOIN games g USING (game_id)
            WHERE g.season=? AND b.team_code=? ORDER BY b.seq""", (season, TEAM_CODE)):
        bat.setdefault(r["game_id"], []).append({
            "pid": r["player_id"], "name": r["player_name"], "o": r["bat_order"], "pos": r["position"],
            "sub": r["is_sub"], "pa": r["pa"], "ab": r["ab"], "r": r["r"], "h": r["h"], "b2": r["b2"],
            "b3": r["b3"], "hr": r["hr"], "rbi": r["rbi"], "bb": r["bb"], "hbp": r["hbp"], "so": r["so"],
            "sb": r["sb"], "res": r["pa_results"],
        })
    for r in conn.execute("""
            SELECT p.* FROM pitching p JOIN games g USING (game_id)
            WHERE g.season=? AND p.team_code=? ORDER BY p.seq""", (season, TEAM_CODE)):
        pit.setdefault(r["game_id"], []).append({
            "pid": r["player_id"], "name": r["player_name"], "ip": r["ip"], "outs": r["outs"],
            "bf": r["bf"], "h": r["h"], "r": r["r"], "er": r["er"], "bb": r["bb"], "hbp": r["hbp"],
            "so": r["so"], "hr": r["hr"], "np": r["pitches"], "dec": r["decision"], "gs": r["is_starter"],
        })
    out = []
    for g in games:
        out.append({
            "id": g["game_id"], "date": g["game_date"], "time": g["start_time"], "stage": g["stage"],
            "round": ROUND_NAMES.get(g["round_code"], g["round_code"]), "stadium": g["stadium"],
            "ha": g["home_away"], "opp": g["opponent_name"], "ts": g["team_score"], "os": g["opponent_score"],
            "result": g["result"], "status": g["status"],
            "starter": g["team_starter"], "oppStarter": g["opponent_starter"],
            "wp": g["win_pitcher"], "lp": g["lose_pitcher"], "sp": g["save_pitcher"],
            "rheb": [g["team_hits"], g["team_errors"], g["team_walks"],
                     g["opponent_hits"], g["opponent_errors"], g["opponent_walks"]],
            "line": json.loads(g["line_score"]) if g["line_score"] else None,
            "notes": json.loads(g["notes"]) if g["notes"] else [],
            "bat": bat.get(g["game_id"], []), "pit": pit.get(g["game_id"], []),
        })
    return out


def build_data(conn, season: int, all_seasons: list[int]) -> dict:
    stages = {}
    for key, label in STAGE_LABELS:
        rec = stats.team_record(conn, season, key)
        if rec["g"]:
            stages[key] = {
                "label": label, "record": rec,
                "batting": stats.batting(conn, season, key),
                "pitching": stats.pitching(conn, season, key),
                "team": stats.team(conn, season, key),
                "missing": stats.missing_boxes(conn, season, key),
            }
    # 시즌 중 다른 팀에서 뛴 선수: 정규시즌 기록에 공식 시즌 기록을 붙여 화면에서 '이적'으로 표시
    if "regular" in stages:
        moved = stats.transfers(conn, season)
        for kind in ("batting", "pitching"):
            for row in stages["regular"][kind]:
                if row["player_id"] in moved[kind]:
                    row["official"] = moved[kind][row["player_id"]]
    # 남은 경기가 없으면 끝난 시즌 → 화면에 '최종 순위'로 표시
    remaining = conn.execute("""
        SELECT COUNT(*) FROM games WHERE season=? AND status IN ('SCHEDULED', 'LIVE', 'SUSPENDED')
        AND game_date >= ?""", (season, date.today().isoformat())).fetchone()[0]
    return {
        "team": TEAM_NAME, "season": season, "seasons": all_seasons,
        "generatedAt": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "lastSync": db.get_meta(conn, "last_sync"),
        "standings": db.get_meta(conn, f"standings:{season}"),
        "finished": remaining == 0,
        "stages": stages, "games": _games(conn, season),
    }


def seasons(conn) -> list[int]:
    """기록이 있는 시즌 목록 (최신순)."""
    return [r[0] for r in conn.execute(
        "SELECT DISTINCT season FROM games WHERE status='FINAL' ORDER BY season DESC")]


def render(conn, season: int, out_path: Path, all_seasons: list[int]) -> Path:
    data = build_data(conn, season, all_seasons)
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    html = TEMPLATE.read_text(encoding="utf-8").replace("/*__DATA__*/null", payload)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    return out_path


def render_all(conn, site_dir: Path) -> list[int]:
    """시즌마다 <시즌>.html을 만들고, 최신 시즌은 index.html로도 저장한다."""
    all_seasons = seasons(conn)
    for s in all_seasons:
        render(conn, s, site_dir / f"{s}.html", all_seasons)
    if all_seasons:
        shutil.copyfile(site_dir / f"{all_seasons[0]}.html", site_dir / "index.html")
    return all_seasons
