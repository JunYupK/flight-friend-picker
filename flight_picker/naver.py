# flight_picker/naver.py
#
# my-flight-friend/flight_monitor/collector_naver.py 에서 헬퍼만 발췌 포팅.
# 유지: 편도 검색 URL / extract JS / 카드 파서.
# 제거: _fetch_route/_fetch_airport/_fetch_all (save_legs = DB 의존).
#
# ⚠️ URL 형식과 DOM 셀렉터는 라이브 사이트 역공학 결과다. 임의 수정 금지.
# 네이버는 tfs 템플릿이 필요 없어 즉시 동작한다. 예약 딥링크는 없고 search_url만 제공(열면 실시간 재검색).

from __future__ import annotations

import json
import re
from html import unescape

ORIGIN = "ICN"
ORIGIN_NAVER = "SEL:city"
SOURCE = "naver"


def _build_naver_url(dep: str, arr: str, date_str: str) -> str:
    """편도 검색 URL 생성.

    dep/arr: IATA 공항 코드 (e.g. ICN, NRT).
    date_str: YYYY-MM-DD 형식.
    """
    date_compact = date_str.replace("-", "")
    # 출발지는 SEL:city, 도착지는 {code}:airport
    if dep == ORIGIN:
        dep_part = ORIGIN_NAVER
        arr_part = f"{arr}:airport"
    else:
        dep_part = f"{dep}:airport"
        arr_part = ORIGIN_NAVER
    return (
        f"https://flight.naver.com/flights/international/"
        f"{dep_part}-{arr_part}-{date_compact}"
        f"?adult=1&isDirect=false&fareType=Y&tripType=OW"
    )


def _extract_js() -> str:
    """DOM에서 항공편 카드 데이터를 추출해 #__nv__ div에 JSON으로 주입."""
    return """(function() {
    var results = [];
    var cards = document.querySelectorAll('div[class*="combination_ConcurrentItemContainer"]');

    for (var i = 0; i < cards.length; i++) {
        var card = cards[i];

        // 가격
        var priceEl = card.querySelector('i[class*="item_num"]');
        if (!priceEl) continue;
        var priceText = priceEl.textContent.trim().replace(/,/g, '');
        var price = parseInt(priceText);
        if (isNaN(price) || price < 20000 || price > 3000000) continue;

        // 항공사
        var airlineEl = card.querySelector('b[class*="airline_name"]');
        var airline = airlineEl ? airlineEl.textContent.trim() : '';

        // 출발/도착 시간 & 공항
        var times = card.querySelectorAll('b[class*="route_time"]');
        var codes = card.querySelectorAll('i[class*="route_code"]');
        var depTime = times.length > 0 ? times[0].textContent.trim() : null;
        var arrTime = times.length > 1 ? times[1].textContent.trim() : null;
        var depAirport = codes.length > 0 ? codes[0].textContent.trim() : null;
        var arrAirport = codes.length > 1 ? codes[1].textContent.trim() : null;

        // 비행정보: "직항, 02시간 10분" or "경유 1, 26시간 25분"
        var detailEl = card.querySelector('button[class*="route_details"]');
        var detailText = detailEl ? detailEl.textContent.trim() : '';
        var stops = 0;
        var durationMin = null;

        if (detailText.indexOf('직항') !== -1) {
            stops = 0;
        } else {
            var sm = detailText.match(/경유\\s*(\\d+)/);
            if (sm) stops = parseInt(sm[1]);
        }

        var dm = detailText.match(/(\\d+)시간(?:\\s*(\\d+)분)?/);
        if (dm) {
            durationMin = parseInt(dm[1]) * 60 + parseInt(dm[2] || 0);
        }

        results.push({
            price: price,
            airline: airline,
            dep_time: depTime,
            arr_time: arrTime,
            dep_airport: depAirport,
            arr_airport: arrAirport,
            stops: stops,
            duration_min: durationMin
        });
    }

    var el = document.getElementById('__nv__');
    if (!el) {
        el = document.createElement('div');
        el.id = '__nv__';
        el.style.display = 'none';
        document.body.appendChild(el);
    }
    el.textContent = JSON.stringify(results);
})();"""


def _parse_cards(raw_html: str) -> list[dict]:
    """JS가 주입한 #__nv__ div에서 항공편 데이터를 추출."""
    m = re.search(r'id="__nv__"[^>]*>(.*?)</div>', raw_html, re.DOTALL)
    if not m:
        return []
    try:
        return json.loads(unescape(m.group(1).strip()))
    except (json.JSONDecodeError, ValueError):
        return []
