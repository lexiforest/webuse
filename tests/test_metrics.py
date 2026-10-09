import webuse
import asyncio
import pytest
from pydantic import BaseModel


class FakeMetricsClient:
    def __init__(self):
        self.calls = []

    def counter(self, bucket, value, tags=None):
        self.calls.append(("counter", bucket, value, tags or {}))

    def gauge(self, bucket, value, tags=None):
        self.calls.append(("gauge", bucket, value, tags or {}))

    def timer(self, bucket, value, tags=None):
        self.calls.append(("timer", bucket, value, tags or {}))

    def incr(self, bucket, value, tags=None):
        self.calls.append(("incr", bucket, value, tags or {}))

    def decr(self, bucket, value, tags=None):
        self.calls.append(("decr", bucket, value, tags or {}))


def test_attach_metrics_emits_request_and_response_metrics():
    signals = webuse.SignalBus()
    client = FakeMetricsClient()
    webuse.attach_metrics(signals, client=client, tags={"spider": "books"})
    response = webuse.Response(
        url="https://example.com", status_code=200, content=b"hello"
    )
    request = webuse.CrawlRequest(url="https://example.com")

    signals.send("request_queued", request=request, source="start")
    signals.send("request_before_downloader", request=request)
    signals.send("response_received", request=request, response=response)
    signals.send("request_after_downloader", request=request, success=True)

    assert (
        "counter",
        "request_queued",
        1,
        {"spider": "books", "source": "start"},
    ) in client.calls
    assert ("incr", "request_in_flight", 1, {"spider": "books"}) in client.calls
    assert (
        "counter",
        "response_received",
        1,
        {"spider": "books", "status": "200"},
    ) in client.calls
    assert (
        "gauge",
        "response_bytes",
        5,
        {"spider": "books", "status": "200"},
    ) in client.calls
    assert (
        "counter",
        "request_finished",
        1,
        {"spider": "books", "success": "true"},
    ) in client.calls
    assert any(
        call[0] == "timer" and call[1] == "request_duration" for call in client.calls
    )


def test_attach_metrics_emits_parse_and_item_metrics():
    signals = webuse.SignalBus()
    client = FakeMetricsClient()
    webuse.attach_metrics(signals, client=client)
    response = webuse.Response(url="https://example.com", status_code=200, content=b"")

    signals.send("parse_started", response=response)
    signals.send(
        "parse_finished",
        response=response,
        items=[{"title": "one"}],
        followups=["https://example.com/next"],
    )
    signals.send("item_extracted", item={"title": "one"})
    signals.send("item_processed", item={"title": "one"})

    assert ("gauge", "parse_items", 1, {}) in client.calls
    assert ("gauge", "parse_followups", 1, {}) in client.calls
    assert ("counter", "item_extracted", 1, {"item_type": "dict"}) in client.calls
    assert ("counter", "item_processed", 1, {"item_type": "dict"}) in client.calls
    assert any(
        call[0] == "timer" and call[1] == "parse_duration" for call in client.calls
    )


def test_attach_metrics_emits_pipeline_error_metrics():
    signals = webuse.SignalBus()
    client = FakeMetricsClient()
    webuse.attach_metrics(signals, client=client)
    pipeline = webuse.Pipeline()
    error = RuntimeError("broken")

    signals.send("pipeline_error", pipeline=pipeline, error=error)
    signals.send(
        "item_dropped", item={"title": "one"}, error=webuse.DropItem("duplicate")
    )

    assert (
        "counter",
        "pipeline_error",
        1,
        {"pipeline": "Pipeline", "error": "RuntimeError"},
    ) in client.calls
    assert (
        "counter",
        "item_dropped",
        1,
        {"item_type": "dict", "error": "DropItem"},
    ) in client.calls


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("drop", [False, True])
def test_pipeline_failure_balances_runtime_metrics(asynchronous, drop):
    class Item(BaseModel):
        title: str

    class Broken(webuse.Pipeline):
        def process_item(self, item):
            raise webuse.DropItem("skip") if drop else RuntimeError("broken")

    class Example(webuse.AsyncSpider if asynchronous else webuse.Spider):
        start_urls = ["https://example.com"]
        pipelines = [Broken()]

        def parse(self, response):
            return Item(title="one")

    class Client:
        def request(self, method, url, **kwargs):
            return webuse.Response(url=url, status_code=200, content=b"")

    class AsyncClient:
        async def request(self, *args, **kwargs):
            return Client().request(*args, **kwargs)

    signals = webuse.SignalBus()
    client = FakeMetricsClient()
    metrics = webuse.attach_metrics(signals, client=client)

    def run():
        spider = Example()
        if asynchronous:
            return asyncio.run(spider.run(client=AsyncClient(), signals=signals))
        return spider.run(client=Client(), signals=signals)

    if drop:
        assert run().items == []
    else:
        with pytest.raises(RuntimeError, match="broken"):
            run()
        assert ("counter", "crawl_error", 1, {"error": "RuntimeError"}) in client.calls
        assert (
            "counter",
            "pipeline_error",
            1,
            {"pipeline": "Broken", "error": "RuntimeError"},
        ) in client.calls
    for bucket in (
        "pipeline_in_flight",
        "parse_in_flight",
        "crawl_in_flight",
        "request_in_flight",
    ):
        assert (
            sum(
                value if kind == "incr" else -value
                for kind, name, value, _ in client.calls
                if name == bucket and kind in {"incr", "decr"}
            )
            == 0
        )
    assert not metrics._parse_started_at
    assert not metrics._pipeline_started_at
