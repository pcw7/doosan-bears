"""시즌 누적 기록 집계 (DB에 저장된 경기별 기록을 합산)."""
import json
from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal

from .config import ROUND_NAMES, TEAM_CODE

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


POSITION_CODES = {"포": "포수", "一": "1루수", "二": "2루수", "三": "3루수", "유": "유격수",
                  "좌": "좌익수", "중": "중견수", "우": "우익수", "지": "지명타자"}
POSITION_GROUPS = {"투수": "투수", "포수": "포수", "1루수": "내야수", "2루수": "내야수", "3루수": "내야수", "유격수": "내야수",
                   "좌익수": "외야수", "중견수": "외야수", "우익수": "외야수", "지명타자": "지명타자"}


def positions(conn, season: int, team: str = TEAM_CODE) -> dict[str, str]:
    """선수별 그 시즌 주 포지션. 투구 기록이 있으면 투수, 아니면 박스스코어 위치('유', '타二' 등) 중 가장 많이 맡은 수비 위치.
    대타·대주자로만 나온 선수는 빠진다 (화면에서 프로필 포지션으로 대신함)."""
    pitchers = {r[0] for r in conn.execute("""
        SELECT DISTINCT p.player_id FROM pitching p JOIN games g USING (game_id)
        WHERE p.team_code=? AND g.season=? AND g.status='FINAL'""", (team, season))}
    counts = defaultdict(lambda: defaultdict(int))
    for pid, pos in conn.execute("""
            SELECT b.player_id, b.position FROM batting b JOIN games g USING (game_id)
            WHERE b.team_code=? AND g.season=? AND g.status='FINAL'""", (team, season)):
        for ch in pos or "":
            if ch in POSITION_CODES:
                counts[pid][POSITION_CODES[ch]] += 1
    out = {pid: max(c, key=c.get) for pid, c in counts.items()}
    out.update({pid: "투수" for pid in pitchers})
    return out


def missing_boxes(conn, season: int, stage: str, team: str = TEAM_CODE) -> dict:
    """종료 경기 중 네이버에 타자/투수 기록이 없는 경기 수 (2011년 투수 기록, 2008년 포스트시즌 등)."""
    r = conn.execute(f"""
        SELECT SUM(NOT EXISTS (SELECT 1 FROM batting b WHERE b.game_id = g.game_id AND b.team_code = :team)) batting,
               SUM(NOT EXISTS (SELECT 1 FROM pitching p WHERE p.game_id = g.game_id AND p.team_code = :team)) pitching
        FROM games g WHERE {FINAL_GAMES}""", {"team": team, "season": season, "stage": stage}).fetchone()
    return {"batting": r["batting"] or 0, "pitching": r["pitching"] or 0}


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

    # 팀 ERA는 박스스코어의 팀 투구 합계(자책점·이닝)로 계산한다.
    # 팀 자책점은 공식 규칙상 개인 자책점 합보다 적을 수 있고, 개인 투수 기록이 빠진 경기(2011년 등)도 팀 합계는 있다.
    # 팀 합계가 없는 2008~2010년은 개인 기록 합으로 대신한다.
    def team_er(g) -> int:
        return g["team_er"] if g["team_er"] is not None else pit_g.get(g["game_id"], (0, 0))[0]

    def team_outs(g) -> int:
        return g["team_outs"] if g["team_outs"] is not None else pit_g.get(g["game_id"], (0, 0))[1]

    # 투수진: 선발 / 불펜 / 전체
    by_role = {r["is_starter"]: {k: v or 0 for k, v in dict(r).items()} for r in conn.execute(f"""
        SELECT is_starter, {PIT_SUMS}
        FROM pitching p JOIN games g USING (game_id)
        WHERE p.team_code=:team AND {FINAL_GAMES} GROUP BY is_starter""", p)}
    keys = ("g", "gs", "w", "l", "sv", "hld", "qs", "outs", "bf", "h", "r", "er", "bb", "hbp", "so", "hr", "pitches")
    starter = by_role.get(1, dict.fromkeys(keys, 0))
    bullpen = by_role.get(0, dict.fromkeys(keys, 0))
    # 전체: WHIP·K/9 등은 개인 기록 합으로 두고, 이닝·자책점·ERA만 팀 합계로 바꾼다
    total = _pit_rates({k: starter[k] + bullpen[k] for k in keys})
    total["er"] = sum(team_er(g) for g in games)
    total["outs"] = sum(team_outs(g) for g in games)
    total["ip"] = outs_to_ip(total["outs"])
    total["era"] = _rate(total["er"] * 27, total["outs"], 2)
    pit = []
    for label, d in (("선발", _pit_rates(starter)), ("불펜", _pit_rates(bullpen)), ("전체", total)):
        d = dict(d)
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
            outs = sum(team_outs(g) for g in gs)
            out.append({"label": label, **_record(gs), "avg": _rate(h, ab), "hr": hr, "era": _rate(er * 27, outs, 2)})
        return out

    opponents = sorted(grouped(lambda g: g["opponent_name"]),
                       key=lambda r: (-(r["pct"] if r["pct"] is not None else -1), r["label"]))
    months = grouped(lambda g: f"{int(g['game_date'][5:7])}월")

    return {"batting": bat, "pitching": pit, "splits": splits, "comebacks": comebacks,
            "opponents": opponents, "months": months,
            "noTeamTotals": sum(g["team_er"] is None or g["team_outs"] is None for g in games)}


# ── 이적 선수 판별 ──────────────────────────────────────

def _avg_str(h: int, ab: int) -> str:
    """공식 기록과 같은 형식('0.234', 반올림)의 타율 문자열."""
    if not ab:
        return "0.000"
    return str((Decimal(h) / Decimal(ab)).quantize(Decimal("0.001"), ROUND_HALF_UP))


def transfers(conn, season: int, team: str = TEAM_CODE) -> dict:
    """정규시즌 두산 기록을 박스스코어의 공식 시즌 기록과 비교해, 두산 밖에서 뛴 기록이 있는 선수를 찾는다.

    경기마다 공식 시즌 기록을 그때까지의 두산 누적 기록과 비교한다.
    - 타자: 공식 타율이 '그 경기 포함/제외' 누적 타율과 모두 다르면 어긋남 (공식 기록에 그 경기가 아직 반영 안 됐을 수 있음)
    - 투수: 공식 등판 수가 두산 누적 등판 수보다 많으면 어긋남 (투수 기록이 빠진 경기 수만큼의 차이는 무시)
    이적해 온 선수는 두산 경기 내내 어긋나므로, 80% 이상의 경기와 마지막 두 경기가 어긋날 때만 이적으로 본다.
    시즌 중간에 생긴 자료 누락이나 서스펜디드 경기처럼 일부 경기만 어긋나는 경우는 제외된다.
    (첫 경기만으로 판단하지 않는 이유: 0타수 무안타끼리는 타율이 .000으로 우연히 같을 수 있다)
    """
    def persistent(miss: list[bool]) -> bool:
        return bool(miss) and sum(miss) >= 0.8 * len(miss) and all(miss[-2:])

    p = {"team": team, "season": season, "stage": "regular"}
    order = "ORDER BY g.game_date, g.start_time, g.game_id"
    missing = missing_boxes(conn, season, "regular", team)

    bat = {}
    for r in conn.execute(f"""
            SELECT b.player_id, b.h, b.ab, b.season_avg FROM batting b JOIN games g USING (game_id)
            WHERE b.team_code=:team AND {FINAL_GAMES} {order}""", p):
        s = bat.setdefault(r["player_id"], {"h": 0, "ab": 0, "miss": [], "official": None})
        before = _avg_str(s["h"], s["ab"])
        s["h"] += r["h"]
        s["ab"] += r["ab"]
        if r["season_avg"]:
            s["miss"].append(r["season_avg"] not in (_avg_str(s["h"], s["ab"]), before))
            s["official"] = r["season_avg"]
    batting = {} if missing["batting"] else {
        pid: {"avg": float(s["official"])} for pid, s in bat.items() if persistent(s["miss"])}

    pit = {}
    for r in conn.execute(f"""
            SELECT p.player_id, p.season_era, p.season_w, p.season_l, p.season_s, p.season_g
            FROM pitching p JOIN games g USING (game_id)
            WHERE p.team_code=:team AND {FINAL_GAMES} {order}""", p):
        s = pit.setdefault(r["player_id"], {"g": 0, "miss": [], "last": None})
        s["g"] += 1
        s["miss"].append((r["season_g"] or 0) - s["g"] > missing["pitching"])
        s["last"] = dict(r)
    pitching = {}
    for pid, s in pit.items():
        last = s["last"]
        if persistent(s["miss"]):
            try:
                era = float(last["season_era"])
            except (TypeError, ValueError):
                era = None
            pitching[pid] = {"g": last["season_g"], "w": last["season_w"], "l": last["season_l"],
                             "sv": last["season_s"], "era": era}
    return {"batting": batting, "pitching": pitching}


# ── 역대 기록 ─────────────────────────────────────────

def postseason_result(conn, season: int, finished: bool, team: str = TEAM_CODE) -> str | None:
    """포스트시즌 결과: 한국시리즈 4승이면 우승, 끝난 시즌이면 마지막 라운드 탈락(한국시리즈는 준우승)."""
    rows = conn.execute("""
        SELECT round_code, result FROM games WHERE season=? AND stage='postseason' AND status='FINAL'
        ORDER BY game_date, start_time, game_id""", (season,)).fetchall()
    if not rows:
        return None
    if sum(r["round_code"] == "kbo_ps_ks" and r["result"] == "W" for r in rows) >= 4:
        return "우승"
    last = rows[-1]["round_code"]
    if not finished:
        return f"{ROUND_NAMES.get(last, last)} 진행 중"
    return "준우승" if last == "kbo_ps_ks" else f"{ROUND_NAMES.get(last, last)} 탈락"


def season_records(conn, seasons: list[int], top_n: int = 5) -> list[dict]:
    """2008년 이후 두산 한 시즌 개인 기록 상위 N명 (정규시즌, 두산 소속 기록).
    타율·OPS는 그 시즌 규정타석(경기수×3.1), ERA는 규정이닝(경기수) 이상만."""
    bat, pit = [], []
    for s in seasons:
        g = team_record(conn, s, "regular")["g"]
        for r in batting(conn, s, "regular"):
            bat.append({**r, "season": s, "qualified": r["pa"] >= int(g * 3.1)})
        for r in pitching(conn, s, "regular"):
            pit.append({**r, "season": s, "qualified": r["outs"] >= g * 3})

    def top(rows, key, fmt, highest=True, qualified=False):
        rows = [r for r in rows if r.get(key) is not None and (r["qualified"] or not qualified)]
        rows.sort(key=lambda r: r[key], reverse=highest)
        return {"fmt": fmt, "rows": [{"season": r["season"], "pid": r["player_id"], "name": r["name"], "value": r[key]}
                                     for r in rows[:top_n]]}

    return [
        {"label": "홈런", **top(bat, "hr", "n")},
        {"label": "타점", **top(bat, "rbi", "n")},
        {"label": "안타", **top(bat, "h", "n")},
        {"label": "도루", **top(bat, "sb", "n")},
        {"label": "타율", **top(bat, "avg", "avg", qualified=True)},
        {"label": "OPS", **top(bat, "ops", "avg", qualified=True)},
        {"label": "승", **top(pit, "w", "n")},
        {"label": "세이브", **top(pit, "sv", "n")},
        {"label": "홀드", **top(pit, "hld", "n")},
        {"label": "탈삼진", **top(pit, "so", "n")},
        {"label": "ERA", **top(pit, "era", "era", highest=False, qualified=True)},
    ]
