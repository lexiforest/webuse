import asyncio

import pytest

from crawl_helpers import AsyncFakeClient, FakeClient, SampleItem
from webuse import AsyncItemPipeline, AsyncSpider, ItemPipeline, SignalBus, Spider
from webuse.exceptions import DropItem, PipelineError


def run_spider(asynchronous, pipelines):
    spider_class = AsyncSpider if asynchronous else Spider
    spider = spider_class(
        start_urls=["https://example.com"],
        parse=lambda response: SampleItem(title="Home"),
        pipelines=pipelines,
    )
    if asynchronous:
        return asyncio.run(spider.run(client=AsyncFakeClient()))
    return spider.run(client=FakeClient())


@pytest.mark.parametrize("asynchronous", [False, True])
def test_open_failure_closes_previous_pipelines_and_preserves_cleanup_errors(
    asynchronous,
):
    events = []
    opening_error = ValueError("open")
    closing_error = RuntimeError("close")

    class First(ItemPipeline):
        def open_spider(self):
            events.append("open first")

        def close_spider(self):
            events.append("close first")
            raise closing_error

    class Second(ItemPipeline):
        def open_spider(self):
            raise opening_error

        def close_spider(self):
            pytest.fail("Failed opener was never registered as open")

    pipelines = [First(), Second()]

    with pytest.raises(ExceptionGroup) as raised:
        run_spider(asynchronous, pipelines)
    assert raised.value.exceptions == (opening_error, closing_error)
    assert events == ["open first", "close first"]


@pytest.mark.parametrize("asynchronous", [False, True])
def test_processing_and_all_cleanup_errors_are_preserved(asynchronous):
    events = []
    processing_error = ValueError("process")
    closing_errors = [RuntimeError("close first"), RuntimeError("close second")]

    class Failing(ItemPipeline):
        def __init__(self, index):
            self.index = index

        def process_item(self, item):
            raise processing_error

        def close_spider(self):
            events.append(self.index)
            raise closing_errors[self.index]

    pipelines = [Failing(0), Failing(1)]

    with pytest.raises(ExceptionGroup) as raised:
        run_spider(asynchronous, pipelines)
    assert raised.value.exceptions == (
        processing_error,
        closing_errors[1],
        closing_errors[0],
    )
    assert events == [1, 0]


@pytest.mark.parametrize("pipeline", [AsyncItemPipeline(), AsyncItemPipeline])
def test_async_pipeline_defaults_work_through_factory(pipeline):
    result = run_spider(True, [pipeline])
    assert result.items == [SampleItem(title="Home")]


def test_sync_spider_rejects_async_pipeline():
    with pytest.raises(PipelineError, match="AsyncSpider"):
        run_spider(False, [AsyncItemPipeline()])


def test_async_spider_supports_mixed_hooks_and_signal_context():
    events = []
    signals = SignalBus()
    signals.connect(
        "item_processed", lambda item, spider: events.append((item.title, spider))
    )

    class Filter(ItemPipeline):
        def process_item(self, item):
            if item.title == "drop":
                raise DropItem()
            if item.title == "skip":
                return None
            return item

    class AsyncOutput(AsyncItemPipeline):
        async def open_spider(self):
            events.append("open")

        async def process_item(self, item):
            return item.model_copy(update={"title": item.title.upper()})

        async def close_spider(self):
            events.append("close")

    spider = AsyncSpider(
        start_urls=["https://example.com"],
        parse=lambda response: [SampleItem(title=t) for t in ["drop", "skip", "home"]],
        pipelines=[Filter(), AsyncOutput()],
        signals=signals,
    )
    result = asyncio.run(spider.run(client=AsyncFakeClient()))
    assert result.items == [SampleItem(title="HOME")]
    assert events == ["open", ("HOME", spider), "close"]


@pytest.mark.parametrize(
    "asynchronous,async_hook", [(False, False), (True, False), (True, True)]
)
@pytest.mark.parametrize("drop_method", ["none", "exception"])
def test_dropped_items_emit_matching_events(asynchronous, async_hook, drop_method):
    events = []
    signals = SignalBus()
    for name in (
        "item_extracted",
        "pipeline_started",
        "pipeline_finished",
        "item_dropped",
        "item_processed",
        "pipeline_error",
        "item_error",
    ):
        signals.connect(
            name,
            lambda signal_name=name, **context: events.append((signal_name, context)),
        )

    item = SampleItem(title="Home")
    error = DropItem("Filtered")

    def drop(item):
        if drop_method == "exception":
            raise error
        return None

    class Filter(ItemPipeline):
        process_item = staticmethod(drop)

    class AsyncFilter(AsyncItemPipeline):
        async def process_item(self, item):
            return drop(item)

    class Output(ItemPipeline):
        def process_item(self, item):
            pytest.fail("Dropped items must not reach later pipelines")

    pipeline = AsyncFilter() if async_hook else Filter()
    spider_class = AsyncSpider if asynchronous else Spider
    spider = spider_class(
        start_urls=["https://example.com"],
        parse=lambda response: item,
        pipelines=[pipeline, Output()],
        signals=signals,
    )
    result = (
        asyncio.run(spider.run(client=AsyncFakeClient()))
        if asynchronous
        else spider.run(client=FakeClient())
    )
    assert result.items == []
    assert result.errors == []
    assert [name for name, _ in events] == [
        "item_extracted",
        "pipeline_started",
        "pipeline_finished",
        "item_dropped",
    ]
    assert all(context["item"] is item for _, context in events)
    assert all(context["spider"] is spider for _, context in events)
    assert events[2][1]["pipeline"] is pipeline
    dropped_error = events[3][1]["error"]
    assert isinstance(dropped_error, DropItem)
    if drop_method == "exception":
        assert dropped_error is error


def test_sync_spider_rejects_async_hooks_without_leaking_coroutines():
    coroutines = []

    async def open_hook():
        pass

    class AsyncOpen(ItemPipeline):
        def open_spider(self):
            coroutine = open_hook()
            coroutines.append(coroutine)
            return coroutine

    with pytest.raises(PipelineError, match="AsyncSpider"):
        run_spider(False, [AsyncOpen()])
    assert coroutines[0].cr_frame is None


@pytest.mark.parametrize("concurrency", [1, 2, 3])
def test_async_spider_bounds_pipeline_calls_by_worker_count(concurrency):
    active = 0
    peak = 0

    class Output(AsyncItemPipeline):
        async def process_item(self, item):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0)
            active -= 1
            return item

    spider = AsyncSpider(
        start_urls=[
            "https://example.com",
            "https://example.com/page-1",
            "https://example.com/page-2",
        ],
        concurrency=concurrency,
        parse=lambda response: (
            SampleItem(title=f"{response.url}:{index}") for index in range(4)
        ),
        pipelines=[Output()],
    )
    result = asyncio.run(spider.run(client=AsyncFakeClient()))
    assert len(result.items) == 12
    assert active == 0
    assert peak == concurrency
