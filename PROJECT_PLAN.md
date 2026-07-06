# flight-picker — 프로젝트 계획 & 포팅 컨텍스트

> my-flight-friend에서 갈라져 나오는 독립 CLI. 이 문서는 ① 설계(Part A) ② 새 레포로 가져온
> 취약한 역공학 지식(Part B)을 담는다. 구현 지시는 `KICKOFF_PROMPT.md` 참고.

---

## Part A — 설계

**한 줄:** 목적지·날짜·조건을 터미널에서 고르면 그 자리에서 구글/네이버를 라이브 크롤 →
조건 스코어링 → 랭킹 출력 → 선택 시 예약 딥링크로 이동하는 로컬 Python CLI.

**결정(확정):** ① 독립 레포 ② 로컬 `python` 실행 우선(배포 나중) ③ 라이브 온디맨드 크롤 ④ 구글+네이버.

**레포 구조**
```
flight-picker/
  flight_picker/
    __init__.py
    __main__.py        # python -m flight_picker → cli.main()
    cli.py             # 인터랙티브(questionary+rich) + argparse 논-인터랙티브
    crawl.py           # 라이브 단일 노선+날짜 크롤 오케스트레이션
    score.py           # 순수 스코어링/필터 (의존 0)
    # ── 포팅된 크롤 프리미티브 (이미 존재) ──
    gflights.py  naver.py  crawl_utils.py  combine.py  constants.py
    templates.json     # 구글 tfs 노선 템플릿 (사용자 1회) — gitignore
  tests/  test_score.py  test_crawl.py
  requirements.txt  README.md  .gitignore
```

**모듈 설계**
- `crawl.py :: async crawl_offers(dest, dest_name, dep_date, ret_date, sources) -> list[offer]`
  - 소스별 out URL(ICN→dest, dep_date) + in URL(dest→ICN, ret_date) **2개**만 생성.
    구글 `gflights._build_tfs_url`(템플릿 필요), 네이버 `naver._build_naver_url`.
  - `AsyncWebCrawler(BrowserConfig(...))` + `crawl_utils.crawl_one_way_batches(..., parse_cards=소스파서, batch_size=2)`.
    CrawlerRunConfig는 소스 원본 설정: 구글 `wait_for li.pIav2d`·delay 4·timeout 15000 / 네이버 `wait_for combination_ConcurrentItemContainer`·delay 8·timeout 30000.
  - enrich(각 flight에 date·search_url, 구글은 `_build_booking_url`로 booking_url) → out/in 분리 →
    `combine.combine_roundtrips(stay_durations=[(ret-dep).days], topk=SEARCH_CONFIG["topk_per_date"])`.
  - 두 소스 병합. 소스 하나 실패해도 계속(로깅). 동기 래퍼 `crawl_offers_sync = asyncio.run(...)`.
  - **주의:** 구글 `TFS_TEMPLATES`는 기본 비어 있어 `_build_tfs_url`이 None → 구글 0건.
    `templates.json`을 로드해 `constants.TFS_TEMPLATES.update(...)`로 패치. 없으면 네이버만.
- `score.py`(순수):
  - `stay_minutes(offer)` = (ret_date @ in_dep_time) − (dep_date @ out_arr_time); 시간 없으면 None.
  - `filter_offers(..., out_dep_before, in_dep_after, direct_only, exclude_airlines)`.
  - `rank_offers(..., priority)`: `price`(가격↑) / `stay`(체류↓) / `balance`(정규화 `w_stay·stay + w_price·(1−price) + w_early·(1−out_dep)`). offer에 `stay_minutes/score/rank` 부여.
- `cli.py`(questionary+rich): 목적지 select → 출발/귀국일 입력 → **필터 선택**(우선순위 💰/⏱️/⚖️,
  가는편 출발 이전 시각, 오는편 출발 이후 시각, 직항만, 제외 항공사) → 라이브 크롤(rich 스피너) →
  `rich.table` 랭킹 → 행 선택 시 `webbrowser.open(out_url)`. argparse 논-인터랙티브도 지원.

---

## Part B — 포팅한 취약한 역공학 지식 (셀렉터/URL/스키마)

> 아래 지식은 이미 `flight_picker/*.py` 에 코드로 포팅되어 있다. 이 문서는 그 계약을 요약해,
> 셀렉터가 깨지거나 리팩터할 때 무엇을 보존해야 하는지 잃지 않도록 남긴다.

**Offer/leg dict 스키마** (`combine_roundtrips` 입출력 계약)
- leg(크롤 결과): `date, price, airline, dep_time("HH:MM"), arr_time, duration_min, stops(0=직항), dep_airport, arr_airport, search_url, booking_url` (+구글은 `flight_numbers/segment_airports/segment_dates`).
- offer(왕복): `source, trip_type, origin, destination, destination_name, departure_date, return_date, stay_nights, price(왕복합산 KRW), out_airline, in_airline, is_mixed_airline, out_dep_time, out_arr_time, out_duration_min, out_stops, in_dep_time, in_arr_time, in_duration_min, in_stops, out_arr_airport, in_dep_airport, out_url, in_url, out_price, in_price, checked_at`.

**구글 플라이트** (`gflights.py`)
- 검색 URL: `.../travel/flights/search?tfs={base64_protobuf}&curr=KRW&hl=ko`. 노선별 tfs 템플릿 필요 →
  decode 후 첫 `\d{4}-\d{2}-\d{2}`를 대상 날짜로 치환 후 re-encode(`_build_tfs_url`).
- 예약 딥링크: `.../booking?tfs=...`(`_build_booking_tfs`). protobuf 필드맵:
  outer{1=28, 2=2, 3=itin, 8=1, 9=1, 14=1, 16=…, 19=2}, itin{2=date, 4=segment{1=dep,2=date,3=arr,5=airline,6=flight_num}, 13=origin, 14=dest}. **인코딩 임의 변경 금지.**
- extract JS 셀렉터: 카드 `li.pIav2d`; 가격 `.YMlIz.FpEdX.jLMuyc > span[aria-label]`("250436 대한민국 원");
  출발 `.wtdjmc.YMlIz`; 도착 `.XWcVob.YMlIz`; 경유 `.VG3hNb`("직항"/"경유 N회"); 소요 `.gvkrdb`("총 비행 시간은 2시간 20분");
  항공사 `.h1fkLb span`; 공항 `.iCvNQ`; 편명 `[data-travelimpactmodelwebsiteurl]`의 `itinerary=ICN-NRT-YP-735-20260501`
  (콤마=경유, parts=DEP-ARR-AIRLINE-FNUM-YYYYMMDD); 한국어 오전/오후 파싱. 결과 `#__fl__` div JSON → `_parse_flight_cards`. 가격 sanity 20000~3000000.
- crawl4ai: `magic=True`, `js_code=[make_scroll_js(), _extract_js()]`, `wait_for="js:() => !!document.querySelector('li.pIav2d')"`, `delay_before_return_html=4.0`, `cache_mode="bypass"`, `page_timeout=15000`.

**네이버** (`naver.py`)
- URL: `.../flights/international/{SEL:city|CODE:airport}-{...}-{YYYYMMDD}?adult=1&isDirect=false&fareType=Y&tripType=OW`.
  출발=`SEL:city`, 도착=`{CODE}:airport`. **템플릿 불필요 → 즉시 동작.** 딥링크 없음 → `search_url`만(열면 재검색).
- extract JS 셀렉터: 카드 `div[class*="combination_ConcurrentItemContainer"]`; 가격 `i[class*="item_num"]`;
  항공사 `b[class*="airline_name"]`; 시간 `b[class*="route_time"]`(0=출발,1=도착); 공항 `i[class*="route_code"]`;
  상세 `button[class*="route_details"]`("직항, 02시간 10분"/"경유 1, 26시간 25분"). 결과 `#__nv__` div JSON → `_parse_cards`.
- crawl4ai: `wait_for` = 위 카드 셀렉터, `delay_before_return_html=8.0`, `page_timeout=30000`.

**공통** (`crawl_utils.py`, `constants.py`)
- `make_scroll_js`: 최대 5회 스크롤(1.5s 간격, 높이 정체 시 중단).
- `crawl_one_way_batches`: `batch_size`씩 `arun_many`, 개별 실패 로깅 후 계속(raise 금지), 반환 `(meta, 가격오름차순 flights)`.
- `BrowserConfig(headless=True, viewport=1920x1080, extra_args=["--disable-blink-features=AutomationControlled","--no-sandbox","--disable-dev-shm-usage","--disable-gpu"])`.
- `SEARCH_CONFIG`: `topk_per_date=5`, `request_delay=1.0`, `stay_durations=[3,4,5]`, `adults=1`, `gf_page_timeout_ms=15000`, `page_timeout_ms=30000`.

**combine_roundtrips 로직:** 날짜별 인덱싱 → 날짜별 topk 절단 → out[d] × in[d+stay] 교차 → `is_mixed_airline = out_al!=in_al` → 가격 오름차순.

**스코어링 명세(사용자):** 체류 = 오는편 출발 − 가는편 도착; 합리성 = 체류분/가격; 가는편 이른 순 가점; ⚖️균형이 기본 정렬.

**딥링크/세션만료:** 구글 booking 딥링크·네이버 search URL 모두 열 때 실시간 재가격/재검색 → 클릭 시점 재크롤 불필요.

**MVP 밖 한계:** 구글 tfs 템플릿 노선별 1회 확보(없으면 네이버만) · 수하물 정보 없음(필터 미지원) · 인원=성인1 고정 · 정확한 날짜 1쌍 · 라이브 크롤은 안티봇/네트워크에 좌우.
