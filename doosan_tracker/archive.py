"""경기별 원본 JSON 보관소. 종료/취소된 경기를 한 번만 쓰고 이후에는 바꾸지 않는다."""
import json
from pathlib import Path

from .config import ARCHIVE_DIR


def path_for(season: int, game_id: str) -> Path:
    return ARCHIVE_DIR / str(season) / f"{game_id}.json"


def write(season: int, game_id: str, schedule: dict, record: dict | None, fetched_at: str) -> Path:
    path = path_for(season, game_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = {"fetched_at": fetched_at, "schedule": schedule, "record": record}
    path.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return path


def read_all():
    """(game_id, 문서) 를 순서대로 돌려준다."""
    for path in sorted(ARCHIVE_DIR.glob("*/*.json")):
        yield path.stem, json.loads(path.read_text(encoding="utf-8"))
