import asyncio

import pytest

from webuse import Response, acrawl, crawl
from webuse.engine.async_state import AsyncMemoryRequestQueue, AsyncMemoryRequestSeen
from webuse.engine.state import (
    DefaultRequestHasher,
    MemoryRequestQueue,
    MemoryRequestSeen,
)
from webuse.models import CrawlRequest


@pytest.fixture(params=[False, True], ids=["sync", "async"])
def runtime(request):
    queued = []

    class Queue(MemoryRequestQueue):
        def put(self, item):
            queued.append(item.url)
            super().put(item)

    class AsyncQueue(AsyncMemoryRequestQueue):
        async def put(self, item):
            queued.append(item.url)
            await super().put(item)

    class Client:
        def request(self, method, url, **options):
            return Response(url=url, content=b"<h1>Page</h1>")

    class AsyncClient(Client):
        async def request(self, method, url, **options):
            await asyncio.sleep(0)
            return super().request(method, url, **options)

    def execute(seeds, *, stored=(), seen_urls=(), **options):
        hashes = [
            DefaultRequestHasher().hash(CrawlRequest(url=url)) for url in seen_urls
        ]
        if request.param:
            queue = AsyncQueue(list(stored))
            seen = AsyncMemoryRequestSeen(hashes)
            return asyncio.run(
                acrawl(
                    seeds,
                    request_queue=queue,
                    request_seen=seen,
                    client=AsyncClient(),
                    **options,
                )
            )
        queue = Queue(list(stored))
        queued.clear()  # Only observe admissions during this run.
        return crawl(
            seeds,
            request_queue=queue,
            request_seen=MemoryRequestSeen(hashes),
            client=Client(),
            **options,
        )

    return execute, queued


def test_seen_seeds_and_rediscovered_urls_never_enter_queue(runtime):
    run, queued = runtime

    def parse(response):
        yield response.follow("/#again")
        yield response.follow("/old#again")

    result = run(
        ["https://test/old", "https://test/#start"],
        seen_urls=["https://test/old"],
        extract=parse,
        max_depth=1,
    )
    assert queued == ["https://test/"]
    assert result.visited == {"https://test/"}
    assert result.stats.skipped_duplicates == 3
    assert result.stats.followed_links == 0


@pytest.mark.parametrize("concurrency", [1, 4])
def test_duplicates_queued_before_first_download_are_checked_on_dequeue(
    runtime, concurrency
):
    run, queued = runtime
    result = run(
        ["https://test/#one", "https://test/#two"],
        concurrency=concurrency,
    )
    assert queued == ["https://test/", "https://test/"]
    assert result.stats.fetched == 1
    assert result.stats.skipped_duplicates == 1


def test_stored_queue_checks_patterns_and_seen_before_downloading(runtime):
    run, queued = runtime
    result = run(
        [],
        stored=[
            CrawlRequest(url="https://test/ads", page_type="detail"),
            CrawlRequest(url="https://test/outside", page_type="detail"),
            CrawlRequest(url="https://test/products/old"),
            CrawlRequest(url="https://test/products/new"),
            CrawlRequest(url="https://test/products/new#again"),
        ],
        seen_urls=["https://test/products/old"],
        pages={
            "detail": {
                "url_patterns": ["/products/", "/ads"],
                "exclude_patterns": ["/ads"],
            }
        },
    )
    assert queued == []
    assert result.visited == {"https://test/products/new"}
    assert result.pages[0].crawl_request.page_type == "detail"
    assert result.stats.skipped_rules == 2
    assert result.stats.skipped_duplicates == 2


def test_rejected_type_does_not_mark_url_as_seen(runtime):
    run, queued = runtime
    result = run(
        [
            CrawlRequest(url="https://test/products/1", page_type="wrong"),
            "https://test/products/1",
        ],
        pages={
            "wrong": {"url_patterns": ["/books/"]},
            "detail": {"url_patterns": ["/products/"]},
        },
    )
    assert queued == ["https://test/products/1"]
    assert result.pages[0].crawl_request.page_type == "detail"
    assert result.stats.skipped_rules == 1
    assert result.stats.skipped_duplicates == 0


def test_dedupe_false_bypasses_both_queue_checks(runtime):
    run, queued = runtime
    result = run(
        ["https://test/", "https://test/#again"],
        seen_urls=["https://test/"],
        dedupe=False,
    )
    assert queued == ["https://test/", "https://test/"]
    assert result.stats.fetched == 2
    assert result.stats.skipped_duplicates == 0
