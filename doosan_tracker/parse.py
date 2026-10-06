"""네이버 API 응답 → DB 행(dict) 변환."""
import json
import logging

from .config import STAGES

log = logging.getLogger(__name__)

POSITION_PITCHER = "투"
DECISIONS_KO = {"승": "W", "패": "L", "세": "S", "홀": "H"}
FRACTIONS = {"⅓": 1, "⅔": 2}


def game_status(g: dict) -> str:
    if g.get("cancel"):
        return "CANCELLED"
    if g.get("suspended"):
        return "SUSPENDED"
    return {"RESULT": "FINAL", "STARTED": "LIVE", "BEFORE": "SCHEDULED"}.get(g.get("statusCode"), g.get("statusCode") or "UNKNOWN")


def schedule_to_game(g: dict, team: str) -> dict:
    """일정 API의 경기 1건을 games 테이블 행으로 변환 (팀 기준 관점)."""
    is_home = g["homeTeamCode"] == team
    side, opp = ("home", "away") if is_home else ("away", "home")
    status = game_status(g)
    team_score = g.get(f"{side}TeamScore")
    opp_score = g.get(f"{opp}TeamScore")
    result = None
    if status == "FINAL":
        result = "W" if team_score > opp_score else "L" if team_score < opp_score else "D"
    round_code = g.get("roundCode") or ""
    date_time = g.get("gameDateTime") or ""
    return {
        "game_id": g["gameId"],
        "season": int(g["gameDate"][:4]),
        "game_date": g["gameDate"],
        "start_time": date_time[11:16] or None,
        "round_code": round_code,
        "stage": STAGES.get(round_code, "other"),
        "stadium": g.get("stadium"),
        "home_away": "H" if is_home else "A",
        "opponent_code": g[f"{opp}TeamCode"],
        "opponent_name": g[f"{opp}TeamName"],
        "team_score": team_score if status == "FINAL" else None,
        "opponent_score": opp_score if status == "FINAL" else None,
        "result": result,
        "status": status,
        "team_starter": g.get(f"{side}StarterName") or None,
        "opponent_starter": g.get(f"{opp}StarterName") or None,
        "win_pitcher": g.get("winPitcherName") or None,
        "lose_pitcher": g.get("losePitcherName") or None,
    }


def ip_to_outs(ip: str) -> int:
    """'6 ⅓' → 19, '0 ⅔' → 2, '7' → 21."""
    outs, digits = 0, ""
    for ch in (ip or "").replace("1/3", "⅓").replace("2/3", "⅔"):
        if ch.isdigit():
            digits += ch
        elif ch in FRACTIONS:
            outs += FRACTIONS[ch]
        elif digits:
            outs += int(digits) * 3
            digits = ""
    if digits:
        outs += int(digits) * 3
    return outs


def classify_pa(s: str) -> str:
    """타석 결과 약어('좌2', '중안', '4구', '포희번' ...) → 결과 코드."""
    s = s.strip()
    if "희비" in s:
        return "SF"
    if "희번" in s:
        return "SH"
    if s.endswith("4구") or s.startswith("고4") or "고의" in s:
        return "BB"
    if "사구" in s:
        return "HBP"
    if "삼진" in s or "낫" in s:
        return "SO"
    if s.endswith("홈"):
        return "HR"
    if s.endswith("안"):
        return "1B"
    if len(s) > 1 and s.endswith("2"):
        return "2B"
    if len(s) > 1 and s.endswith("3"):
        return "3B"
    if "병" in s:
        return "GIDP"
    if "실" in s:
        return "ROE"
    if "야선" in s:
        return "FC"
    if "방" in s:
        return "INT"
    return "OUT"


def _pa_results(b: dict) -> list[str]:
    """inn1..inn25 필드를 이닝 순서대로 펼친 타석 결과 목록. 한 이닝 2타석은 '4구/중안'처럼 '/'로 구분."""
    results = []
    for i in range(1, 26):
        cell = (b.get(f"inn{i}") or "").strip()
        if cell:
            results.extend(p for p in cell.split("/") if p.strip())
    return results


def batting_row(game_id: str, team_code: str, seq: int, b: dict) -> dict | None:
    results = _pa_results(b)
    pos = b.get("pos") or ""
    if not results and pos == POSITION_PITCHER:
        return None  # 지명타자 해제로 타순에 들어간 투수 — 타격 기록 없음
    kinds = [classify_pa(r) for r in results]
    hbp, sf, sh = kinds.count("HBP"), kinds.count("SF"), kinds.count("SH")
    row = {
        "game_id": game_id,
        "player_id": str(b["playerCode"]),
        "player_name": b["name"],
        "team_code": team_code,
        "bat_order": b.get("batOrder"),
        "seq": seq,
        "position": pos,
        "is_sub": 1 if b.get("substituteIn") else 0,
        "ab": b.get("ab", 0),
        "r": b.get("run", 0),
        "h": b.get("hit", 0),
        "b2": kinds.count("2B"),
        "b3": kinds.count("3B"),
        "hr": b.get("hr", 0),
        "rbi": b.get("rbi", 0),
        "bb": b.get("bb", 0),
        "hbp": hbp,
        "so": b.get("kk", 0),
        "sb": b.get("sb", 0),
        "sf": sf,
        "sh": sh,
        "gidp": kinds.count("GIDP"),
        "pa_results": " ".join(results),
    }
    row["pa"] = row["ab"] + row["bb"] + hbp + sf + sh + kinds.count("INT")
    parsed_hits = sum(kinds.count(k) for k in ("1B", "2B", "3B", "HR"))
    if parsed_hits != row["h"] or kinds.count("HR") != row["hr"]:
        log.warning("%s %s: 타석 결과 해석 불일치 (안타 %d/%d, 홈런 %d/%d) %s",
                    game_id, b["name"], parsed_hits, row["h"], kinds.count("HR"), row["hr"], results)
    return row


def pitching_row(game_id: str, team_code: str, seq: int, p: dict, decisions: dict) -> dict:
    pid = str(p["pcode"])
    bbhp = p.get("bbhp", 0)
    bb = p.get("bb", 0)
    return {
        "game_id": game_id,
        "player_id": pid,
        "player_name": p["name"],
        "team_code": team_code,
        "seq": seq,
        "is_starter": 1 if seq == 0 else 0,
        "outs": ip_to_outs(p.get("inn", "")),
        "ip": (p.get("inn") or "").strip(),
        "bf": p.get("pa", 0),
        "ab": p.get("ab", 0),
        "h": p.get("hit", 0),
        "r": p.get("r", 0),
        "er": p.get("er", 0),
        "bb": bb,
        "hbp": max(bbhp - bb, 0),
        "so": p.get("kk", 0),
        "hr": p.get("hr", 0),
        "pitches": p.get("bf", 0),  # 네이버 응답의 bf 필드는 투구수
        "decision": decisions.get(pid) or DECISIONS_KO.get(p.get("wls") or ""),
    }


def parse_record(game: dict, record: dict, team: str) -> tuple[dict, list[dict], list[dict], dict | None]:
    """박스스코어 → (games 보강 필드, 타자 행들, 투수 행들, 팀 순위 스냅샷)."""
    gid = game["game_id"]
    is_home = game["home_away"] == "H"
    side, opp = ("home", "away") if is_home else ("away", "home")
    codes = {side: team, opp: game["opponent_code"]}

    board = record.get("scoreBoard") or {}
    rheb = board.get("rheb") or {}
    inn = board.get("inn") or {}
    decisions = {str(x["pCode"]): x["wls"] for x in record.get("pitchingResult") or []}
    by_decision = {}
    for x in record.get("pitchingResult") or []:
        by_decision.setdefault(x["wls"], x["name"])

    extra = {
        "team_hits": (rheb.get(side) or {}).get("h"),
        "team_errors": (rheb.get(side) or {}).get("e"),
        "team_walks": (rheb.get(side) or {}).get("b"),
        "opponent_hits": (rheb.get(opp) or {}).get("h"),
        "opponent_errors": (rheb.get(opp) or {}).get("e"),
        "opponent_walks": (rheb.get(opp) or {}).get("b"),
        "team_er": ((record.get("teamPitchingBoxscore") or {}).get(side) or {}).get("er"),
        "line_score": json.dumps({"team": inn.get(side), "opponent": inn.get(opp)}),
        "win_pitcher": by_decision.get("W") or game.get("win_pitcher"),
        "lose_pitcher": by_decision.get("L") or game.get("lose_pitcher"),
        "save_pitcher": by_decision.get("S"),
        "notes": json.dumps(record.get("etcRecords") or [], ensure_ascii=False),
    }
    # 박스스코어 기준으로 점수 재확인
    if (rheb.get(side) or {}).get("r") is not None:
        extra["team_score"] = rheb[side]["r"]
        extra["opponent_score"] = rheb[opp]["r"]

    batting, pitching = [], []
    batters = record.get("battersBoxscore") or {}
    pitchers = record.get("pitchersBoxscore") or {}
    for s in ("away", "home"):
        for i, b in enumerate(batters.get(s) or []):
            row = batting_row(gid, codes[s], i, b)
            if row:
                batting.append(row)
        for i, p in enumerate(pitchers.get(s) or []):
            pitching.append(pitching_row(gid, codes[s], i, p, decisions))

    standings = record.get(f"{side}Standings")
    return extra, batting, pitching, standings
