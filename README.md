# flight-picker

ICN 출발 일본 왕복 항공권을 **온디맨드로 라이브 크롤**(구글 플라이트 + 네이버항공)해서,
터미널에서 고른 조건(가는편 이른 / 오는편 늦은 / 가격 합리 등)으로 **스코어링·랭킹**하고,
선택하면 **예약 딥링크**로 바로 여는 로컬 CLI 도구.

> my-flight-friend(배치 가격 모니터링)에서 갈라져 나온 독립 프로젝트. 우선 로컬 실행,
> 컴퓨팅 자원이 충분해지면 배포.

## 구성

- `flight_picker/constants.py` · `combine.py` · `crawl_utils.py` · `gflights.py` · `naver.py`
  — my-flight-friend에서 포팅한 **크롤 프리미티브**(구글 tfs·딥링크·DOM 셀렉터, 네이버 URL·셀렉터, 배치 크롤, 왕복 조합).
  이 파일들의 셀렉터/URL/protobuf 인코딩은 라이브 사이트 역공학 결과이므로 **임의 수정 금지**.
- `flight_picker/crawl.py` — 라이브 단일 노선+날짜 크롤 오케스트레이션 (소스별 URL 조립 → 배치 크롤 → enrich → 왕복 조합 → 소스 병합. 한 소스가 실패해도 나머지 결과 유지.)
- `flight_picker/score.py` — 순수 스코어링/필터/랭킹 (`stay_minutes` / `filter_offers` / `rank_offers`. 크롤·네트워크 의존 0.)
- `flight_picker/cli.py` · `__main__.py` — questionary+rich 인터랙티브 UI + argparse 논-인터랙티브. 랭킹 테이블에서 행을 고르면 예약 딥링크를 브라우저로 연다.
- `AGENTS.md` — **하네스 규칙**: 레이어 의존성, 파일 위치, 역공학 코드 보호, 금지사항. 에이전트 작업 전 필독.
- `CLAUDE.md` — LLM 행동 규범 (충돌 시 AGENTS.md 우선).
- `tests/` — `test_score.py`(순수 픽스처), `test_crawl.py`(`crawl_one_way_batches` monkeypatch — 실제 크롤 없음), `test_architecture.py`(AGENTS.md 규칙 ast 기계 강제).

전체 설계는 `PROJECT_PLAN.md` 참고.

## 랭킹 우선순위

- `price` 💰 — 왕복 가격 오름차순.
- `stay` ⏱️ — 현지 체류시간(오는편 출발 − 가는편 도착) 내림차순, 동점 시 가격 오름차순.
- `balance` ⚖️ (기본) — 후보 내 min-max 정규화 가중합: 체류 0.4 + 저가 0.4 + 이른 가는편 출발 0.2.

## 설치

```bash
pip install -r requirements.txt
playwright install chromium
```

## 구글 플라이트 tfs 템플릿 (선택, 구글 소스용)

구글 플라이트는 노선별 `tfs` 파라미터가 있어야 검색 URL을 만들 수 있습니다(네이버는 불필요).

1. 브라우저에서 구글 플라이트로 해당 노선(예: ICN→FUK) 왕복 검색.
2. 결과 페이지 URL에서 `tfs=` 값(또는 URL 전체)을 복사.
3. `flight_picker/templates.example.json`을 `flight_picker/templates.json`으로 복사한 뒤
   `"ICN_FUK"`, `"FUK_ICN"` 값에 붙여넣기.

템플릿이 없으면 **네이버 소스만으로도 동작**합니다(graceful degradation).

## 실행

```bash
# 인터랙티브 (목적지·날짜·조건을 터미널에서 선택)
python -m flight_picker

# 논-인터랙티브
python -m flight_picker --dest FUK --out 2026-08-14 --in 2026-08-18 --priority balance --out-before 12 --in-after 18
```

## 한계

- 인원 = 성인 1인 고정(가격이 1인 기준). 수하물 필터 미지원(크롤 데이터에 정보 없음).
- 정확한 출발/귀국 1쌍만(±N일 flex는 후속). 라이브 크롤은 사이트 안티봇/네트워크 상태에 좌우됩니다.
