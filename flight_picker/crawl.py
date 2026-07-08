# flight_picker/crawl.py
#
# 라이브 단일 노선+날짜 크롤 오케스트레이션 (AGENTS.md §2 Crawl 레이어).
# AsyncWebCrawler 수명주기 관리 → 소스별 URL 조립 → 배치 크롤 → enrich → combine → 소스 병합.
# crawl4ai 런타임 import는 이 모듈 전용.

from __future__ import annotations

import asyncio
import json
from datetime import date
from pathlib import Path
from typing import Callable

from crawl4ai import AsyncWebCrawler, BrowserConfig, CacheMode, CrawlerRunConfig

from . import combine, constants, crawl_utils, gflights, naver
from .constants import ORIGIN, SEARCH_CONFIG

DEFAULT_SOURCES: tuple[str, ...] = ("google", "naver")

_TEMPLATES_PATH = Path(__file__).resolve().parent / "templates.json"

# 소스 원본 crawl4ai 설정 (PROJECT_PLAN.md Part B — 셀렉터와 한 몸, 임의 변경 금지)
_GF_WAIT_FOR = "js:() => !!document.querySelector('li.pIav2d')"
_GF_DELAY_BEFORE_RETURN = 4.0
_NAVER_WAIT_FOR = 'css:div[class*="combination_ConcurrentItemContainer"]'
_NAVER_DELAY_BEFORE_RETURN = 8.0


def _load_templates() -> None:
    """templates.json이 있으면 구글 tfs 템플릿을 TFS_TEMPLATES에 패치."""
    if not _TEMPLATES_PATH.exists():
        return
    try:
        constants.TFS_TEMPLATES.update(json.loads(_TEMPLATES_PATH.read_text(encoding="utf-8")))
    except (OSError, ValueError) as e:
        print(f"[GoogleFlights WARN] templates.json 로드 실패: {e}")


def _browser_config() -> BrowserConfig:
    return BrowserConfig(
        headless=True,
        viewport_width=1920,
        viewport_height=1080,
        extra_args=[
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
        ],
    )


def _google_run_config() -> CrawlerRunConfig:
    return CrawlerRunConfig(
        magic=True,
        js_code=[crawl_utils.make_scroll_js(), gflights._extract_js()],
        wait_for=_GF_WAIT_FOR,
        delay_before_return_html=_GF_DELAY_BEFORE_RETURN,
        cache_mode=CacheMode.BYPASS,
        page_timeout=SEARCH_CONFIG["gf_page_timeout_ms"],
    )


def _naver_run_config() -> CrawlerRunConfig:
    return CrawlerRunConfig(
        js_code=[crawl_utils.make_scroll_js(), naver._extract_js()],
        wait_for=_NAVER_WAIT_FOR,
        delay_before_return_html=_NAVER_DELAY_BEFORE_RETURN,
        cache_mode=CacheMode.BYPASS,
        page_timeout=SEARCH_CONFIG["page_timeout_ms"],
    )


async def _crawl_source(
    crawler: AsyncWebCrawler,
    source: str,
    dest: str,
    dest_name: str,
    dep_date: str,
    ret_date: str,
    stay: int,
) -> list[dict]:
    """한 소스의 out+in 편도 2회 크롤 → enrich → 왕복 offer 조합."""
    parse_cards: Callable[[str], list[dict]]
    if source == "google":
        out_url = gflights._build_tfs_url(ORIGIN, dest, dep_date)
        in_url = gflights._build_tfs_url(dest, ORIGIN, ret_date)
        if not out_url or not in_url:
            print(f"[GoogleFlights WARN] tfs 템플릿 없음({ORIGIN}_{dest}) — 구글 스킵 (templates.json 참고)")
            return []
        run_config = _google_run_config()
        parse_cards = gflights._parse_flight_cards
        label = "GoogleFlights"
    elif source == "naver":
        out_url = naver._build_naver_url(ORIGIN, dest, dep_date)
        in_url = naver._build_naver_url(dest, ORIGIN, ret_date)
        run_config = _naver_run_config()
        parse_cards = naver._parse_cards
        label = "Naver"
    else:
        print(f"[{source} WARN] 알 수 없는 소스 — 스킵")
        return []

    urls = [out_url, in_url]
    metas = [
        {"dep": ORIGIN, "arr": dest, "date": dep_date, "direction": "out", "url": out_url},
        {"dep": dest, "arr": ORIGIN, "date": ret_date, "direction": "in", "url": in_url},
    ]

    results = await crawl_utils.crawl_one_way_batches(
        crawler, urls, metas, run_config,
        source_label=label,
        parse_cards=parse_cards,
        request_delay=SEARCH_CONFIG["request_delay"],
        batch_size=2,
    )

    out_flights: list[dict] = []
    in_flights: list[dict] = []
    for meta, flights in results:
        for flight in flights:
            flight["date"] = meta["date"]
            flight["search_url"] = meta["url"]
            if source == "google":
                flight["booking_url"] = gflights._build_booking_url(
                    flight, meta["dep"], meta["arr"], meta["date"])
            (out_flights if meta["direction"] == "out" else in_flights).append(flight)

    return combine.combine_roundtrips(
        out_flights, in_flights,
        source=source,
        origin=ORIGIN,
        destination=dest,
        destination_name=dest_name,
        stay_durations=[stay],
        topk=SEARCH_CONFIG["topk_per_date"],
    )


async def crawl_offers(
    dest: str,
    dest_name: str,
    dep_date: str,
    ret_date: str,
    sources: tuple[str, ...] = DEFAULT_SOURCES,
) -> list[dict]:
    """ICN↔dest 왕복(dep_date/ret_date)을 소스별 라이브 크롤해 offer 리스트로 반환.

    한 소스가 실패해도 로깅 후 나머지 소스 결과는 유지한다.
    """
    _load_templates()
    stay = (date.fromisoformat(ret_date) - date.fromisoformat(dep_date)).days

    offers: list[dict] = []
    async with AsyncWebCrawler(config=_browser_config()) as crawler:
        for source in sources:
            try:
                offers.extend(await _crawl_source(
                    crawler, source, dest, dest_name, dep_date, ret_date, stay))
            except Exception as e:
                print(f"[{source} ERROR] 소스 크롤 실패: {e}")
    return offers


def crawl_offers_sync(
    dest: str,
    dest_name: str,
    dep_date: str,
    ret_date: str,
    sources: tuple[str, ...] = DEFAULT_SOURCES,
) -> list[dict]:
    """crawl_offers 동기 래퍼 (asyncio.run 진입점)."""
    return asyncio.run(crawl_offers(dest, dest_name, dep_date, ret_date, sources))
