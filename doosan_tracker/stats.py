"""시즌 누적 기록 집계 (DB에 저장된 경기별 기록을 합산)."""
from .config import TEAM_CODE


def _rate(num, den, digits=3):
    return round(num / den, digits) if den else None


def team_record(conn, season: int, stage: str) -> dict:
    r = conn.execute("""
        SELECT SUM(result='W') w, SUM(result='L') l, SUM(result='D') d,
               SUM(team_score) rs, SUM(opponent_score) ra, COUNT(*) g
        FROM games WHERE season=? AND stage=? AND status='FINAL'""", (season, stage)).fetchone()
    rec = {k: r[k] or 0 for k in ("w", "l", "d", "rs", "ra", "g")}
    rec["pct"] = _rate(rec["w"], rec["w"] + rec["l"])
    return rec


def batting(conn, season: int, stage: str, team: str = TEAM_CODE) -> list[dict]:
    rows = conn.execute("""
        SELECT b.player_id, MAX(b.player_name) name, COUNT(*) g,
               SUM(pa) pa, SUM(ab) ab, SUM(r) r, SUM(h) h, SUM(b2) b2, SUM(b3) b3, SUM(b.hr) hr,
               SUM(rbi) rbi, SUM(bb) bb, SUM(hbp) hbp, SUM(so) so, SUM(sb) sb,
               SUM(sf) sf, SUM(sh) sh, SUM(gidp) gidp
        FROM batting b JOIN games g USING (game_id)
        WHERE b.team_code=? AND g.season=? AND g.stage=? AND g.status='FINAL'
        GROUP BY b.player_id""", (team, season, stage)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        tb = d["h"] + d["b2"] + 2 * d["b3"] + 3 * d["hr"]
        d["avg"] = _rate(d["h"], d["ab"])
        d["obp"] = _rate(d["h"] + d["bb"] + d["hbp"], d["ab"] + d["bb"] + d["hbp"] + d["sf"])
        d["slg"] = _rate(tb, d["ab"])
        d["ops"] = round(d["obp"] + d["slg"], 3) if d["obp"] is not None and d["slg"] is not None else None
        out.append(d)
    return sorted(out, key=lambda d: -d["pa"])


def pitching(conn, season: int, stage: str, team: str = TEAM_CODE) -> list[dict]:
    rows = conn.execute("""
        SELECT p.player_id, MAX(p.player_name) name, COUNT(*) g, SUM(is_starter) gs,
               -- decision이 NULL(결정 없음)이어도 0이 되도록 '=' 대신 IS 사용
               SUM(decision IS 'W') w, SUM(decision IS 'L') l, SUM(decision IS 'S') sv, SUM(decision IS 'H') hld,
               SUM(outs) outs, SUM(bf) bf, SUM(p.h) h, SUM(p.r) r, SUM(er) er, SUM(bb) bb,
               SUM(hbp) hbp, SUM(so) so, SUM(p.hr) hr, SUM(pitches) pitches
        FROM pitching p JOIN games g USING (game_id)
        WHERE p.team_code=? AND g.season=? AND g.stage=? AND g.status='FINAL'
        GROUP BY p.player_id""", (team, season, stage)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["ip"] = outs_to_ip(d["outs"])
        d["era"] = _rate(d["er"] * 27, d["outs"], 2)
        d["whip"] = _rate((d["bb"] + d["h"]) * 3, d["outs"], 2)
        d["k9"] = _rate(d["so"] * 27, d["outs"], 2)
        out.append(d)
    return sorted(out, key=lambda d: -d["outs"])


def outs_to_ip(outs: int) -> str:
    whole, frac = divmod(outs or 0, 3)
    return f"{whole}" + ("", " ⅓", " ⅔")[frac]
