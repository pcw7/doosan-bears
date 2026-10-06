"""HTML 대시보드 생성: 데이터를 JSON으로 만들어 templates/report.html에 끼워 넣는다."""
import json
from datetime import datetime
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


def build_data(conn, season: int) -> dict:
    stages = {}
    for key, label in STAGE_LABELS:
        rec = stats.team_record(conn, season, key)
        if rec["g"]:
            stages[key] = {
                "label": label, "record": rec,
                "batting": stats.batting(conn, season, key),
                "pitching": stats.pitching(conn, season, key),
            }
    return {
        "team": TEAM_NAME, "season": season,
        "generatedAt": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "lastSync": db.get_meta(conn, "last_sync"),
        "standings": db.get_meta(conn, "standings"),
        "stages": stages, "games": _games(conn, season),
    }


def render(conn, season: int, out_path: Path) -> Path:
    data = build_data(conn, season)
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    html = TEMPLATE.read_text(encoding="utf-8").replace("/*__DATA__*/null", payload)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    return out_path


def latest_season(conn) -> int | None:
    r = conn.execute("SELECT MAX(season) s FROM games WHERE status='FINAL'").fetchone()
    return r["s"]
