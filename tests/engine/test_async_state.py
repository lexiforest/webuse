import asyncio

import pytest

from crawl_helpers import AsyncFakeClient, FakeRedis
from webuse import (
    AsyncMemoryRequestQueue,
    AsyncMemoryRequestSeen,
    AsyncRedisRequestQueue,
    AsyncRedisRequestSeen,
    CrawlRequest,
    CloseSpider,
    acrawl,
)


class AsyncRedis:
    def __init__(self):
        self.backend = FakeRedis()

    def __getattr__(self, name):
        async def command(*args):
            await asyncio.sleep(0)
            return getattr(self.backend, name)(*args)

        return command


@pytest.mark.parametrize("redis", [False, True])
def test_async_state_roundtrip_and_atomic_dedupe(redis):
    async def run():
        client = AsyncRedis()
        queue = (
            AsyncRedisRequestQueue("queue", client=client)
            if redis
            else AsyncMemoryRequestQueue()
        )
        seen = (
            AsyncRedisRequestSeen("seen", client=client)
            if redis
            else AsyncMemoryRequestSeen()
        )
        request = CrawlRequest(
            url="https://example.com", page_type="detail", meta={"page": 1}
        )
        await queue.put(request)
        assert await queue.size() == 1
        assert not await queue.empty()
        assert await queue.pop() == request
        assert await queue.pop() is None
        added = await asyncio.gather(*(seen.add("same") for _ in range(20)))
        assert sum(added) == 1
        assert await seen.contains("same")
        assert await seen.size() == 1
        await queue.put(request)
        await queue.clear()
        assert await queue.empty()

    asyncio.run(run())


def test_redis_frontier_waits_for_active_discovery_and_reuses_seen():
    async def run():
        client = AsyncRedis()
        queue = AsyncRedisRequestQueue(client=client)
        seen = AsyncRedisRequestSeen(client=client)
        await queue.put(CrawlRequest(url="https://example.com"))

        async def parse(response):
            await asyncio.sleep(0)
            yield {"url": response.url}
            if response.crawl_request.depth == 0:
                yield "/page-1"
                yield "/page-1"

        result = await asyncio.wait_for(
            acrawl(
                [],
                extract=parse,
                max_depth=1,
                concurrency=5,
                request_queue=queue,
                request_seen=seen,
                client=AsyncFakeClient(),
            ),
            2,
        )
        assert len(result.items) == 2
        assert result.stats.skipped_duplicates == 1
        assert await queue.empty()
        again = await acrawl(
            "https://example.com",
            request_queue=queue,
            request_seen=seen,
            client=AsyncFakeClient(),
        )
        assert again.stats.fetched == 0

    asyncio.run(run())


@pytest.mark.parametrize("failure", ["pop", "add", "size"])
def test_async_backend_failure_does_not_hang(failure):
    async def run():
        queue, seen = AsyncMemoryRequestQueue(), AsyncMemoryRequestSeen()

        async def fail(*args):
            await asyncio.sleep(0)
            raise RuntimeError("backend unavailable")

        setattr(seen if failure == "add" else queue, failure, fail)
        with pytest.raises(RuntimeError, match="backend unavailable"):
            await asyncio.wait_for(
                acrawl(
                    "https://example.com",
                    request_queue=queue,
                    request_seen=seen,
                    client=AsyncFakeClient(),
                ),
                2,
            )

    asyncio.run(run())


def test_close_spider_clears_async_frontier():
    async def run():
        queue = AsyncMemoryRequestQueue()

        def parse(response):
            raise CloseSpider("done")

        result = await acrawl(
            ["https://example.com", "https://example.com/page-1"],
            extract=parse,
            concurrency=1,
            request_queue=queue,
            client=AsyncFakeClient(),
        )
        assert result.close_reason == "done"
        assert await queue.empty()

    asyncio.run(run())


def test_redis_cleanup_closes_only_owned_clients(monkeypatch):
    from redis.asyncio import Redis

    closed = []

    class Client:
        async def aclose(self):
            closed.append(self)

    owned, borrowed = Client(), Client()
    monkeypatch.setattr(Redis, "from_url", lambda url: owned)

    async def run():
        await AsyncRedisRequestQueue(redis_url="redis://localhost:6379/0").aclose()
        await AsyncRedisRequestSeen(client=borrowed).aclose()
        assert closed == [owned]

    asyncio.run(run())
