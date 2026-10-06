"""CSV 내보내기 (엑셀에서 바로 열 수 있도록 UTF-8 BOM)."""
import csv
from pathlib import Path

from . import stats
from .config import TEAM_CODE

QUERIES = {
    "games.csv": """
        SELECT game_date, start_time, round_code, stage, stadium, home_away, opponent_name,
               team_score, opponent_score, result, status, team_hits, team_errors,
               opponent_hits, opponent_errors, team_starter, opponent_starter,
               win_pitcher, lose_pitcher, save_pitcher, game_id
        FROM games ORDER BY game_date, start_time""",
    "batting_games.csv": """
        SELECT g.game_date, g.opponent_name, g.home_away, g.result, b.player_name, b.bat_order,
               b.position, b.pa, b.ab, b.r, b.h, b.b2, b.b3, b.hr, b.rbi, b.bb, b.hbp, b.so,
               b.sb, b.sf, b.sh, b.gidp, b.pa_results, b.player_id, b.game_id
        FROM batting b JOIN games g USING (game_id)
        WHERE b.team_code = :team ORDER BY g.game_date, b.seq""",
    "pitching_games.csv": """
        SELECT g.game_date, g.opponent_name, g.home_away, g.result, p.player_name, p.seq + 1 AS appearance,
               p.ip, p.outs, p.bf, p.ab, p.h, p.r, p.er, p.bb, p.hbp, p.so, p.hr, p.pitches,
               p.decision, p.player_id, p.game_id
        FROM pitching p JOIN games g USING (game_id)
        WHERE p.team_code = :team ORDER BY g.game_date, p.seq""",
}


def _write(path: Path, header: list[str], rows) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def export_csv(conn, out_dir: Path, seasons: list[int]) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for name, sql in QUERIES.items():
        cur = conn.execute(sql, {"team": TEAM_CODE})
        path = out_dir / name
        _write(path, [c[0] for c in cur.description], cur.fetchall())
        written.append(path)
    for season in seasons:
        for kind, fn in (("batting", stats.batting), ("pitching", stats.pitching)):
            rows = fn(conn, season, "regular")
            if rows:
                path = out_dir / f"{kind}_season_{season}.csv"
                _write(path, list(rows[0]), [list(r.values()) for r in rows])
                written.append(path)
    return written
