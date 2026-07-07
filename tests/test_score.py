# tests/test_score.py
#
# score.py 순수 함수 검증 — 픽스처 offer dict만 사용, 네트워크/파일 I/O 없음 (AGENTS.md §6).

from __future__ import annotations

import pytest

from flight_picker.score import filter_offers, rank_offers, stay_minutes


def make_offer(**over: object) -> dict:
    """combine_roundtrips 출력 스키마를 따르는 최소 픽스처 offer."""
    base: dict = {
        "source": "naver",
        "trip_type": "oneway_combo",
        "origin": "ICN",
        "destination": "FUK",
        "destination_name": "후쿠오카",
        "departure_date": "2026-08-14",
        "return_date": "2026-08-17",
        "stay_nights": 3,
        "price": 300000,
        "out_airline": "대한항공",
        "in_airline": "대한항공",
        "is_mixed_airline": False,
        "out_dep_time": "08:00",
        "out_arr_time": "10:00",
        "out_stops": 0,
        "in_dep_time": "18:00",
        "in_arr_time": "20:30",
        "in_stops": 0,
        "out_url": "https://example.com/out",
        "in_url": "https://example.com/in",
    }
    base.update(over)
    return base


# ── stay_minutes ────────────────────────────────────────────────────────────

class TestStayMinutes:
    def test_basic(self):
        # 8/14 10:00 도착 → 8/17 18:00 출발 = 3일(4320분) + 8시간(480분)
        offer = make_offer()
        assert stay_minutes(offer) == 3 * 24 * 60 + 8 * 60

    def test_same_day_would_be_negative_days_zero(self):
        # 당일치기: 도착 10:00 → 출발 18:00 = 480분
        offer = make_offer(return_date="2026-08-14")
        assert stay_minutes(offer) == 480

    def test_missing_out_arr_time(self):
        assert stay_minutes(make_offer(out_arr_time=None)) is None

    def test_missing_in_dep_time(self):
        assert stay_minutes(make_offer(in_dep_time=None)) is None

    def test_unknown_time_placeholder(self):
        assert stay_minutes(make_offer(out_arr_time="??:??")) is None
        assert stay_minutes(make_offer(in_dep_time="??:??")) is None


# ── filter_offers ───────────────────────────────────────────────────────────

class TestFilterOffers:
    def test_no_filters_keeps_all(self):
        offers = [make_offer(), make_offer(price=100)]
        assert filter_offers(offers) == offers

    def test_out_dep_before(self):
        early = make_offer(out_dep_time="08:00")
        boundary = make_offer(out_dep_time="09:00")
        late = make_offer(out_dep_time="10:30")
        got = filter_offers([early, boundary, late], out_dep_before="09:00")
        assert got == [early, boundary]

    def test_out_dep_before_accepts_hour_only(self):
        early = make_offer(out_dep_time="08:59")
        late = make_offer(out_dep_time="09:01")
        got = filter_offers([early, late], out_dep_before="9")
        assert got == [early]

    def test_out_dep_before_drops_missing_time(self):
        missing = make_offer(out_dep_time=None)
        assert filter_offers([missing], out_dep_before="12:00") == []

    def test_in_dep_after(self):
        early = make_offer(in_dep_time="12:00")
        boundary = make_offer(in_dep_time="17:00")
        late = make_offer(in_dep_time="18:00")
        got = filter_offers([early, boundary, late], in_dep_after="17:00")
        assert got == [boundary, late]

    def test_in_dep_after_drops_missing_time(self):
        missing = make_offer(in_dep_time="??:??")
        assert filter_offers([missing], in_dep_after="10:00") == []

    def test_direct_only(self):
        direct = make_offer(out_stops=0, in_stops=0)
        out_stop = make_offer(out_stops=1, in_stops=0)
        in_stop = make_offer(out_stops=0, in_stops=2)
        got = filter_offers([direct, out_stop, in_stop], direct_only=True)
        assert got == [direct]

    def test_exclude_airlines_either_leg(self):
        keep = make_offer(out_airline="대한항공", in_airline="아시아나항공")
        out_bad = make_offer(out_airline="진에어", in_airline="대한항공")
        in_bad = make_offer(out_airline="대한항공", in_airline="진에어")
        got = filter_offers([keep, out_bad, in_bad], exclude_airlines=("진에어",))
        assert got == [keep]

    def test_filters_combine(self):
        ok = make_offer(out_dep_time="07:00", in_dep_time="19:00", out_stops=0, in_stops=0)
        bad = make_offer(out_dep_time="07:00", in_dep_time="19:00", out_stops=1, in_stops=0)
        got = filter_offers([ok, bad], out_dep_before="08:00", in_dep_after="18:00", direct_only=True)
        assert got == [ok]


# ── rank_offers ─────────────────────────────────────────────────────────────

class TestRankOffers:
    def test_price_mode_sorts_ascending(self):
        a = make_offer(price=300000)
        b = make_offer(price=150000)
        c = make_offer(price=220000)
        got = rank_offers([a, b, c], priority="price")
        assert [o["price"] for o in got] == [150000, 220000, 300000]
        assert [o["rank"] for o in got] == [1, 2, 3]

    def test_stay_mode_sorts_descending_tie_price(self):
        long_stay = make_offer(return_date="2026-08-18", price=400000)   # 4박
        short_a = make_offer(return_date="2026-08-17", price=200000)     # 3박, 저렴
        short_b = make_offer(return_date="2026-08-17", price=350000)     # 3박, 비쌈
        got = rank_offers([short_b, long_stay, short_a], priority="stay")
        assert got[0] is long_stay
        assert got[1] is short_a
        assert got[2] is short_b

    def test_stay_mode_missing_stay_goes_last(self):
        known = make_offer()
        unknown = make_offer(in_dep_time=None, price=1)
        got = rank_offers([unknown, known], priority="stay")
        assert got[0] is known
        assert got[1] is unknown

    def test_balance_dominant_offer_wins(self):
        # best: 최저가 + 최장 체류 + 가장 이른 출발 → 가중치와 무관하게 1위
        best = make_offer(price=200000, return_date="2026-08-19", out_dep_time="07:00")
        worst = make_offer(price=500000, return_date="2026-08-15", out_dep_time="15:00")
        mid = make_offer(price=350000, return_date="2026-08-17", out_dep_time="10:00")
        got = rank_offers([mid, worst, best], priority="balance")
        assert got[0] is best
        assert got[-1] is worst
        assert got[0]["rank"] == 1

    def test_balance_degenerate_range_no_crash(self):
        # 후보가 1개거나 모든 값이 동일해도 (min==max) 정상 동작
        one = rank_offers([make_offer()], priority="balance")
        assert one[0]["rank"] == 1
        same = rank_offers([make_offer(), make_offer()], priority="balance")
        assert [o["rank"] for o in same] == [1, 2]

    def test_annotations_attached(self):
        got = rank_offers([make_offer()], priority="balance")
        o = got[0]
        assert o["stay_minutes"] == 3 * 24 * 60 + 8 * 60
        assert isinstance(o["score"], float)
        assert o["rank"] == 1

    def test_invalid_priority_raises(self):
        with pytest.raises(ValueError):
            rank_offers([make_offer()], priority="cheapest")

    def test_empty_input(self):
        assert rank_offers([], priority="price") == []
