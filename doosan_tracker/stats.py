"""시즌 누적 기록 집계 (DB에 저장된 경기별 기록을 합산)."""
import json
from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal

from .config import TEAM_CODE

FINAL_GAMES = "g.season=:season AND g.stage=:stage AND g.status='FINAL'"
BAT_SUMS = """SUM(pa) pa, SUM(ab) ab, SUM(b.r) r, SUM(b.h) h, SUM(b2) b2, SUM(b3) b3, SUM(b.hr) hr,
    SUM(rbi) rbi, SUM(bb) bb, SUM(hbp) hbp, SUM(so) so, SUM(sb) sb, SUM(sf) sf, SUM(sh) sh, SUM(gidp) gidp"""
PIT_SUMS = """COUNT(*) g, SUM(is_starter) gs,
    -- decision이 NULL(결정 없음)이어도 0이 되도록 '=' 대신 IS 사용
    SUM(decision IS 'W') w, SUM(decision IS 'L') l, SUM(decision IS 'S') sv, SUM(decision IS 'H') hld,
    SUM(is_starter AND outs >= 18 AND er <= 3) qs,
    SUM(outs) outs, SUM(bf) bf, SUM(p.h) h, SUM(p.r) r, SUM(er) er, SUM(bb) bb,
    SUM(hbp) hbp, SUM(so) so, SUM(p.hr) hr, SUM(pitches) pitches"""


def _rate(num, den, digits=3):
    return round(num / den, digits) if den else None


def _bat_rates(d: dict) -> dict:
    tb = d["h"] + d["b2"] + 2 * d["b3"] + 3 * d["hr"]
    d["avg"] = _rate(d["h"], d["ab"])
    d["obp"] = _rate(d["h"] + d["bb"] + d["hbp"], d["ab"] + d["bb"] + d["hbp"] + d["sf"])
    d["slg"] = _rate(tb, d["ab"])
    d["ops"] = round(d["obp"] + d["slg"], 3) if d["obp"] is not None and d["slg"] is not None else None
    return d


def _pit_rates(d: dict) -> dict:
    d["ip"] = outs_to_ip(d["outs"])
    d["era"] = _rate(d["er"] * 27, d["outs"], 2)
    d["whip"] = _rate((d["bb"] + d["h"]) * 3, d["outs"], 2)
    d["k9"] = _rate(d["so"] * 27, d["outs"], 2)
    d["bb9"] = _rate(d["bb"] * 27, d["outs"], 2)
    return d


def outs_to_ip(outs: int) -> str:
    whole, frac = divmod(outs or 0, 3)
    return f"{whole}" + ("", " ⅓", " ⅔")[frac]


def team_record(conn, season: int, stage: str) -> dict:
    r = conn.execute("""
        SELECT SUM(result='W') w, SUM(result='L') l, SUM(result='D') d,
               SUM(team_score) rs, SUM(opponent_score) ra, COUNT(*) g
        FROM games WHERE season=? AND stage=? AND status='FINAL'""", (season, stage)).fetchone()
    rec = {k: r[k] or 0 for k in ("w", "l", "d", "rs", "ra", "g")}
    rec["pct"] = _rate(rec["w"], rec["w"] + rec["l"])
    return rec


def batting(conn, season: int, stage: str, team: str = TEAM_CODE) -> list[dict]:
    rows = conn.execute(f"""
        SELECT b.player_id, MAX(b.player_name) name, COUNT(*) g, {BAT_SUMS}
        FROM batting b JOIN games g USING (game_id)
        WHERE b.team_code=:team AND {FINAL_GAMES}
        GROUP BY b.player_id""", {"team": team, "season": season, "stage": stage})
    return sorted((_bat_rates(dict(r)) for r in rows), key=lambda d: -d["pa"])


def pitching(conn, season: int, stage: str, team: str = TEAM_CODE) -> list[dict]:
    rows = conn.execute(f"""
        SELECT p.player_id, MAX(p.player_name) name, {PIT_SUMS}
        FROM pitching p JOIN games g USING (game_id)
        WHERE p.team_code=:team AND {FINAL_GAMES}
        GROUP BY p.player_id""", {"team": team, "season": season, "stage": stage})
    return sorted((_pit_rates(dict(r)) for r in rows), key=lambda d: -d["outs"])


# ── 팀 기록 ─────────────────────────────────────────────

def _record(games: list[dict]) -> dict:
    w = sum(g["result"] == "W" for g in games)
    l = sum(g["result"] == "L" for g in games)
    return {
        "g": len(games), "w": w, "l": l, "d": len(games) - w - l, "pct": _rate(w, w + l),
        "rs": sum(g["team_score"] for g in games), "ra": sum(g["opponent_score"] for g in games),
    }


def _flow(g: dict) -> dict:
    """이닝별 점수를 반 이닝씩 따라가며 선취점, 7회 종료 시점 점수, 리드/열세 경험 여부를 구한다."""
    line = json.loads(g["line_score"] or "null") or {}
    t, o = line.get("team") or [], line.get("opponent") or []
    is_away = g["home_away"] == "A"
    away, home = (t, o) if is_away else (o, t)
    ts = os_ = 0
    first, trailed, led = None, False, False
    for i in range(max(len(away), len(home))):
        for arr, ours in ((away, is_away), (home, not is_away)):
            if i >= len(arr):
                continue
            if ours:
                ts += arr[i] or 0
            else:
                os_ += arr[i] or 0
            if first is None and (ts or os_):
                first = "team" if ts else "opp"
            trailed |= ts < os_
            led |= ts > os_
    after7 = (sum(t[:7]), sum(o[:7])) if len(t) >= 7 and len(o) >= 7 else None
    return {"first": first, "after7": after7, "trailed": trailed, "led": led,
            "extra": max(len(t), len(o)) > 9}


def team(conn, season: int, stage: str, team: str = TEAM_CODE) -> dict:
    p = {"team": team, "season": season, "stage": stage}
    games = [dict(r) for r in conn.execute(
        f"SELECT * FROM games g WHERE {FINAL_GAMES} ORDER BY game_date, start_time", p)]
    n = len(games)

    # 팀 타격·수비: 두산 vs 상대 팀 (두산 경기에서 상대 팀이 친 기록)
    sums = {r["ours"]: dict(r) for r in conn.execute(f"""
        SELECT b.team_code = :team ours, {BAT_SUMS}
        FROM batting b JOIN games g USING (game_id) WHERE {FINAL_GAMES} GROUP BY ours""", p)}
    errors = {1: sum(g["team_errors"] or 0 for g in games), 0: sum(g["opponent_errors"] or 0 for g in games)}
    bat_keys = ("pa", "ab", "r", "h", "b2", "b3", "hr", "rbi", "bb", "hbp", "so", "sb", "sf", "sh", "gidp")
    bat = []
    for ours, label in ((1, "두산"), (0, "상대 팀")):
        row = sums.get(ours) or {}
        d = _bat_rates({k: row.get(k) or 0 for k in bat_keys})
        d.update(label=label, g=n, e=errors[ours], rpg=_rate(d["r"], n, 2))
        bat.append(d)

    # 경기별 두산 타격·투구 합계 (상대 팀별/월별 집계용)
    bat_g = {r[0]: r[1:] for r in conn.execute(f"""
        SELECT game_id, SUM(b.h), SUM(ab), SUM(b.hr) FROM batting b JOIN games g USING (game_id)
        WHERE b.team_code=:team AND {FINAL_GAMES} GROUP BY game_id""", p)}
    pit_g = {r[0]: r[1:] for r in conn.execute(f"""
        SELECT game_id, SUM(er), SUM(outs) FROM pitching p JOIN games g USING (game_id)
        WHERE p.team_code=:team AND {FINAL_GAMES} GROUP BY game_id""", p)}

    def team_er(g) -> int:
        """팀 자책점. 투수 교체 후 실책이 끼면 개인 자책점 합보다 적을 수 있어 공식 팀 ERA는 이 값을 쓴다."""
        return g["team_er"] if g["team_er"] is not None else pit_g.get(g["game_id"], (0, 0))[0]

    # 투수진: 선발 / 불펜 / 전체
    by_role = {r["is_starter"]: {k: v or 0 for k, v in dict(r).items()} for r in conn.execute(f"""
        SELECT is_starter, {PIT_SUMS}
        FROM pitching p JOIN games g USING (game_id)
        WHERE p.team_code=:team AND {FINAL_GAMES} GROUP BY is_starter""", p)}
    keys = ("g", "gs", "w", "l", "sv", "hld", "qs", "outs", "bf", "h", "r", "er", "bb", "hbp", "so", "hr", "pitches")
    starter = by_role.get(1, dict.fromkeys(keys, 0))
    bullpen = by_role.get(0, dict.fromkeys(keys, 0))
    total = {k: starter[k] + bullpen[k] for k in keys}
    total["er"] = sum(team_er(g) for g in games)
    pit = []
    for label, d in (("선발", starter), ("불펜", bullpen), ("전체", total)):
        d = _pit_rates(dict(d))
        d["label"] = label
        d["ip_avg"] = outs_to_ip(round(d["outs"] / d["g"])) if label != "전체" and d["g"] else None
        if label != "선발":
            d["qs"] = None
        pit.append(d)

    # 상황별 성적
    flows = {g["game_id"]: _flow(g) for g in games}
    f = lambda g: flows[g["game_id"]]
    margin = lambda g: abs(g["team_score"] - g["opponent_score"])
    split_defs = [
        ("전체", games),
        ("홈", [g for g in games if g["home_away"] == "H"]),
        ("원정", [g for g in games if g["home_away"] == "A"]),
        ("선취점 시", [g for g in games if f(g)["first"] == "team"]),
        ("선실점 시", [g for g in games if f(g)["first"] == "opp"]),
        ("7회까지 리드 시", [g for g in games if f(g)["after7"] and f(g)["after7"][0] > f(g)["after7"][1]]),
        ("7회까지 열세 시", [g for g in games if f(g)["after7"] and f(g)["after7"][0] < f(g)["after7"][1]]),
        ("1점차 경기", [g for g in games if margin(g) == 1]),
        ("5점차 이상", [g for g in games if margin(g) >= 5]),
        ("연장전", [g for g in games if f(g)["extra"]]),
    ]
    splits = [{"label": label, **_record(gs)} for label, gs in split_defs if gs or label == "전체"]
    comebacks = {
        "wins": sum(g["result"] == "W" and f(g)["trailed"] for g in games),
        "losses": sum(g["result"] == "L" and f(g)["led"] for g in games),
    }

    # 상대 팀별 / 월별 (팀 타율·ERA 포함)
    def grouped(key) -> list[dict]:
        groups = defaultdict(list)
        for g in games:
            groups[key(g)].append(g)
        out = []
        for label, gs in groups.items():
            h = sum(bat_g.get(g["game_id"], (0, 0, 0))[0] for g in gs)
            ab = sum(bat_g.get(g["game_id"], (0, 0, 0))[1] for g in gs)
            hr = sum(bat_g.get(g["game_id"], (0, 0, 0))[2] for g in gs)
            er = sum(team_er(g) for g in gs)
            outs = sum(pit_g.get(g["game_id"], (0, 0))[1] for g in gs)
            out.append({"label": label, **_record(gs), "avg": _rate(h, ab), "hr": hr, "era": _rate(er * 27, outs, 2)})
        return out

    opponents = sorted(grouped(lambda g: g["opponent_name"]),
                       key=lambda r: (-(r["pct"] if r["pct"] is not None else -1), r["label"]))
    months = grouped(lambda g: f"{int(g['game_date'][5:7])}월")

    return {"batting": bat, "pitching": pit, "splits": splits, "comebacks": comebacks,
            "opponents": opponents, "months": months}


# ── 이적 선수 판별 ──────────────────────────────────────

def _avg_str(h: int, ab: int) -> str:
    """공식 기록과 같은 형식('0.234', 반올림)의 타율 문자열."""
    if not ab:
        return "0.000"
    return str((Decimal(h) / Decimal(ab)).quantize(Decimal("0.001"), ROUND_HALF_UP))


def transfers(conn, season: int, team: str = TEAM_CODE) -> dict:
    """정규시즌 두산 기록을 박스스코어의 공식 시즌 기록과 비교해, 두산 밖에서 뛴 기록이 있는 선수를 찾는다.

    공식 기록은 박스스코어를 받은 시점 기준이라 그 경기가 아직 반영되기 전 값일 수도 있다.
    그래서 타자는 공식 타율이 '마지막 경기 포함'과 '제외' 두 값 모두와 다를 때,
    투수는 공식 등판 수가 두산 등판 수보다 많을 때만 이적으로 본다.
    """
    p = {"team": team, "season": season, "stage": "regular"}
    order = "ORDER BY g.game_date, g.start_time, g.game_id"

    bat_cum = {}
    for r in conn.execute(f"""
            SELECT b.player_id, b.h, b.ab, b.season_avg FROM batting b JOIN games g USING (game_id)
            WHERE b.team_code=:team AND {FINAL_GAMES} {order}""", p):
        h, ab, _, _ = bat_cum.get(r["player_id"], (0, 0, None, None))
        bat_cum[r["player_id"]] = (h + r["h"], ab + r["ab"], _avg_str(h, ab), r["season_avg"])
    batting = {pid: {"avg": float(official)}
               for pid, (h, ab, prev_avg, official) in bat_cum.items()
               if official and official not in (_avg_str(h, ab), prev_avg)}

    pit_cum = {}
    for r in conn.execute(f"""
            SELECT p.player_id, p.season_era, p.season_w, p.season_l, p.season_s, p.season_g
            FROM pitching p JOIN games g USING (game_id)
            WHERE p.team_code=:team AND {FINAL_GAMES} {order}""", p):
        pit_cum[r["player_id"]] = (pit_cum.get(r["player_id"], (0, None))[0] + 1, dict(r))
    pitching = {}
    for pid, (n, last) in pit_cum.items():
        if (last["season_g"] or 0) > n:
            try:
                era = float(last["season_era"])
            except (TypeError, ValueError):
                era = None
            pitching[pid] = {"g": last["season_g"], "w": last["season_w"], "l": last["season_l"],
                             "sv": last["season_s"], "era": era}
    return {"batting": batting, "pitching": pitching}
