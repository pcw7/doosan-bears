"""SQLite 저장소."""
import json
import sqlite3
from datetime import datetime
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS games (
    game_id          TEXT PRIMARY KEY,
    season           INTEGER NOT NULL,
    game_date        TEXT NOT NULL,          -- YYYY-MM-DD
    start_time       TEXT,                   -- HH:MM
    round_code       TEXT,                   -- kbo_r, kbo_ps_ks ...
    stage            TEXT,                   -- regular / postseason / exhibition / allstar
    stadium          TEXT,
    home_away        TEXT,                   -- H / A (두산 기준)
    opponent_code    TEXT,
    opponent_name    TEXT,
    team_score       INTEGER,
    opponent_score   INTEGER,
    result           TEXT,                   -- W / L / D (종료 경기만)
    status           TEXT NOT NULL,          -- FINAL / SCHEDULED / LIVE / CANCELLED / SUSPENDED
    team_hits        INTEGER,
    team_errors      INTEGER,
    team_walks       INTEGER,
    opponent_hits    INTEGER,
    opponent_errors  INTEGER,
    opponent_walks   INTEGER,
    team_er          INTEGER,                -- 팀 자책점 (공식 규칙상 투수 개인 자책점 합보다 적을 수 있음)
    team_outs        INTEGER,                -- 팀 투구 아웃 수 (박스스코어 팀 합계, 개인 투수 기록이 빠진 경기도 있음)
    line_score       TEXT,                   -- JSON {"team": [...], "opponent": [...]}
    team_starter     TEXT,
    opponent_starter TEXT,
    win_pitcher      TEXT,
    lose_pitcher     TEXT,
    save_pitcher     TEXT,
    notes            TEXT,                   -- JSON: 결승타/홈런/2루타/실책 등
    updated_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS batting (
    game_id     TEXT NOT NULL REFERENCES games(game_id) ON DELETE CASCADE,
    player_id   TEXT NOT NULL,
    player_name TEXT NOT NULL,
    team_code   TEXT NOT NULL,
    bat_order   INTEGER,
    seq         INTEGER,
    position    TEXT,
    is_sub      INTEGER,
    pa INTEGER, ab INTEGER, r INTEGER, h INTEGER, b2 INTEGER, b3 INTEGER, hr INTEGER,
    rbi INTEGER, bb INTEGER, hbp INTEGER, so INTEGER, sb INTEGER, sf INTEGER, sh INTEGER, gidp INTEGER,
    pa_results  TEXT,                        -- 타석 결과 (예: '좌2 3땅 중안 삼진')
    season_avg  TEXT,                        -- 박스스코어에 실린 공식 시즌 타율 (받은 시점 기준, 다른 팀 기록 포함)
    PRIMARY KEY (game_id, player_id)
);

CREATE TABLE IF NOT EXISTS pitching (
    game_id     TEXT NOT NULL REFERENCES games(game_id) ON DELETE CASCADE,
    player_id   TEXT NOT NULL,
    player_name TEXT NOT NULL,
    team_code   TEXT NOT NULL,
    seq         INTEGER,
    is_starter  INTEGER,
    outs INTEGER, ip TEXT, bf INTEGER, ab INTEGER, h INTEGER, r INTEGER, er INTEGER,
    bb INTEGER, hbp INTEGER, so INTEGER, hr INTEGER, pitches INTEGER,
    decision    TEXT,                        -- W / L / S / H
    -- 박스스코어에 실린 공식 시즌 기록 (받은 시점 기준, 다른 팀 기록 포함)
    season_era TEXT, season_w INTEGER, season_l INTEGER, season_s INTEGER, season_g INTEGER,
    PRIMARY KEY (game_id, player_id)
);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE INDEX IF NOT EXISTS idx_games_date ON games(game_date);
CREATE INDEX IF NOT EXISTS idx_batting_player ON batting(player_id);
CREATE INDEX IF NOT EXISTS idx_pitching_player ON pitching(player_id);
"""


SCHEMA_VERSION = 5  # 스키마를 바꾸면 올린다 → 기존 DB를 지우고 data/games 원본에서 다시 만든다


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    if conn.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        conn.executescript("".join(f"DROP TABLE {t};" for t in tables))
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _upsert(conn: sqlite3.Connection, table: str, row: dict, key: tuple[str, ...]) -> None:
    cols = list(row)
    updates = ", ".join(f"{c}=excluded.{c}" for c in cols if c not in key)
    conn.execute(
        f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))}) "
        f"ON CONFLICT ({', '.join(key)}) DO UPDATE SET {updates}",
        [row[c] for c in cols],
    )


def game_status(conn: sqlite3.Connection, game_id: str) -> str | None:
    r = conn.execute("SELECT status FROM games WHERE game_id = ?", (game_id,)).fetchone()
    return r["status"] if r else None


def save_game(conn: sqlite3.Connection, game: dict) -> None:
    _upsert(conn, "games", {**game, "updated_at": now()}, ("game_id",))


def save_final_game(conn, game: dict, batting: list[dict], pitching: list[dict]) -> None:
    """종료 경기를 박스스코어와 함께 한 트랜잭션으로 저장 (재실행해도 같은 결과)."""
    with conn:
        save_game(conn, game)
        conn.execute("DELETE FROM batting WHERE game_id = ?", (game["game_id"],))
        conn.execute("DELETE FROM pitching WHERE game_id = ?", (game["game_id"],))
        for row in batting:
            _upsert(conn, "batting", row, ("game_id", "player_id"))
        for row in pitching:
            _upsert(conn, "pitching", row, ("game_id", "player_id"))


def last_final_date(conn) -> str | None:
    r = conn.execute("SELECT MAX(game_date) d FROM games WHERE status = 'FINAL'").fetchone()
    return r["d"]


def set_meta(conn, key: str, value) -> None:
    with conn:
        _upsert(conn, "meta", {"key": key, "value": json.dumps(value, ensure_ascii=False)}, ("key",))


def get_meta(conn, key: str, default=None):
    r = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return json.loads(r["value"]) if r else default
