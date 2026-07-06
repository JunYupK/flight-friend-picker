# flight_picker/gflights.py
#
# my-flight-friend/flight_monitor/collector_google_flights.py 에서 헬퍼만 발췌 포팅.
# 유지: tfs 검색 URL / 예약 딥링크(protobuf) / extract JS / 카드 파서.
# 제거: _fetch_route/_fetch_airport/_fetch_all (save_legs·get_collected_today = DB 의존).
#
# ⚠️ tfs protobuf 인코딩과 DOM 셀렉터는 라이브 사이트 역공학 결과다. 임의 수정 금지.

from __future__ import annotations

import base64
import json
import re
from html import unescape

from .constants import TFS_TEMPLATES

_TFS_DATE_RE = re.compile(rb"\d{4}-\d{2}-\d{2}")


def _pb_varint(value: int) -> bytes:
    """Protobuf varint 인코딩."""
    result = b""
    while value > 0x7F:
        result += bytes([0x80 | (value & 0x7F)])
        value >>= 7
    result += bytes([value])
    return result


def _pb_field(field_num: int, wire_type: int, data: int | bytes) -> bytes:
    """Protobuf 필드 인코딩. wire_type 0=varint, 2=length-delimited."""
    tag = _pb_varint((field_num << 3) | wire_type)
    if wire_type == 0:
        return tag + _pb_varint(data)
    return tag + _pb_varint(len(data)) + data


def _pb_string(field_num: int, s: str) -> bytes:
    return _pb_field(field_num, 2, s.encode())


def _build_booking_tfs(
    date_str: str,
    segments: list[dict],
    origin: str,
    destination: str,
) -> str:
    """편명 정보로 Google Flights booking tfs 파라미터 생성.

    segments: [{"dep": "ICN", "arr": "NKG", "date": "2026-04-01",
                "airline": "MU", "flight_num": "580"}, ...]
    """
    itin = _pb_string(2, date_str)
    for seg in segments:
        seg_bytes = (
            _pb_string(1, seg["dep"])
            + _pb_string(2, seg["date"])
            + _pb_string(3, seg["arr"])
            + _pb_string(5, seg["airline"])
            + _pb_string(6, seg["flight_num"])
        )
        itin += _pb_field(4, 2, seg_bytes)
    # origin / destination wrappers (field 13, 14)
    itin += _pb_field(13, 2, _pb_field(1, 0, 1) + _pb_string(2, origin))
    itin += _pb_field(14, 2, _pb_field(1, 0, 1) + _pb_string(2, destination))

    outer = (
        _pb_field(1, 0, 28)
        + _pb_field(2, 0, 2)
        + _pb_field(3, 2, itin)
        + _pb_field(8, 0, 1)
        + _pb_field(9, 0, 1)
        + _pb_field(14, 0, 1)
        + _pb_field(16, 2, b"\x08" + b"\xff" * 9 + b"\x01")
        + _pb_field(19, 0, 2)
    )
    tfs = base64.urlsafe_b64encode(outer).rstrip(b"=").decode()
    return f"https://www.google.com/travel/flights/booking?tfs={tfs}&curr=KRW&hl=ko"


def _build_booking_url(
    flight: dict, dep: str, arr: str, date_str: str,
) -> str | None:
    """편명이 있으면 booking URL 생성, 없으면 None."""
    flight_numbers = flight.get("flight_numbers")
    if not flight_numbers:
        return None

    seg_dates = flight.get("segment_dates") or []
    airports = flight.get("segment_airports") or []

    segments = []
    for i, fn_str in enumerate(flight_numbers):
        m = re.match(r"([A-Z0-9]{2})\s*(\d+)", fn_str)
        if not m:
            return None
        seg_date = seg_dates[i] if i < len(seg_dates) and seg_dates[i] else date_str
        segments.append({
            "dep": "", "arr": "", "date": seg_date,
            "airline": m.group(1), "flight_num": m.group(2),
        })

    if len(segments) == 1:
        segments[0]["dep"] = dep
        segments[0]["arr"] = arr
    elif airports and len(airports) == len(segments) + 1:
        for i, seg in enumerate(segments):
            seg["dep"] = airports[i]
            seg["arr"] = airports[i + 1]
    else:
        return None

    return _build_booking_tfs(date_str, segments, dep, arr)


def _build_tfs_url(dep: str, arr: str, date_str: str) -> str | None:
    """노선+날짜 조합의 Google Flights 검색 URL 반환. 템플릿 없으면 None.
    tfs 값은 base64 문자열 또는 전체 URL 모두 허용."""
    template = TFS_TEMPLATES.get(f"{dep}_{arr}")
    if not template:
        return None
    # 전체 URL이 입력된 경우 tfs= 파라미터만 추출
    if template.startswith("http"):
        from urllib.parse import urlparse, parse_qs
        qs = parse_qs(urlparse(template).query)
        tfs_list = qs.get("tfs")
        if not tfs_list:
            return None
        template = tfs_list[0]
    raw = base64.urlsafe_b64decode(template + "==")
    # 템플릿 내 첫 번째 YYYY-MM-DD 패턴을 찾아 target 날짜로 교체
    m = _TFS_DATE_RE.search(raw)
    if m:
        raw = raw[:m.start()] + date_str.encode() + raw[m.end():]
    else:
        print(f"[GoogleFlights WARN] tfs 템플릿에 날짜 패턴 없음: {dep}_{arr}")
    tfs = base64.urlsafe_b64encode(raw).rstrip(b"=").decode()
    return f"https://www.google.com/travel/flights/search?tfs={tfs}&curr=KRW&hl=ko"


def _extract_js() -> str:
    """
    li.pIav2d 카드 셀렉터 기반으로 항공편 데이터를 추출해
    #__fl__ div에 JSON으로 주입한다.
    편명은 data-travelimpactmodelwebsiteurl의 itinerary 파라미터에서 추출.
    """
    return """(function() {
    function toHHMM(text) {
        if (!text) return null;
        var m = text.match(/(오전|오후)\\s*(\\d+):(\\d+)/);
        if (!m) return text.trim();
        var h = parseInt(m[2]);
        if (m[1] === '오후' && h !== 12) h += 12;
        if (m[1] === '오전' && h === 12) h = 0;
        return String(h).padStart(2, '0') + ':' + m[3];
    }

    // data-travelimpactmodelwebsiteurl에서 itinerary 파싱
    // 직항: itinerary=ICN-NRT-YP-735-20260501
    // 경유: itinerary=ICN-TNA-SC-8004-20260501,TNA-CKG-SC-8803-20260502
    function extractItinerary(card) {
        var el = card.querySelector('[data-travelimpactmodelwebsiteurl]');
        if (!el) return { flight_numbers: [], segment_airports: [], segment_dates: [] };
        var url = el.getAttribute('data-travelimpactmodelwebsiteurl') || '';
        var m = url.match(/itinerary=([^&]+)/);
        if (!m) return { flight_numbers: [], segment_airports: [], segment_dates: [] };

        var segments = m[1].split(',');
        var fns = [];
        var airports = [];
        var dates = [];
        for (var i = 0; i < segments.length; i++) {
            var parts = segments[i].split('-');
            // parts: [DEP, ARR, AIRLINE, FNUM, YYYYMMDD]
            if (parts.length < 5) continue;
            if (i === 0) airports.push(parts[0]);
            airports.push(parts[1]);
            fns.push(parts[2] + ' ' + parts[3]);
            // YYYYMMDD → YYYY-MM-DD
            var d = parts[4];
            if (d.length === 8) {
                dates.push(d.substring(0, 4) + '-' + d.substring(4, 6) + '-' + d.substring(6, 8));
            } else {
                dates.push('');
            }
        }
        return { flight_numbers: fns, segment_airports: airports, segment_dates: dates };
    }

    var results = [];
    var cards = Array.from(document.querySelectorAll('li.pIav2d'));

    for (var i = 0; i < cards.length; i++) {
        var card = cards[i];

        // 가격: aria-label="250436 대한민국 원"
        var priceEl = card.querySelector('.YMlIz.FpEdX.jLMuyc > span[aria-label]')
                   || card.querySelector('.YMlIz.FpEdX span[aria-label]');
        if (!priceEl) continue;
        var priceLabel = priceEl.getAttribute('aria-label') || '';
        var priceM = priceLabel.match(/^([\\d,]+)/);
        if (!priceM) continue;
        var price = parseInt(priceM[1].replace(/,/g, ''));
        if (price < 20000 || price > 3000000) continue;

        // 출발/도착 시간
        var depEl = card.querySelector('.wtdjmc.YMlIz');
        var arrEl = card.querySelector('.XWcVob.YMlIz');

        // 직항 여부 / 경유 횟수
        var stopsEl = card.querySelector('.VG3hNb');
        var stopsText = stopsEl ? stopsEl.textContent.trim() : '';
        if (!stopsText) {
            // fallback: 카드 내 텍스트에서 "직항" / "경유 N회" 패턴 검색
            var tw = document.createTreeWalker(card, NodeFilter.SHOW_TEXT);
            while (tw.nextNode()) {
                var txt = tw.currentNode.textContent.trim();
                if (txt === '직항') { stopsText = '직항'; break; }
                var sm = txt.match(/경유\\s*(\\d+)회/);
                if (sm) { stopsText = sm[1]; break; }
            }
        }
        var stops = stopsText === '직항' ? 0 : (parseInt(stopsText) || null);

        // 비행시간 (aria-label: "총 비행 시간은 2시간 20분입니다.")
        var durEl = card.querySelector('.gvkrdb');
        var durText = durEl ? (durEl.getAttribute('aria-label') || durEl.textContent || '') : '';
        var durM = durText.match(/(\\d+)시간(?:\\s*(\\d+)분)?/);
        var duration_min = durM ? parseInt(durM[1]) * 60 + parseInt(durM[2] || 0) : null;

        // 항공사
        var airlineEl = card.querySelector('.h1fkLb span');
        var airline = airlineEl ? airlineEl.textContent.trim() : '';

        // 공항 코드 — IATA 3자리 대문자. .iCvNQ 또는 fallback으로 전체 텍스트 노드 스캔
        var depAirport = null, arrAirport = null;
        var airportEls = card.querySelectorAll('.iCvNQ');
        if (airportEls.length >= 2) {
            depAirport = airportEls[0].textContent.trim();
            arrAirport = airportEls[airportEls.length - 1].textContent.trim();
        } else {
            // fallback: 카드 내 모든 텍스트 노드에서 IATA 패턴 검색
            var walker = document.createTreeWalker(card, NodeFilter.SHOW_TEXT);
            var codes = [];
            while (walker.nextNode()) {
                var t = walker.currentNode.textContent.trim();
                if (/^[A-Z]{3}$/.test(t) && codes.indexOf(t) === -1) codes.push(t);
            }
            if (codes.length >= 2) { depAirport = codes[0]; arrAirport = codes[1]; }
        }

        // itinerary에서 편명 + 공항 + 날짜 추출
        var itin = extractItinerary(card);

        // dep/arr 공항: DOM 셀렉터 실패 시 itinerary에서 보완
        if (!depAirport && itin.segment_airports.length >= 2) {
            depAirport = itin.segment_airports[0];
        }
        if (!arrAirport && itin.segment_airports.length >= 2) {
            arrAirport = itin.segment_airports[itin.segment_airports.length - 1];
        }

        results.push({
            price: price,
            dep_time: toHHMM(depEl ? depEl.textContent : null),
            arr_time: toHHMM(arrEl ? arrEl.textContent : null),
            stops: stops,
            duration_min: duration_min,
            airline: airline,
            dep_airport: depAirport,
            arr_airport: arrAirport,
            flight_numbers: itin.flight_numbers,
            segment_airports: itin.segment_airports,
            segment_dates: itin.segment_dates
        });
    }

    var el = document.getElementById('__fl__');
    if (!el) {
        el = document.createElement('div');
        el.id = '__fl__';
        el.style.display = 'none';
        document.body.appendChild(el);
    }
    el.textContent = JSON.stringify(results);
})();"""


def _parse_flight_cards(raw_html: str) -> list[dict]:
    """JS가 주입한 #__fl__ div에서 구조화된 항공편 데이터를 추출."""
    m = re.search(r'id="__fl__"[^>]*>(.*?)</div>', raw_html, re.DOTALL)
    if not m:
        return []
    try:
        return json.loads(unescape(m.group(1).strip()))
    except (json.JSONDecodeError, ValueError):
        return []
