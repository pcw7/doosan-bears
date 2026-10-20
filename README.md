# 두산 베어스 기록 자동 수집기

[![경기 기록 수집 & 배포](https://github.com/pcw7/doosan-bears/actions/workflows/sync.yml/badge.svg)](https://github.com/pcw7/doosan-bears/actions/workflows/sync.yml)

두산 베어스 경기가 끝날 때마다 경기 결과와 선수 기록을 자동으로 모아 웹 대시보드로 보여줍니다.
경기 시간대(한국시간 17:05~01:45)에 20분마다 새 경기를 확인해 수집하고, GitHub Pages에 배포합니다.

**대시보드: https://pcw7.github.io/doosan-bears/** (2008년~현재, 시즌마다 페이지)

| 메인 화면 | 시즌 흐름 탭 |
|---|---|
| ![메인 화면: 시즌 요약, 성적 줄, KBO 순위표, 경기 결과](docs/screenshot-main.png) | ![시즌 흐름 탭: 순위 추이, 승패 마진, 월별 득실점 그래프](docs/screenshot-flow.png) |

## 화면

| 위치 | 내용 |
|---|---|
| 상단 | **시즌 요약 한 줄**(순위·포스트시즌 결과·다음 경기), 성적 줄(승패·승률·순위·포스트시즌·득실·최근 10경기와 연속), **시즌 선택**, **선수 검색** |
| 왼쪽 | **KBO 리그 순위표** (넓은 화면에서 스크롤을 따라다님, 좁은 화면에선 본문 위에 접힘) |
| 다음 경기 | **선발 투수 매치업**(시즌·상대 전적), 시즌 상대 전적, 양 팀 최근 5경기, 순위 |
| 경기 결과 탭 | 경기 목록(20경기씩 더보기), 누르면 박스스코어(이닝별 점수·타자·투수·결승타 등) |
| 선수 탭 | **팀 내 1위** 카드, 포지션별·등번호순 선수 카드(사진·번호·주요 기록) |
| 타자 / 투수 기록 탭 | 시즌 누적 기록 표 (열 제목으로 정렬, 규정타석·규정이닝 필터) |
| 팀 기록 탭 | 팀 타격·수비, 투수진(선발/불펜), 상황별·상대 팀별·월별 성적, 역전승/역전패 |
| 시즌 흐름 탭 | 정규시즌 **순위 추이**, **승패 마진**(승−패), **월별 득실점** 그래프 (마우스·←/→ 키로 경기별 값, 표로 보기), **연속 기록**(최다 연승·연패, 연속 경기 안타·출루, 지금 이어지는 기록) |
| 역대 기록 탭 | **시즌별 팀 성적**(순위·포스트시즌 결과), **한 시즌 개인 기록** 상위 5명, **연속 기록**(최다 연승·연패, 연속 경기 안타·출루) (2008년~) |
| 선수 기록 창 | 이름·카드를 누르면 프로필(번호·생년월일·키/몸무게·출신·드래프트·WAR), **두산 통산 기록**(정규시즌 시즌별 기록과 통산 합계), 그 시즌 경기별 기록 |

- 정규시즌 / 포스트시즌 / 시범경기를 탭으로 나눠 봅니다.
- 포스트시즌 경기에는 "와일드카드 2차전"처럼 차전과 그 경기까지의 시리즈 전적이 붙습니다. 와일드카드는 4위 팀의 1승 어드밴티지를 포함합니다.
- 포스트시즌 결과(탈락·다음 라운드 진출·진행 중)는 시리즈 전적으로 판단합니다. 그래서 다음 라운드 일정이 아직 안 나왔거나, 필요 없어진 "필요 시" 경기가 일정에 남아 있어도 맞게 표시됩니다. 일정에서 빠진 예정 경기는 DB에서도 지웁니다.
- 시즌 중 다른 팀에서 온 선수는 **"이적"** 배지가 붙고, 두산 기록과 공식 시즌 기록을 함께 보여줍니다.
- 다른 시즌의 선수 기록 창으로 바로 가는 주소: `<시즌>.html#p=<선수ID>` (검색·역대 기록에서 사용)

## 동작 방식

```
cron-job.org — 한국시간 매일 17:05 ~ 01:45, 20분마다 GitHub에 "실행" 요청 (코드 push 때, 수동 실행 때도 실행)
 ↓
GitHub Actions
 ┌ 수집 작업 (collect)
 │   원본에서 DB 복원 → 네이버에서 두산 일정 확인
 │   → 새로 끝난 경기의 박스스코어 저장 → 새 경기 출전 선수의 등번호·프로필 갱신
 │   → 리그 순위표 갱신 → 다음 경기 미리보기 → 19개 시즌 웹페이지 생성
 │   → 바뀐 데이터만 커밋 ("기록 추가: 1경기" / "선수 정보·순위 갱신")
 └ 배포 작업 (deploy) → GitHub Pages
```

## 내 PC에서 실행하기

```powershell
pip install -r requirements.txt          # 처음 한 번 (암호화용 cryptography)
git pull                                 # Actions가 수집한 최신 데이터 받기
python -m doosan_tracker report          # reports/ 에 웹페이지·CSV 생성 (브라우저로 reports/index.html 열기)
python -m doosan_tracker status          # DB 현황
python -m doosan_tracker sync            # 새 경기 수집 + 리포트 (보통은 Actions가 함)
python -m doosan_tracker sync --from 2025-03-01 --to 2025-11-30   # 기간 지정 수집
python -m doosan_tracker info --all      # 모든 시즌 선수 정보·순위표 다시 채우기
```

자동 수집은 Actions가 맡습니다. PC에서 `sync`를 정기적으로 돌리면 같은 파일을 두 곳에서 만들어 `git pull` 때 충돌하니 피하세요.
직접 수집한 데이터는 `data/`를 커밋하고 push하면 Actions에도 반영됩니다.

## 구성

사용 기술: Python 3.12 (표준 라이브러리 + `cryptography`), SQLite, GitHub Actions, GitHub Pages, cron-job.org.
웹페이지는 HTML 파일 하나에 데이터를 넣어 만들고, 그래프는 차트 라이브러리 없이 SVG로 직접 그립니다.

```
doosan_tracker/
  naver.py      네이버 스포츠 API 호출
  archive.py    원본 암호화 보관 (data/games, data/players, data/standings)
  parse.py      원본 → 경기/타자/투수 행 (2루타·3루타·사구·희생타·도루 보정 포함)
  db.py         SQLite 스키마와 저장
  sync.py       원본에서 DB 복원 → 새로 끝난 경기만 수집
  players.py    선수 등번호(문자중계 명단)·프로필·WAR
  league.py     리그 순위표 (정규시즌 기준으로 다시 계산)
  preview.py    다음 경기 미리보기
  stats.py      시즌·팀·역대 기록 집계, 이적 선수 판별
  export.py     CSV 내보내기
  report.py     웹페이지 생성 (templates/report.html)
.github/workflows/sync.yml   자동 수집 + Pages 배포
docs/                        README 화면 캡처
```
