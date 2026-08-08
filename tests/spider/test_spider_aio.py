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


def test_async_spider_run_is_async_entrypoint():
    class ExampleSpider(AsyncSpider):
        start_urls = ["https://example.com"]
        follow = [FollowRule(css="a.next", same_domain=True)]
        extract = {"title": "h1"}
        max_depth = 1

        async def parse(self, response):
            return {"url": response.url}

    async def run_spider():
        return await ExampleSpider().run(client=AsyncFakeClient())

    result = asyncio.run(run_spider())

    assert result.items == [
        {"url": "https://example.com/"},
        {"url": "https://example.com/page-1"},
    ]


def test_async_spider_config_extracts_by_request_category(tmp_path):
    config = tmp_path / "categories.yaml"
    config.write_text(
        """
start_urls:
  - https://example.com/
max_depth: 1
pages:
  default:
    follow:
      - css: a.detail
        category: detail
    extract:
      listing:
        fields:
          title: h1
  detail:
    extract:
      detail:
        fields:
          detail_title: h1
""",
        encoding="utf-8",
    )

    pages = {
        "https://example.com/": b"""
<html><body>
  <h1>Listing</h1>
  <a class="detail" href="/detail">Detail</a>
</body></html>
""",
        "https://example.com/detail": b"<html><body><h1>Detail</h1></body></html>",
    }

    class CategoryClient:
        async def request(self, method, url, **kwargs):
            _ = (method, kwargs)
            return Response(url=url, status_code=200, content=pages[url])

    class ConfigSpider(AsyncSpider):
        spider_config_path = config

    async def run_spider():
        return await ConfigSpider().run(client=CategoryClient())

    result = asyncio.run(run_spider())

    assert result.items == [
        {"title": "Listing", "_type": "listing"},
        {"detail_title": "Detail", "_type": "detail"},
    ]


def test_async_spider_config_follow_rule_can_be_limited_to_source_category(tmp_path):
    config = tmp_path / "source-category.yaml"
    config.write_text(
        """
start_urls:
  - https://example.com/
max_depth: 2
pages:
  default:
    follow:
      - css: a.detail
        category: detail
    extract:
      listing:
        fields:
          title: h1
  detail:
    extract:
      detail:
        fields:
          detail_title: h1
""",
        encoding="utf-8",
    )

    pages = {
        "https://example.com/": b"""
<html><body>
  <h1>Listing</h1>
  <a class="detail" href="/detail">Detail</a>
</body></html>
""",
        "https://example.com/detail": b"""
<html><body>
  <h1>Detail</h1>
  <a class="detail" href="/detail-2">Detail Two</a>
</body></html>
""",
        "https://example.com/detail-2": b"<html><body><h1>Detail Two</h1></body></html>",
    }

    class CategoryClient:
        async def request(self, method, url, **kwargs):
            _ = (method, kwargs)
            return Response(url=url, status_code=200, content=pages[url])

    class ConfigSpider(AsyncSpider):
        spider_config_path = config

    async def run_spider():
        return await ConfigSpider().run(client=CategoryClient())

    result = asyncio.run(run_spider())

    assert result.items == [
        {"title": "Listing", "_type": "listing"},
        {"detail_title": "Detail", "_type": "detail"},
    ]
    assert "https://example.com/detail-2" not in result.visited


def test_async_spider_parse_can_yield_items_and_follow_requests():
    class ExampleSpider(AsyncSpider):
        start_urls = ["https://example.com"]
        max_depth = 1

        async def parse(self, response):
            yield {"title": response.css_first("h1").text()}
            if response.url == "https://example.com/":
                yield response.follow("/page-1")

    async def run_spider():
        return await ExampleSpider().run(client=AsyncFakeClient())

    result = asyncio.run(run_spider())

    assert result.items == [{"title": "Home"}, {"title": "Page One"}]


def test_async_spider_routes_follow_request_by_category():
    class ExampleSpider(AsyncSpider):
        start_urls = ["https://example.com"]
        max_depth = 1
        routes = {"detail": "parse_detail"}

        async def parse(self, response):
            yield response.follow("/page-1", category="detail")

        async def parse_detail(self, response):
            yield {"detail": response.css_first("h1").text()}

    async def run_spider():
        return await ExampleSpider().run(client=AsyncFakeClient())

    result = asyncio.run(run_spider())

    assert result.items == [{"detail": "Page One"}]
