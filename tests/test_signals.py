import asyncio

import pytest
import webuse
from pydantic import BaseModel

from webuse.response import Response


class FakeClient:
    def request(self, method, url, **kwargs):
        _ = (method, kwargs)
        return Response(
            url=url, status_code=200, content=b"<html><body><h1>Home</h1></body></html>"
        )

    def close(self):
        return None


class Item(BaseModel):
    title: str


def test_signal_bus_filters_handler_kwargs():
    bus = webuse.SignalBus()
    values = []

    def handler(item):
        values.append(item)

    bus.connect("item_processed", handler)
    bus.send("item_processed", item="one", spider=object(), extra=True)

    assert values == ["one"]


def test_signal_bus_rejects_async_handler_in_sync_send():
    bus = webuse.SignalBus()

    async def handler():
        return None

    bus.connect("crawl_started", handler)

    with pytest.raises(webuse.SignalError):
        bus.send("crawl_started")


def test_signal_bus_asend_awaits_async_handlers():
    bus = webuse.SignalBus()
    values = []

    async def handler(item):
        values.append(item)

    bus.connect("item_processed", handler)

    asyncio.run(bus.asend("item_processed", item="one"))

    assert values == ["one"]


def test_crawl_emits_core_signals():
    bus = webuse.SignalBus()
    events = []
    for name in [
        "crawl_started",
        "request_queued",
        "request_before_downloader",
        "request_after_downloader",
        "response_received",
        "parse_started",
        "parse_finished",
        "scheduler_empty",
        "crawl_finished",
    ]:
        bus.connect(name, lambda signal=name, **kwargs: events.append(signal))

    result = webuse.crawl(
        "https://example.com",
        client=FakeClient(),
        extract={"title": "h1"},
        signals=bus,
    )

    assert result.items == [{"title": "Home"}]
    assert events == [
        "crawl_started",
        "request_queued",
        "request_before_downloader",
        "request_after_downloader",
        "response_received",
        "parse_started",
        "parse_finished",
        "scheduler_empty",
        "crawl_finished",
    ]


def test_spider_emits_item_and_pipeline_signals():
    bus = webuse.SignalBus()
    events = []
    for name in [
        "spider_open",
        "item_extracted",
        "pipeline_started",
        "pipeline_finished",
        "item_processed",
        "spider_closed",
    ]:
        bus.connect(name, lambda signal=name, **kwargs: events.append(signal))

    class CleanPipeline(webuse.Pipeline):
        def process_item(self, item):
            return item.model_copy(update={"title": item.title.upper()})

    class ExampleSpider(webuse.Spider):
        start_urls = ["https://example.com"]
        extract = {"title": "h1"}
        item_model = Item
        pipelines = [CleanPipeline()]

    result = ExampleSpider().run(client=FakeClient(), signals=bus)

    assert result.items == [Item(title="HOME")]
    assert "spider_open" in events
    assert "item_extracted" in events
    assert "pipeline_started" in events
    assert "pipeline_finished" in events
    assert "item_processed" in events
    assert events[-1] == "spider_closed"
