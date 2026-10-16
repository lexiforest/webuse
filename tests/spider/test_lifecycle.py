import asyncio

import pytest

from crawl_helpers import AsyncFakeClient, FakeClient
from webuse import AsyncItemPipeline, AsyncSpider, ItemPipeline, SignalBus, Spider
from webuse.exceptions import SpiderError


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("failure", ["open", "parse", "close", "signal"])
def test_failed_run_cleans_up_and_spider_can_be_reused(asynchronous, failure):
    events = []
    error = RuntimeError(failure)
    signals = SignalBus()

    def closed(result, reason):
        events.append(("closed", reason, result is not None))
        if failure == "signal":
            raise error

    signals.connect("spider_closed", closed)

    class Output(ItemPipeline):
        def open_spider(self):
            events.append("open")
            if failure == "open":
                raise error

        def close_spider(self):
            events.append("close")
            if failure == "close":
                raise error

    def parse(response):
        assert spider._run_state is not None
        if failure == "parse":
            raise error
        return None

    spider_class = AsyncSpider if asynchronous else Spider
    client = AsyncFakeClient() if asynchronous else FakeClient()
    spider = spider_class(start_urls=["https://example.com"], parse=parse)

    def run(**kwargs):
        result = spider.run(client=client, **kwargs)
        return asyncio.run(result) if asynchronous else result

    with pytest.raises(RuntimeError) as raised:
        run(pipelines=[Output()], signals=signals)
    assert raised.value is error
    assert spider._run_state is None
    expected = ["open"] if failure == "open" else ["open", "close"]
    expected.append(
        (
            "closed",
            "finished" if failure == "signal" else "error",
            failure in {"close", "signal"},
        )
    )
    assert events == expected

    spider.parse = lambda response: {"title": response.find(css="h1").text()}
    assert run(pipelines=[]).items == [{"title": "Home"}]
    assert spider._run_state is None


@pytest.mark.parametrize("phase", ["open", "parse"])
def test_cancellation_closes_pipelines_and_rejects_overlapping_runs(phase):
    async def run():
        reached = asyncio.Event()
        blocked = asyncio.Event()
        events = []
        signals = SignalBus()
        signals.connect("spider_closed", lambda reason: events.append(reason))

        class First(AsyncItemPipeline):
            async def close_spider(self):
                await asyncio.sleep(0)
                events.append("close first")

        class Second(AsyncItemPipeline):
            async def open_spider(self):
                if phase == "open":
                    reached.set()
                    await blocked.wait()

            async def close_spider(self):
                events.append("close second")

        async def parse(response):
            reached.set()
            await blocked.wait()

        spider = AsyncSpider(start_urls=["https://example.com"], parse=parse)
        task = asyncio.create_task(
            spider.run(
                client=AsyncFakeClient(), pipelines=[First(), Second()], signals=signals
            )
        )
        try:
            await asyncio.wait_for(reached.wait(), timeout=2)
            with pytest.raises(SpiderError, match="one crawl at a time"):
                await spider.run(client=AsyncFakeClient())
        finally:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        expected = ["close second"] if phase == "parse" else []
        assert events == [*expected, "close first", "cancelled"]
        assert spider._run_state is None
        spider.parse = lambda response: {"title": "Home"}
        result = await spider.run(client=AsyncFakeClient(), pipelines=[])
        assert result.items == [{"title": "Home"}]

    asyncio.run(run())
