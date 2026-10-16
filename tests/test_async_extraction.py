import asyncio
import json
from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from crawl_helpers import AsyncFakeClient, PAGES
from webuse import (
    AsyncItemPipeline,
    AsyncSpider,
    AsyncLlmSelector,
    Response,
    acrawl,
)
from webuse.extract import Document
from webuse.llm import OpenAISettings
from webuse.signals import SignalBus


class Item(BaseModel):
    title: str


@pytest.mark.parametrize("with_pipelines", [False, True])
def test_response_streams_overlap_and_preserve_item_and_pipeline_order(with_pipelines):
    async def run():
        parse_barrier = asyncio.Barrier(3)
        pipeline_barrier = asyncio.Barrier(3)
        processed = []
        trace = {}

        async def parse(response):
            await parse_barrier.wait()
            for index in range(2):
                title = f"{response.url}:{index}"
                trace[title] = []
                yield Item(title=title)
                # A worker finishes this item before consuming its next one.
                assert title in processed
                assert trace[title] == (["first", "second"] if with_pipelines else [])

        class First(AsyncItemPipeline):
            async def process_item(self, item):
                await pipeline_barrier.wait()
                trace[item.title].append("first")
                return item

        class Second(AsyncItemPipeline):
            async def process_item(self, item):
                assert trace[item.title] == ["first"]
                await asyncio.sleep(0)
                trace[item.title].append("second")
                return item

        signals = SignalBus()
        signals.connect("item_processed", lambda item: processed.append(item.title))
        spider = AsyncSpider(
            start_urls=list(PAGES),
            concurrency=3,
            parse=parse,
            pipelines=[First(), Second()] if with_pipelines else [],
            signals=signals,
        )
        result = await asyncio.wait_for(spider.run(client=AsyncFakeClient()), 2)
        assert len(result.items) == len(processed) == 6
        assert {item.title for item in result.items} == set(trace)

    asyncio.run(run())


@pytest.mark.parametrize("cancel", [False, True])
def test_overlapping_pipeline_calls_stop_before_lifecycle_cleanup(cancel):
    async def run():
        active = set()
        closed_streams = set()
        all_started = asyncio.Event()
        finish = asyncio.Event()
        pipeline_closed = []

        async def parse(response):
            try:
                yield Item(title=response.url)
            finally:
                closed_streams.add(response.url)

        class Output(AsyncItemPipeline):
            async def process_item(self, item):
                active.add(item.title)
                if len(active) == 3:
                    all_started.set()
                try:
                    await all_started.wait()
                    if not cancel and item.title == "https://example.com/":
                        raise RuntimeError("sink failed")
                    await finish.wait()
                    return item
                finally:
                    active.remove(item.title)

            async def close_spider(self):
                assert not active
                pipeline_closed.append(True)

        spider = AsyncSpider(
            start_urls=list(PAGES), concurrency=3, parse=parse, pipelines=[Output()]
        )
        task = asyncio.create_task(spider.run(client=AsyncFakeClient()))
        try:
            await asyncio.wait_for(all_started.wait(), 2)
            if cancel:
                task.cancel()
            with pytest.raises(asyncio.CancelledError if cancel else RuntimeError):
                await asyncio.wait_for(task, 2)
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        assert closed_streams == set(PAGES)
        assert pipeline_closed == [True]

    asyncio.run(run())


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("shape", ["entries", "tuple"])
def test_pipeline_processes_each_yield_before_requesting_next(asynchronous, shape):
    processed = []

    class Output(AsyncItemPipeline):
        async def process_item(self, item):
            await asyncio.sleep(0)
            processed.append(item.title)
            return item

    def sync_entries():
        yield Item(title="first")
        assert processed == ["first"]
        yield Item(title="second")

    async def async_entries():
        yield Item(title="first")
        assert processed == ["first"]
        yield Item(title="second")

    def parse(response):
        entries = async_entries() if asynchronous else sync_entries()
        return (entries, []) if shape == "tuple" else entries

    result = asyncio.run(
        AsyncSpider(
            start_urls=["https://example.com"],
            parse=parse,
            pipelines=[Output()],
        ).run(client=AsyncFakeClient())
    )
    assert [item.title for item in result.items] == processed == ["first", "second"]


@pytest.mark.parametrize("cancel", [False, True])
def test_stream_closes_on_pipeline_failure_or_cancellation(cancel):
    async def run():
        closed = []
        started = asyncio.Event()

        async def parse(response):
            try:
                yield Item(title="first")
                pytest.fail("Must not consume the next item")
            finally:
                closed.append(True)

        class Output(AsyncItemPipeline):
            async def process_item(self, item):
                started.set()
                if cancel:
                    await asyncio.Event().wait()
                raise RuntimeError("sink failed")

        spider = AsyncSpider(
            start_urls=["https://example.com"], parse=parse, pipelines=[Output()]
        )
        task = asyncio.create_task(spider.run(client=AsyncFakeClient()))
        await asyncio.wait_for(started.wait(), 2)
        if cancel:
            task.cancel()
        with pytest.raises(asyncio.CancelledError if cancel else RuntimeError):
            await task
        assert closed == [True]

    asyncio.run(run())


class ModelClient:
    def __init__(self, content):
        self.content = content
        self.calls = []
        self.closed = False
        self.chat = SimpleNamespace(completions=self)

    async def create(self, **kwargs):
        await asyncio.sleep(0)
        self.calls.append(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=self.content))]
        )

    async def close(self):
        self.closed = True


@pytest.mark.parametrize("spider", [False, True])
def test_declarative_extraction_awaits_models_and_closes_owned_clients(
    monkeypatch, spider
):
    from webuse.extract import structured, resolver
    from webuse import llm

    sessions = []

    class ModelSession:
        async def __aenter__(self):
            self.closed = False
            sessions.append(self)
            return self

        async def __aexit__(self, *args):
            self.closed = True

        async def post(self, url, **kwargs):
            await asyncio.sleep(0)
            assert url == "https://model.test/v1/chat/completions"
            assert kwargs["headers"] == {"Authorization": "Bearer model-key"}
            assert kwargs["allow_redirects"] is False
            self.payload = kwargs["json"]
            content = (
                '{"indices": [0]}'
                if "candidates" in self.payload["messages"][1]["content"]
                else '["value"]'
            )
            return Response(
                content=json.dumps(
                    {"choices": [{"message": {"content": content}}]}
                ).encode()
            )

    monkeypatch.setattr(llm.requests, "AsyncSession", ModelSession)
    for module in (structured, resolver):
        monkeypatch.setattr(
            module,
            "openai_defaults",
            lambda: OpenAISettings(
                model="local", base_url="https://model.test/v1", api_key="model-key"
            ),
        )

    def block_sync(*args, **kwargs):
        pytest.fail("Async extraction must not call synchronous LLM methods")

    monkeypatch.setattr(Document, "llm_extract", block_sync)
    monkeypatch.setattr("webuse.extract.resolver.LlmSelector.select", block_sync)
    rules = {
        "default": {
            "page": {
                "fields": {
                    "title": "h1",
                    "value": {
                        "llm_extract": "value",
                        "schema": {"type": "array", "items": {"type": "string"}},
                    },
                    "values": {
                        "llm_extract": "values",
                        "schema": {"type": "array", "items": {"type": "string"}},
                    },
                    "selected": {"llm": "page"},
                }
            }
        }
    }

    async def run():
        if spider:
            result = await AsyncSpider(
                start_urls=["https://example.com"], extract=rules
            ).run(client=AsyncFakeClient())
        else:
            result = await acrawl(
                "https://example.com", extract=rules, client=AsyncFakeClient()
            )
        assert result.items[0]["title"] == "Home"
        assert result.items[0]["value"] == ["value"]
        assert result.items[0]["values"] == ["value"]
        assert "Home" in result.items[0]["selected"]
        assert len(sessions) == 3 and all(session.closed for session in sessions)
        assert sessions[0].payload["model"] == "local"

    asyncio.run(run())


def test_async_document_helpers_preserve_borrowed_clients(monkeypatch):
    from webuse.extract import structured, resolver

    for module in (structured, resolver):
        monkeypatch.setattr(
            module, "openai_defaults", lambda: OpenAISettings(model="local")
        )

    async def run():
        document = Response(content=b"<h1>hello</h1>")
        client = ModelClient('["hello"]')
        assert await document.allm_extract(
            "title", schema=list[str], client=client
        ) == ["hello"]
        assert not client.closed
        assert document._tree is None
        client.content = '{"indices": [0]}'
        assert (
            await document.afind(llm="page", selector=AsyncLlmSelector(client=client))
            is not None
        )
        assert not client.closed

    asyncio.run(run())
