import asyncio
import csv
import json
import sqlite3
from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from webuse import AsyncSpider, PipelineError
from webuse.pipelines import AsyncItemPipeline, create_pipeline
from webuse.pipelines.utils import _apipeline_lifecycle
from crawl_helpers import AsyncFakeClient


class Item(BaseModel):
    title: str
    asset_urls: list[str] = []
    assets: list[dict] = []


@pytest.mark.parametrize("kind", ["jsonl", "csv", "sqlite"])
def test_async_file_pipelines_write_before_close_and_reopen(tmp_path, kind):
    path = tmp_path / "nested" / f"items.{kind}"

    async def run():
        for title in ("first", "second"):
            pipeline = create_pipeline({"type": kind, "path": path}, asynchronous=True)
            assert isinstance(pipeline, AsyncItemPipeline)
            async with _apipeline_lifecycle([pipeline]):
                await pipeline.process_item(Item(title=title))
                if kind == "sqlite":
                    with sqlite3.connect(path) as db:
                        assert (
                            db.execute("SELECT count(*) FROM items").fetchone()[0] > 0
                        )
                else:
                    assert title in path.read_text()
            assert (
                pipeline._connection is None
                if kind == "sqlite"
                else pipeline._file is None
            )

    asyncio.run(run())
    if kind == "jsonl":
        rows = [json.loads(line) for line in path.read_text().splitlines()]
    elif kind == "csv":
        with path.open() as file:
            rows = list(csv.DictReader(file))
    else:
        with sqlite3.connect(path) as db:
            rows = [json.loads(row[0]) for row in db.execute("SELECT data FROM items")]
    assert [row["title"] for row in rows] == ["first", "second"]


class Session:
    def __init__(self, status=200):
        self.status = status
        self.requests = []
        self.closed = False

    async def request(self, method, url, **kwargs):
        await asyncio.sleep(0)
        self.requests.append((method, url, kwargs))
        return SimpleNamespace(status_code=self.status, text="failed", content=b"asset")

    async def close(self):
        self.closed = True


@pytest.mark.parametrize("kind", ["webhook", "assets"])
@pytest.mark.parametrize("status", [200, 500])
def test_async_http_pipelines_await_io_and_preserve_borrowed_session(
    tmp_path, kind, status
):
    session = Session(status)
    options = (
        {"url": "https://sink.test"} if kind == "webhook" else {"directory": tmp_path}
    )
    pipeline = create_pipeline(
        {"type": kind, "session": session, **options}, asynchronous=True
    )
    item = Item(title="page", asset_urls=["https://example.com/image.png"])

    async def run():
        async with _apipeline_lifecycle([pipeline]):
            if status == 500:
                with pytest.raises(PipelineError, match="HTTP 500"):
                    await pipeline.process_item(item)
            else:
                result = await pipeline.process_item(item)
                if kind == "assets":
                    assert (
                        tmp_path / result.assets[0]["path"]
                    ).read_bytes() == b"asset"
                    cached = await pipeline.process_item(item)
                    assert cached.assets[0]["status"] == "cached"
        assert not session.closed
        assert len(session.requests) == 1

    asyncio.run(run())


def test_async_spider_selects_configured_async_pipeline(tmp_path):
    path = tmp_path / "items.jsonl"
    spider = AsyncSpider(
        start_urls=["https://example.com"],
        parse=lambda response: Item(title="page"),
        pipelines=[{"type": "jsonl", "path": path}],
    )
    asyncio.run(spider.run(client=AsyncFakeClient()))
    assert json.loads(path.read_text())["title"] == "page"


def test_owned_async_http_session_closes_on_cancellation(monkeypatch):
    from webuse.pipelines.builtin import aio

    session = Session()
    monkeypatch.setattr(aio, "AsyncSession", lambda: session)

    async def run():
        pipeline = aio.AsyncWebhookPipeline("https://sink.test")
        with pytest.raises(asyncio.CancelledError):
            async with _apipeline_lifecycle([pipeline]):
                raise asyncio.CancelledError()
        assert session.closed

    asyncio.run(run())
