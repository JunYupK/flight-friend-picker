# AGENTS.md — flight-picker

> 에이전트가 이 레포에서 작업할 때 항상 먼저 읽는 하네스(Harness) 명세서.
> 규칙은 가능한 한 `tests/test_architecture.py`(ast 정적 분석)로 기계적으로 강제한다 — 충돌 시 본 문서 우선.

---

## 1. 프로젝트 개요

**ICN 출발 일본 왕복 항공권 온디맨드 비교 CLI.**
목적지·날짜·조건을 터미널에서 고르면 구글 플라이트+네이버를 그 자리에서 라이브 크롤 →
조건 스코어링 → 랭킹 출력 → 선택 시 예약 딥링크로 이동한다.

my-flight-friend(배치 가격 모니터링)에서 분리된 독립 프로젝트.
**로컬 `python` 실행 전용 — DB 없음, 웹서버 없음, cron 없음.** (배포는 추후 별도 결정.)

---

## 2. 아키텍처 레이어 (의존성 방향 엄수)

```
constants ──→ primitives ──→ crawl ──→ cli
              (gflights·naver·          ↑
               crawl_utils·combine)     │
              score (순수) ─────────────┘
```

### 레이어별 책임

| 레이어 | 파일 | 책임 | 금지 |
|--------|------|------|------|
| **Constants** | `constants.py` | 설정값, 공항 프리셋, TFS_TEMPLATES dict | 로직, I/O |
| **Primitives** | `gflights.py`, `naver.py`, `crawl_utils.py`, `combine.py` | URL/딥링크 생성, extract JS, 파서, 배치 크롤 루프, 왕복 조합 | 크롤 오케스트레이션, UI, 상위 레이어 import |
| **Crawl** | `crawl.py` | AsyncWebCrawler 수명주기, 소스별 URL 조립→배치 크롤→enrich→combine, 소스 병합 | UI 출력(rich/questionary), 스코어링 |
| **Score** | `score.py` | 순수 필터링/스코어링/랭킹 | **일체의 I/O·네트워크·crawl4ai·UI 의존** |
| **CLI** | `cli.py`, `__main__.py` | questionary/rich UI, argparse, webbrowser 열기 | crawl4ai 직접 사용, primitives 직접 호출 |

### 의존성 규칙

```
✅ 허용
cli    → crawl, score, constants
crawl  → gflights, naver, crawl_utils, combine, constants
score  → constants (필요 시), stdlib
primitives → constants, stdlib (+crawl4ai는 TYPE_CHECKING 한정)

❌ 금지
score      → crawl4ai / crawl / cli / questionary / rich / webbrowser / requests (순수성)
primitives → crawl / score / cli (역방향 금지)
cli        → crawl4ai / gflights / naver / crawl_utils (크롤은 crawl.py 경유)
어디서든   → psycopg2 / fastapi / flight_monitor (이 프로젝트는 DB·웹서버 없음)
crawl4ai 런타임 import → crawl.py 전용 (다른 모듈은 TYPE_CHECKING 가드 필수)
```

> 본 규칙은 `tests/test_architecture.py`에서 기계 검증한다 (네트워크·crawl4ai 불필요).

---

## 3. 파일 위치 규칙

새 파일을 만들기 전에 확인할 것. 위치가 불명확하면 **파일 생성 전에 물어본다.**

| 무엇을 만드는가 | 위치 |
|----------------|------|
| 스코어링/필터/랭킹 로직 | `flight_picker/score.py` |
| 크롤 오케스트레이션 (소스 추가·병합·enrich) | `flight_picker/crawl.py` |
| 새 데이터 소스 프리미티브 (URL·JS·파서) | `flight_picker/{source}.py` + `crawl.py`에 등록 |
| 터미널 UI / 인자 파싱 | `flight_picker/cli.py` |
| 설정값·상수 | `flight_picker/constants.py` |
| 왕복 조합 로직 변경 | `flight_picker/combine.py` |
| 테스트 | `tests/` |

---

## 4. 코딩 규칙

- **타입 힌트 필수**: 함수 파라미터·반환값 모두. `Any` 금지.
- **async 일관성**: `asyncio.run()`은 진입점(`crawl_offers_sync`, `__main__`)에서만. 중첩 금지.
- **에러 처리**: 크롤 개별 실패는 `print(f"[{SOURCE} ...]")` 로깅 후 계속. 전체를 중단하는 `raise` 금지 — 한 소스가 죽어도 다른 소스 결과는 살린다.
- **하드코딩 금지**: 타임아웃·topk·delay 등은 `constants.SEARCH_CONFIG` 경유.
- **Offer/Leg dict 인터페이스** (`combine_roundtrips` 입출력 계약 — 필드 추가는 자유, 기존 필드 제거·개명 금지):
  - leg: `date, price, airline, dep_time("HH:MM"), arr_time, duration_min, stops(0=직항), dep_airport, arr_airport, search_url, booking_url`
  - offer: `source, trip_type, origin, destination, destination_name, departure_date, return_date, stay_nights, price, out_/in_ 항공사·시간·경유·가격·URL, is_mixed_airline, checked_at`
  - 전체 필드 목록은 `PROJECT_PLAN.md` Part B.

---

## 5. 역공학 코드 보호 (최중요)

`gflights.py`·`naver.py`의 **DOM 셀렉터, URL 형식, tfs protobuf 인코딩은 라이브 사이트 역공학 결과**다.

- 리팩터·정리 목적의 임의 수정 **절대 금지** (동작이 조용히 깨진다).
- 셀렉터 변경은 **사이트가 실제로 바뀌어 크롤이 0건일 때만**, 라이브 페이지 확인 후 수행.
- 셀렉터/URL/인코딩을 바꾸면 `PROJECT_PLAN.md` Part B를 같은 커밋에서 동기화.
- `crawl_one_way_batches`의 "(meta, 가격 오름차순 flights) 반환, 개별 실패 로깅 후 계속" 계약 유지.

---

## 6. 테스트 규칙

- **실제 외부 호출 금지**: 테스트에서 crawl4ai/HTTP 호출 금지. `crawl_one_way_batches`를 `monkeypatch`로 픽스처 반환하게 대체.
- **score.py는 순수 테스트**: 픽스처 offer dict만으로 검증. 네트워크·파일 I/O 없음.
- **새 score/crawl 함수 → 테스트 동반** (TDD: 테스트 먼저).
- `tests/test_architecture.py`는 §2 의존성 규칙을 항상 검증한다 — **어떤 PR에서도 실패 상태로 머지 금지.**

```bash
pytest tests/                      # 전체
pytest tests/test_architecture.py  # 레이어 규칙만 (의존성 0, 항상 실행 가능)
```

---

## 7. 금지사항 (절대 위반 금지)

```
❌ gflights/naver의 셀렉터·URL·protobuf 인코딩 임의 수정 (§5 절차 외)
❌ score.py에 crawl4ai/네트워크/UI import (순수성 위반)
❌ cli.py에서 crawl4ai 또는 primitives 직접 사용 (crawl.py 경유 필수)
❌ crawl.py 외 모듈의 crawl4ai 런타임 import (TYPE_CHECKING 가드 필수)
❌ psycopg2/fastapi/flight_monitor import (DB·웹서버 없는 프로젝트)
❌ asyncio.run() 중첩 (진입점 전용)
❌ 테스트에서 실제 크롤/HTTP 호출
❌ templates.json 커밋 (개인 노선 데이터 — templates.example.json만 커밋)
❌ SEARCH_CONFIG 우회 하드코딩 (타임아웃·topk·delay)
```

---

## 8. 명령어 레퍼런스

```bash
pip install -r requirements.txt
playwright install chromium

# 인터랙티브 실행
python -m flight_picker

# 논-인터랙티브
python -m flight_picker --dest FUK --out 2026-08-14 --in 2026-08-18 --priority balance

# 테스트
pytest tests/
pytest tests/test_architecture.py
```
