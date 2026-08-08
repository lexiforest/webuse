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


def test_acrawl_follow_rule_assigns_request_category():
    pages = {
        "https://example.com/": b"""
        <html><body>
          <a class="detail" href="/detail">Detail</a>
          <h1>Listing</h1>
        </body></html>
        """,
        "https://example.com/detail": b"<html><body><h1>Detail</h1></body></html>",
    }

    class CategoryClient:
        async def request(self, method, url, **kwargs):
            _ = (method, kwargs)
            return Response(url=url, status_code=200, content=pages[url])

        async def __aexit__(self, exc_type, exc, tb):
            return None

    def parse(response):
        return {
            "title": response.css_first("h1").text(),
            "category": response.request.category,
        }

    async def run_crawl():
        return await acrawl(
            "https://example.com/",
            client=CategoryClient(),
            follow=FollowRule(css="a.detail", category="detail"),
            extract=parse,
            max_depth=1,
        )

    result = asyncio.run(run_crawl())

    assert result.items == [
        {"title": "Listing", "category": None},
        {"title": "Detail", "category": "detail"},
    ]


def test_acrawl_follow_rule_can_be_limited_to_source_category():
    pages = {
        "https://example.com/": b"""
        <html><body>
          <a class="detail" href="/detail">Detail</a>
          <h1>Listing</h1>
        </body></html>
        """,
        "https://example.com/detail": b"""
        <html><body>
          <a class="detail" href="/detail-2">Detail Two</a>
          <h1>Detail</h1>
        </body></html>
        """,
        "https://example.com/detail-2": b"<html><body><h1>Detail Two</h1></body></html>",
    }

    class CategoryClient:
        async def request(self, method, url, **kwargs):
            _ = (method, kwargs)
            return Response(url=url, status_code=200, content=pages[url])

        async def __aexit__(self, exc_type, exc, tb):
            return None

    async def run_crawl():
        return await acrawl(
            "https://example.com/",
            client=CategoryClient(),
            follow=FollowRule(
                css="a.detail", source_category="default", category="detail"
            ),
            extract=lambda response: {"title": response.css_first("h1").text()},
            max_depth=2,
        )

    result = asyncio.run(run_crawl())

    assert result.items == [{"title": "Listing"}, {"title": "Detail"}]
    assert "https://example.com/detail-2" not in result.visited


def test_acrawl_obeys_robots_txt():
    client = AsyncRobotsClient()

    async def run_crawl():
        return await acrawl(
            "https://example.com",
            client=client,
            follow=FollowRule(css="a.next", same_domain=True),
            extract={"title": "h1"},
            max_depth=1,
            robots_txt=True,
            user_agent="webuse-test",
        )

    result = asyncio.run(run_crawl())

    assert result.items == [{"title": "Home"}, {"title": "Allowed"}]
    assert result.stats.skipped_robots == 1
    assert "https://example.com/private" not in result.visited
    assert client.requests.count("https://example.com/robots.txt") == 1
