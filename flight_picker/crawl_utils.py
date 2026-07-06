# flight_picker/crawl_utils.py
#
# my-flight-friend/flight_monitor/crawler_utils.py 에서 포팅.
# 배치 크롤(arun_many)·무한 스크롤 JS 만 유지 (sweep window 로직은 배치 모니터링용이라 제거).
# crawl4ai 타입은 TYPE_CHECKING 하에서만 참조 — crawl4ai 미설치 환경에서도 import 가능.

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from crawl4ai import AsyncWebCrawler, CrawlerRunConfig


def make_scroll_js() -> str:
    return """
(async () => {
    const sleep = ms => new Promise(r => setTimeout(r, ms));
    let prev = 0;
    for (let i = 0; i < 5; i++) {
        window.scrollTo(0, document.body.scrollHeight);
        await sleep(1500);
        const curr = document.body.scrollHeight;
        if (curr === prev) break;
        prev = curr;
    }
})();
"""


async def crawl_one_way_batches(
    crawler: "AsyncWebCrawler",
    urls: list[str],
    metas: list[dict],
    run_config: "CrawlerRunConfig",
    *,
    source_label: str,
    parse_cards: Callable[[str], list[dict]],
    request_delay: float,
    batch_size: int = 5,
) -> list[tuple[dict, list[dict]]]:
    """URL 목록을 batch_size 단위로 arun_many() 크롤링.

    개별 실패는 로깅 후 계속 진행한다 (raise 금지).
    반환: 성공한 URL별 (meta, 가격 오름차순 정렬된 flights) 튜플 리스트.
    topk 절단·소스별 enrichment는 호출측 책임.
    """
    collected: list[tuple[dict, list[dict]]] = []

    for i in range(0, len(urls), batch_size):
        batch_urls = urls[i:i + batch_size]
        batch_metas = metas[i:i + batch_size]
        url_to_meta = {u: m for u, m in zip(batch_urls, batch_metas)}

        try:
            results = await crawler.arun_many(urls=batch_urls, config=run_config)
        except Exception as e:
            print(f"[{source_label} ERROR] batch {i // batch_size}: {e}")
            continue

        for result in results:
            meta = url_to_meta.get(result.url)
            if meta is None:
                print(f"[{source_label} WARN] 매칭 메타 없음: {result.url[:80]}")
                continue
            if not result.success:
                print(f"[{source_label} FAIL] {meta['dep']}-{meta['arr']} {meta['date']}: {result.error_message}")
                continue

            flights = parse_cards(result.html or "")
            if not flights:
                print(f"[{source_label} WARN] 카드 추출 0건 {meta['dep']}-{meta['arr']} {meta['date']}")
                continue

            flights.sort(key=lambda x: x["price"])
            collected.append((meta, flights))

        if i + batch_size < len(urls):
            await asyncio.sleep(request_delay)

    return collected
