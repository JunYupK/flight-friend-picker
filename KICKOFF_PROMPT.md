# 새 세션 킥오프 프롬프트

> 사용법: 이 `flight_picker_bootstrap/` 내용을 **새 flight-picker 레포 루트로 복사**한 뒤,
> 새 레포의 Claude Code 세션에 아래 프롬프트를 붙여넣으세요.
> (포팅 파일은 이미 `flight_picker/`에 있고, 설계는 `PROJECT_PLAN.md`에 있습니다.)

---

```
flight-picker라는 로컬 CLI를 구현해줘. ICN 출발 일본 왕복 항공권을 온디맨드로 라이브 크롤(구글
플라이트+네이버)해서, 터미널에서 고른 조건으로 스코어링·랭킹하고, 선택하면 예약 딥링크로 여는 도구야.
전체 설계는 PROJECT_PLAN.md 참고.

[이미 포팅해 둔 파일] flight_picker/ 아래에 my-flight-friend에서 가져온 크롤 프리미티브가 있어:
- gflights.py: 구글 tfs 검색URL(_build_tfs_url)·예약딥링크(_build_booking_url/_build_booking_tfs)·
  extract JS(_extract_js)·파서(_parse_flight_cards)
- naver.py: 네이버 URL(_build_naver_url)·extract JS(_extract_js)·파서(_parse_cards)
- crawl_utils.py: crawl_one_way_batches, make_scroll_js
- combine.py: combine_roundtrips(편도 out/in → 왕복 offer, 가격오름차순)
- constants.py: SEARCH_CONFIG(topk_per_date=5, request_delay=1.0, stay_durations 등), KST,
  ORIGIN='ICN', JAPAN_AIRPORTS 프리셋, _AIRLINE_IATA, TFS_TEMPLATES(빈 dict)
이 파일들의 셀렉터/URL/protobuf 인코딩은 라이브 사이트 역공학 결과라 절대 임의로 바꾸지 마.

[구현할 것]
1) flight_picker/crawl.py:
   async def crawl_offers(dest, dest_name, dep_date, ret_date, sources) -> list[dict]
   - 소스별 out(ICN→dest, dep_date)+in(dest→ICN, ret_date) URL 2개만 생성.
     구글은 gflights._build_tfs_url, 네이버는 naver._build_naver_url.
   - AsyncWebCrawler(BrowserConfig headless+viewport1920x1080+--no-sandbox 등) +
     crawl_utils.crawl_one_way_batches(batch_size=2, parse_cards=소스파서,
     run_config=CrawlerRunConfig(원본 설정: 구글 magic·js_code=[make_scroll_js,_extract_js]·
     wait_for li.pIav2d·delay_before_return_html=4·cache_mode=bypass·page_timeout=15000 /
     네이버 wait_for combination_ConcurrentItemContainer·delay=8·page_timeout=30000)).
   - enrich: 각 flight에 date·search_url(=meta['url']) 추가, 구글은 gflights._build_booking_url로 booking_url 추가.
   - out/in 분리 → combine.combine_roundtrips(source, origin='ICN', destination=dest,
     destination_name=dest_name, stay_durations=[(ret-dep).days], topk=SEARCH_CONFIG['topk_per_date']).
   - 두 소스 offer 병합. 소스 하나 실패해도 로깅 후 계속. 동기 래퍼 crawl_offers_sync=asyncio.run(...).
   - 주의: 구글 TFS_TEMPLATES가 비어 있으면 _build_tfs_url이 None → 구글 스킵. templates.json이
     있으면 로드해 constants.TFS_TEMPLATES.update()로 패치. 없으면 네이버만으로 진행(경고 로그).

2) flight_picker/score.py (순수 함수, 크롤/네트워크 의존 0):
   - stay_minutes(offer) -> int|None: (ret_date @ in_dep_time) - (dep_date @ out_arr_time),
     시간이 None/"??:??"이면 None.
   - filter_offers(offers, *, out_dep_before=None, in_dep_after=None, direct_only=False,
     exclude_airlines=()) : 가는편 출발시각<=out_dep_before, 오는편 출발시각>=in_dep_after,
     직항만(out_stops==0 and in_stops==0), 항공사 제외(out/in 어느 쪽이든 포함 시 제외).
   - rank_offers(offers, *, priority) : 'price'(price 오름차순) / 'stay'(stay_minutes 내림차순,
     동점 price 오름차순) / 'balance'(후보 min-max 정규화 가중합, 체류↑·가격↓·가는편 출발 이른↑).
     각 offer에 stay_minutes·score·rank 부여해 반환.

3) flight_picker/cli.py (questionary + rich):
   목적지 select(JAPAN_AIRPORTS + 직접입력) → 출발/귀국일 text 입력(YYYY-MM-DD 검증) →
   필터 선택(우선순위 select 💰가격최소/⏱️체류최대/⚖️균형, 가는편 출발 이전 시각, 오는편 출발 이후 시각,
   직항만 confirm, 제외 항공사 checkbox) → 라이브 크롤(rich.status 스피너, crawl_offers_sync) →
   filter_offers→rank_offers→rich.table 랭킹(순위·가는편/오는편 시각·항공사·체류·가격·소스) →
   행 select 후 webbrowser.open(offer['out_url']).
   argparse 논-인터랙티브도: --dest --out --in --priority --out-before --in-after --direct.

4) flight_picker/__main__.py (python -m flight_picker → cli.main()),
   requirements.txt(crawl4ai,questionary,rich)는 이미 있음, README 갱신, .gitignore에 templates.json.

[테스트]
- tests/test_score.py: rank_offers 3모드 정렬, filter_offers 각 조건, stay_minutes 시간누락 처리를
  픽스처 offer dict로 검증(순수, 네트워크 없음).
- tests/test_crawl.py: crawl_utils.crawl_one_way_batches를 monkeypatch로 픽스처 (meta, flights) 반환하게 하고,
  crawl_offers가 enrich→combine_roundtrips까지 올바른 offer를 만드는지 검증. 실제 crawl4ai/HTTP 호출 금지.

[제약] 수하물 필터 미지원(데이터 없음), 인원=성인1 고정, 정확한 날짜 1쌍, 라이브 크롤은 안티봇/네트워크에 좌우.

먼저 score.py를 TDD로(test_score.py → score.py) 짜서 verify하고, 그다음 crawl.py(+test_crawl.py) → cli.py 순서로 진행해줘.
```
