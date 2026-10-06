"""프로젝트 전역 설정."""
from pathlib import Path

TEAM_CODE = "OB"  # 네이버/KBO에서 두산 베어스 팀 코드 (OB 베어스 시절 코드)
TEAM_NAME = "두산 베어스"

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
ARCHIVE_DIR = DATA_DIR / "games"  # 경기별 원본 JSON, 암호화해서 git에 저장
KEY_PATH = ROOT / "archive.key"   # 원본 암호 키 (git에 올리지 않음, 환경변수 DOOSAN_ARCHIVE_KEY가 우선)
DB_PATH = DATA_DIR / "doosan.db"  # ARCHIVE_DIR에서 언제든 다시 만들 수 있는 캐시
SITE_DIR = ROOT / "reports"       # GitHub Pages로 배포되는 폴더
REPORT_PATH = SITE_DIR / "index.html"
CSV_DIR = SITE_DIR / "csv"
LOG_PATH = ROOT / "logs" / "sync.log"

# 네이버 roundCode → 경기 구분
STAGES = {
    "kbo_e": "exhibition",
    "kbo_r": "regular",
    "kbo_as": "allstar",
    "kbo_ps_wd": "postseason",
    "kbo_ps_sp": "postseason",
    "kbo_ps_po": "postseason",
    "kbo_ps_ks": "postseason",
}
ROUND_NAMES = {
    "kbo_e": "시범경기",
    "kbo_r": "정규시즌",
    "kbo_as": "올스타전",
    "kbo_ps_wd": "와일드카드",
    "kbo_ps_sp": "준플레이오프",
    "kbo_ps_po": "플레이오프",
    "kbo_ps_ks": "한국시리즈",
}

# 동기화 시 마지막 종료 경기 이전으로 다시 확인할 일수 (우천 순연/서스펜디드 대비)
LOOKBACK_DAYS = 7
# 앞으로 몇 일치 일정을 미리 받아둘지
LOOKAHEAD_DAYS = 14
# 박스스코어 요청 사이 대기 (초) — API 서버에 부담을 주지 않기 위해
REQUEST_DELAY = 0.4
