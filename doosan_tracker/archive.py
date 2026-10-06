"""원본 보관소 (암호화).

- 경기 원본: data/games/<시즌>/<경기ID>.json.enc — 종료/취소된 경기를 한 번만 쓰고 이후에는 바꾸지 않는다.
- 선수 정보: data/players/<시즌>.json.enc — 등번호·프로필, 갱신될 때마다 다시 쓴다 (players.py).

JSON을 gzip으로 압축한 뒤 Fernet(AES-128 + HMAC)으로 암호화한다.
키는 환경변수 DOOSAN_ARCHIVE_KEY(GitHub Actions) 또는 프로젝트 루트의 archive.key(내 PC)에서 읽는다.
키를 잃어버리면 저장된 원본을 복구할 수 없다.
"""
import gzip
import json
import os
from functools import cache
from pathlib import Path

from .config import ARCHIVE_DIR, KEY_PATH

KEY_ENV = "DOOSAN_ARCHIVE_KEY"
SUFFIX = ".json.enc"


@cache
def _fernet():
    try:
        from cryptography.fernet import Fernet
    except ImportError as e:
        raise RuntimeError("cryptography 패키지가 필요합니다: pip install -r requirements.txt") from e
    key = os.environ.get(KEY_ENV) or (KEY_PATH.read_text(encoding="ascii") if KEY_PATH.exists() else "")
    if not key.strip():
        raise RuntimeError(f"암호 키가 없습니다. 환경변수 {KEY_ENV}를 설정하거나 {KEY_PATH} 파일을 두세요.")
    return Fernet(key.strip())


def save_json(path: Path, obj) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    path.write_bytes(_fernet().encrypt(gzip.compress(raw, mtime=0)))
    return path


def load_json(path: Path):
    from cryptography.fernet import InvalidToken
    try:
        token = _fernet().decrypt(path.read_bytes())
    except InvalidToken:
        raise RuntimeError(f"암호 키가 맞지 않아 {path.name}을(를) 열 수 없습니다. archive.key 또는 {KEY_ENV}를 확인하세요.") from None
    return json.loads(gzip.decompress(token))


# ── 경기 원본 ──

def path_for(season: int, game_id: str) -> Path:
    return ARCHIVE_DIR / str(season) / f"{game_id}{SUFFIX}"


def write(season: int, game_id: str, schedule: dict, record: dict | None, fetched_at: str) -> Path:
    return save_json(path_for(season, game_id), {"fetched_at": fetched_at, "schedule": schedule, "record": record})


def entries() -> list[tuple[str, Path]]:
    """(경기ID, 파일 경로) 목록. 복호화는 read()에서 필요한 것만 한다."""
    return [(p.name.removesuffix(SUFFIX), p) for p in sorted(ARCHIVE_DIR.glob(f"*/*{SUFFIX}"))]


def read(path: Path) -> dict:
    return load_json(path)
