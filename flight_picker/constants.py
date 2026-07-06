# flight_picker/constants.py
#
# my-flight-friend/flight_monitor/config.py 에서 포팅.
# DB 의존(JAPAN_AIRPORTS/TFS_TEMPLATES 를 DB에서 채우던 부분)을 제거하고,
# TFS_TEMPLATES 는 런타임에 templates.json 으로 패치한다.

from datetime import timedelta, timezone

KST = timezone(timedelta(hours=9))

ORIGIN = "ICN"

# CLI 목적지 select 용 프리셋 (IATA → 표시명). 필요 시 추가.
JAPAN_AIRPORTS: dict[str, str] = {
    "NRT": "도쿄/나리타",
    "HND": "도쿄/하네다",
    "KIX": "오사카/간사이",
    "FUK": "후쿠오카",
    "CTS": "삿포로/신치토세",
    "OKA": "오키나와/나하",
    "NGO": "나고야/주부",
}

# Google Flights tfs= 파라미터 템플릿. 노선별 1회 수동 확보 후 templates.json 에 넣는다.
# key: "ICN_FUK" 형식(출발_도착), value: base64 tfs 값 또는 전체 URL.
# 런타임에 cli/crawl 이 templates.json 을 로드해 이 dict 를 update() 한다.
TFS_TEMPLATES: dict[str, str] = {}

# 항공사 한글명 → IATA 코드 매핑 (표시/딥링크 보조용).
_AIRLINE_IATA: dict[str, str] = {
    "대한항공": "KE", "아시아나항공": "OZ",
    "진에어": "LJ", "제주항공": "7C", "티웨이항공": "TW",
    "에어서울": "RS", "에어부산": "BX", "이스타항공": "ZE",
    "일본항공": "JL", "전일본공수": "NH", "ANA": "NH",
    "피치항공": "MM", "Peach": "MM", "피치": "MM",
    "집에어": "ZG", "ZIPAIR": "ZG", "Zipair": "ZG",
    "스프링재팬": "IJ", "Spring Japan": "IJ",
    "중국동방항공": "MU", "중국남방항공": "CZ",
    "에어재팬": "NQ", "Air Japan": "NQ",
    "스타플라이어": "7G", "스카이마크": "BC",
    "배틀스타": "AD",
}

SEARCH_CONFIG = {
    # 공통
    "adults": 1,
    "currency": "KRW",
    "nonStop": False,

    # 조합 정책
    "allow_mixed_airline": True,
    "stay_durations": [3, 4, 5],   # combine_roundtrips 기본 (CLI는 실제 날짜차로 덮어씀)
    "topk_per_date": 5,            # 날짜별 Top-K 유지

    # 성능/안전
    "request_delay": 1.0,
    "page_timeout_ms": 30000,      # Naver(delay 8s)용 기본 page_timeout
    "gf_page_timeout_ms": 15000,   # Google Flights fast-fail 타임아웃
}
