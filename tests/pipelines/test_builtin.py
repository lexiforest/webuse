import asyncio
import csv
import hashlib
import json
import sqlite3

import pytest
import webuse
from webuse.crawl import (
    DefaultRequestHasher,
    FileRequestQueue,
    FileRequestSeen,
    RedisRequestQueue,
    RedisRequestSeen,
    canonical_request_url,
    acrawl,
    crawl,
)
from webuse.models import CrawlRequest, FollowRule
from webuse.pipelines import (
    AssetDownloadPipeline,
    DropItem,
    Pipeline,
    WebhookPipeline,
    resolve_pipeline,
)
from webuse.response import Response
from webuse.spider import AsyncSpider, Spider

from crawl_helpers import (
    AsyncFakeClient,
    AsyncRobotsClient,
    AssetItem,
    FakeAssetResponse,
    FakeAssetSession,
    FakeClient,
    FakeRedis,
    FakeWebhookResponse,
    FakeWebhookSession,
    QueryClient,
    RobotsClient,
    SampleItem,
)


def test_builtin_csv_pipeline(tmp_path):
    class CsvSpider(Spider):
        start_urls = ["https://example.com"]
        extract = {"title": "h1"}
        item_model = SampleItem
        pipelines = [{"type": "csv", "path": tmp_path / "items.csv"}]

    result = CsvSpider().run(client=FakeClient())

    assert result.items == [SampleItem(title="Home")]
    with (tmp_path / "items.csv").open(encoding="utf-8", newline="") as file:
        rows = list(csv.DictReader(file))
    assert rows == [{"title": "Home", "source": ""}]


def test_builtin_sqlite_pipeline(tmp_path):
    class SQLiteSpider(Spider):
        name = "sqlite-spider"
        start_urls = ["https://example.com"]
        extract = {"title": "h1"}
        item_model = SampleItem
        pipelines = [
            {"type": "sqlite", "path": tmp_path / "items.sqlite", "table": "records"}
        ]

    result = SQLiteSpider().run(client=FakeClient())

    assert result.items == [SampleItem(title="Home")]
    connection = sqlite3.connect(tmp_path / "items.sqlite")
    try:
        rows = connection.execute("SELECT item_type, data FROM records").fetchall()
    finally:
        connection.close()
    assert rows == [("SampleItem", json.dumps({"title": "Home", "source": ""}))]


def test_builtin_asset_download_pipeline_downloads_assets(tmp_path):
    url = "https://cdn.example.com/images/cover.JPG?size=small"
    session = FakeAssetSession(FakeAssetResponse(content=b"image-bytes"))
    pipeline = AssetDownloadPipeline(tmp_path / "assets", session=session)

    result = pipeline.process_item(AssetItem(title="Book", asset_urls=[url]))

    assert result.assets == [
        {
            "url": url,
            "path": result.assets[0]["path"],
            "checksum": hashlib.sha1(b"image-bytes").hexdigest(),
            "size": 11,
            "status": "downloaded",
        }
    ]
    assert str(result.assets[0]["path"]).endswith(".jpg")
    assert (
        tmp_path / "assets" / str(result.assets[0]["path"])
    ).read_bytes() == b"image-bytes"
    assert session.requests == [("GET", url, {"timeout": 30})]


def test_builtin_asset_download_pipeline_resolves_from_config_spec(tmp_path):
    url = "https://cdn.example.com/files/spec.pdf"
    session = FakeAssetSession(FakeAssetResponse(content=b"pdf"))
    pipeline = resolve_pipeline(
        {
            "type": "assets",
            "directory": tmp_path / "downloads",
            "session": session,
        }
    )

    result = pipeline.process_item(AssetItem(asset_urls=[url]))

    assert result.assets[0]["status"] == "downloaded"
    assert result.assets[0]["path"].endswith(".pdf")
    assert (tmp_path / "downloads" / result.assets[0]["path"]).read_bytes() == b"pdf"


def test_builtin_asset_download_pipeline_uses_cached_file(tmp_path):
    url = "https://cdn.example.com/files/spec.pdf"
    session = FakeAssetSession(FakeAssetResponse(content=b"new"))
    pipeline = AssetDownloadPipeline(tmp_path / "assets", session=session)
    first = pipeline.process_item(AssetItem(asset_urls=[url]))
    second = pipeline.process_item(AssetItem(asset_urls=[url]))

    assert first.assets[0]["status"] == "downloaded"
    assert second.assets[0]["status"] == "cached"
    assert second.assets[0]["checksum"] == hashlib.sha1(b"new").hexdigest()
    assert len(session.requests) == 1


def test_builtin_asset_download_pipeline_raises_on_http_error(tmp_path):
    url = "https://cdn.example.com/missing.png"
    session = FakeAssetSession(FakeAssetResponse(status_code=404, content=b"missing"))
    pipeline = AssetDownloadPipeline(tmp_path / "assets", session=session)

    with pytest.raises(webuse.PipelineError, match="HTTP 404"):
        pipeline.process_item(AssetItem(asset_urls=[url]))


def test_builtin_webhook_pipeline_sends_each_item():
    session = FakeWebhookSession()

    class WebhookSpider(Spider):
        start_urls = ["https://example.com"]
        extract = {"title": "h1"}
        item_model = SampleItem
        pipelines = [
            WebhookPipeline(
                "https://webhook.example/items",
                headers={"X-Token": "secret"},
                timeout=3,
                session=session,
            )
        ]

    result = WebhookSpider().run(client=FakeClient())

    assert result.items == [SampleItem(title="Home")]
    assert session.requests == [
        (
            "POST",
            "https://webhook.example/items",
            {
                "json": {"title": "Home", "source": ""},
                "headers": {"X-Token": "secret"},
                "timeout": 3,
            },
        )
    ]


def test_builtin_webhook_pipeline_resolves_from_config_spec():
    session = FakeWebhookSession()
    pipeline = resolve_pipeline(
        {
            "type": "webhook",
            "url": "https://webhook.example/items",
            "method": "put",
            "session": session,
        }
    )

    item = SampleItem(title="Home")
    assert pipeline.process_item(item) == item
    assert session.requests == [
        (
            "PUT",
            "https://webhook.example/items",
            {"json": {"title": "Home", "source": ""}, "timeout": 10},
        )
    ]


def test_builtin_webhook_pipeline_raises_on_http_error():
    session = FakeWebhookSession(FakeWebhookResponse(status_code=500, text="failed"))
    pipeline = WebhookPipeline("https://webhook.example/items", session=session)

    with pytest.raises(webuse.PipelineError, match="HTTP 500"):
        pipeline.process_item(SampleItem(title="Home"))
