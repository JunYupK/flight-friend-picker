# tests/test_crawl.py
#
# crawl.crawl_offers 오케스트레이션 검증 — crawl_one_way_batches를 monkeypatch로
# 픽스처 (meta, flights) 반환하게 대체. 실제 crawl4ai/브라우저/HTTP 호출 없음 (AGENTS.md §6).

from __future__ import annotations

import asyncio
import base64
from typing import Callable

import pytest

from flight_picker import constants, crawl, crawl_utils, gflights, naver


class FakeCrawler:
    """AsyncWebCrawler 대체 — 브라우저를 띄우지 않는 no-op 컨텍스트."""

    def __init__(self, config: object = None) -> None:
        self.config = config

    async def __aenter__(self) -> "FakeCrawler":
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False


NAVER_OUT = {
    "price": 100000, "airline": "티웨이항공", "dep_time": "08:00", "arr_time": "09:30",
    "stops": 0, "duration_min": 90, "dep_airport": "ICN", "arr_airport": "FUK",
}
NAVER_IN = {
    "price": 120000, "airline": "제주항공", "dep_time": "18:00", "arr_time": "19:30",
    "stops": 0, "duration_min": 90, "dep_airport": "FUK", "arr_airport": "ICN",
}
GOOGLE_OUT = {
    "price": 150000, "airline": "대한항공", "dep_time": "09:00", "arr_time": "10:30",
    "stops": 0, "duration_min": 90, "dep_airport": "ICN", "arr_airport": "FUK",
    "flight_numbers": ["KE 787"], "segment_airports": ["ICN", "FUK"],
    "segment_dates": ["2026-08-14"],
}
GOOGLE_IN = {
    "price": 130000, "airline": "대한항공", "dep_time": "17:00", "arr_time": "18:30",
    "stops": 0, "duration_min": 90, "dep_airport": "FUK", "arr_airport": "ICN",
    "flight_numbers": ["KE 788"], "segment_airports": ["FUK", "ICN"],
    "segment_dates": ["2026-08-17"],
}


def make_fake_batches(
    calls: list[dict],
    flights_for: Callable[[dict, str], list[dict]],
) -> Callable:
    """meta.direction별 픽스처 flights를 돌려주는 crawl_one_way_batches 대체."""

    async def fake(
        crawler: object, urls: list[str], metas: list[dict], run_config: object, *,
        source_label: str, parse_cards: Callable[[str], list[dict]],
        request_delay: float, batch_size: int,
    ) -> list[tuple[dict, list[dict]]]:
        calls.append({
            "urls": urls, "metas": metas, "run_config": run_config,
            "source_label": source_label, "parse_cards": parse_cards,
            "request_delay": request_delay, "batch_size": batch_size,
        })
        return [(meta, [dict(f) for f in flights_for(meta, source_label)]) for meta in metas]

    return fake


@pytest.fixture()
def no_browser(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(crawl, "AsyncWebCrawler", FakeCrawler)


@pytest.fixture()
def google_templates(monkeypatch: pytest.MonkeyPatch) -> None:
    tmpl = base64.urlsafe_b64encode(b"route:2026-01-01:tail").rstrip(b"=").decode()
    monkeypatch.setitem(constants.TFS_TEMPLATES, "ICN_FUK", tmpl)
    monkeypatch.setitem(constants.TFS_TEMPLATES, "FUK_ICN", tmpl)


def naver_fixture(meta: dict, source_label: str) -> list[dict]:
    return [NAVER_OUT] if meta["direction"] == "out" else [NAVER_IN]


def google_fixture(meta: dict, source_label: str) -> list[dict]:
    return [GOOGLE_OUT] if meta["direction"] == "out" else [GOOGLE_IN]


class TestNaverSource:
    def test_offers_built_from_fixture_flights(self, no_browser, monkeypatch):
        calls: list[dict] = []
        monkeypatch.setattr(crawl_utils, "crawl_one_way_batches", make_fake_batches(calls, naver_fixture))

        offers = asyncio.run(crawl.crawl_offers(
            "FUK", "후쿠오카", "2026-08-14", "2026-08-17", sources=("naver",)))

        assert len(offers) == 1
        o = offers[0]
        assert o["source"] == "naver"
        assert o["price"] == 220000
        assert o["departure_date"] == "2026-08-14"
        assert o["return_date"] == "2026-08-17"
        assert o["stay_nights"] == 3
        assert o["out_airline"] == "티웨이항공"
        assert o["in_airline"] == "제주항공"
        assert o["is_mixed_airline"] is True
        # 네이버는 booking 딥링크 없음 → search_url이 out_url/in_url
        assert o["out_url"] == naver._build_naver_url("ICN", "FUK", "2026-08-14")
        assert o["in_url"] == naver._build_naver_url("FUK", "ICN", "2026-08-17")

    def test_batch_call_contract(self, no_browser, monkeypatch):
        calls: list[dict] = []
        monkeypatch.setattr(crawl_utils, "crawl_one_way_batches", make_fake_batches(calls, naver_fixture))

        asyncio.run(crawl.crawl_offers("FUK", "후쿠오카", "2026-08-14", "2026-08-17", sources=("naver",)))

        assert len(calls) == 1
        call = calls[0]
        assert call["batch_size"] == 2
        assert call["parse_cards"] is naver._parse_cards
        assert call["request_delay"] == constants.SEARCH_CONFIG["request_delay"]
        # out(ICN→FUK, 출발일) + in(FUK→ICN, 귀국일) URL 정확히 2개
        assert call["urls"] == [
            naver._build_naver_url("ICN", "FUK", "2026-08-14"),
            naver._build_naver_url("FUK", "ICN", "2026-08-17"),
        ]
        assert [m["direction"] for m in call["metas"]] == ["out", "in"]
        assert call["metas"][0]["date"] == "2026-08-14"
        assert call["metas"][1]["date"] == "2026-08-17"


class TestGoogleSource:
    def test_offers_get_booking_deeplink(self, no_browser, monkeypatch, google_templates):
        calls: list[dict] = []
        monkeypatch.setattr(crawl_utils, "crawl_one_way_batches", make_fake_batches(calls, google_fixture))

        offers = asyncio.run(crawl.crawl_offers(
            "FUK", "후쿠오카", "2026-08-14", "2026-08-17", sources=("google",)))

        assert len(offers) == 1
        o = offers[0]
        assert o["source"] == "google"
        assert o["price"] == 280000
        # 편명이 있으므로 booking 딥링크가 out_url/in_url
        assert o["out_url"].startswith("https://www.google.com/travel/flights/booking?tfs=")
        assert o["in_url"].startswith("https://www.google.com/travel/flights/booking?tfs=")
        # 검색 URL은 tfs 템플릿의 날짜가 대상 날짜로 치환된 것
        assert calls[0]["urls"] == [
            gflights._build_tfs_url("ICN", "FUK", "2026-08-14"),
            gflights._build_tfs_url("FUK", "ICN", "2026-08-17"),
        ]
        assert calls[0]["parse_cards"] is gflights._parse_flight_cards

    def test_skipped_without_template(self, no_browser, monkeypatch):
        calls: list[dict] = []
        monkeypatch.setattr(crawl_utils, "crawl_one_way_batches", make_fake_batches(calls, google_fixture))

        offers = asyncio.run(crawl.crawl_offers(
            "FUK", "후쿠오카", "2026-08-14", "2026-08-17", sources=("google",)))

        assert offers == []
        assert calls == []  # 템플릿 없으면 크롤 자체를 하지 않는다


class TestSourceMerging:
    def test_both_sources_merged(self, no_browser, monkeypatch, google_templates):
        calls: list[dict] = []

        def fixture(meta: dict, source_label: str) -> list[dict]:
            if source_label == "GoogleFlights":
                return google_fixture(meta, source_label)
            return naver_fixture(meta, source_label)

        monkeypatch.setattr(crawl_utils, "crawl_one_way_batches", make_fake_batches(calls, fixture))

        offers = asyncio.run(crawl.crawl_offers(
            "FUK", "후쿠오카", "2026-08-14", "2026-08-17", sources=("google", "naver")))

        assert sorted(o["source"] for o in offers) == ["google", "naver"]

    def test_one_source_failure_keeps_other(self, no_browser, monkeypatch, google_templates):
        calls: list[dict] = []
        fake = make_fake_batches(calls, naver_fixture)

        async def flaky(*args: object, **kwargs: object) -> list[tuple[dict, list[dict]]]:
            if kwargs["source_label"] == "GoogleFlights":
                raise RuntimeError("boom")
            return await fake(*args, **kwargs)

        monkeypatch.setattr(crawl_utils, "crawl_one_way_batches", flaky)

        offers = asyncio.run(crawl.crawl_offers(
            "FUK", "후쿠오카", "2026-08-14", "2026-08-17", sources=("google", "naver")))

        assert len(offers) == 1
        assert offers[0]["source"] == "naver"


class TestSyncWrapper:
    def test_crawl_offers_sync(self, no_browser, monkeypatch):
        calls: list[dict] = []
        monkeypatch.setattr(crawl_utils, "crawl_one_way_batches", make_fake_batches(calls, naver_fixture))

        offers = crawl.crawl_offers_sync(
            "FUK", "후쿠오카", "2026-08-14", "2026-08-17", sources=("naver",))

        assert len(offers) == 1
        assert offers[0]["price"] == 220000
