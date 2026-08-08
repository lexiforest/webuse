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
    MemoryRequestQueue,
    MemoryRequestSeen,
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


def test_crawl_accepts_request_queue_and_seen():
    queue = MemoryRequestQueue()
    seen = MemoryRequestSeen(
        [DefaultRequestHasher().hash(CrawlRequest(url="https://example.com"))]
    )

    result = crawl(
        "https://example.com",
        client=FakeClient(),
        request_queue=queue,
        request_seen=seen,
    )

    assert result.stats.skipped_duplicates == 1
    assert result.stats.fetched == 0


def test_crawl_dedupes_by_request_hash_but_fetches_real_url():
    client = QueryClient()

    result = crawl(
        [
            "https://example.com/path?b=2&utm_source=news&a=1",
            "https://example.com/path?a=1&b=2",
        ],
        client=client,
        extract={"title": "h1"},
    )

    assert result.stats.fetched == 1
    assert result.stats.skipped_duplicates == 1
    assert client.requests == ["https://example.com/path?b=2&utm_source=news&a=1"]


def test_crawl_follows_links_and_enforces_depth():
    result = crawl(
        "https://example.com",
        client=FakeClient(),
        follow=FollowRule(css="a.next", same_domain=True),
        extract={"title": "h1"},
        max_depth=1,
        concurrency=2,
    )

    assert {page.url for page in result.pages} == {
        "https://example.com/",
        "https://example.com/page-1",
    }
    assert result.items == [{"title": "Home"}, {"title": "Page One"}]
    assert result.stats.followed_links == 1
    assert result.stats.skipped_rules == 1
    assert "https://example.com/page-2" not in result.visited


def test_crawl_follow_rule_assigns_request_category():
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
        def request(self, method, url, **kwargs):
            _ = (method, kwargs)
            return Response(url=url, status_code=200, content=pages[url])

        def close(self):
            return None

    def parse(response):
        return {
            "title": response.css_first("h1").text(),
            "category": response.request.category,
        }

    result = crawl(
        "https://example.com/",
        client=CategoryClient(),
        follow=FollowRule(css="a.detail", category="detail"),
        extract=parse,
        max_depth=1,
    )

    assert result.items == [
        {"title": "Listing", "category": None},
        {"title": "Detail", "category": "detail"},
    ]


def test_crawl_follow_rule_can_be_limited_to_source_category():
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
        def request(self, method, url, **kwargs):
            _ = (method, kwargs)
            return Response(url=url, status_code=200, content=pages[url])

        def close(self):
            return None

    result = crawl(
        "https://example.com/",
        client=CategoryClient(),
        follow=FollowRule(css="a.detail", source_category="default", category="detail"),
        extract=lambda response: {"title": response.css_first("h1").text()},
        max_depth=2,
    )

    assert result.items == [{"title": "Listing"}, {"title": "Detail"}]
    assert "https://example.com/detail-2" not in result.visited


def test_crawl_obeys_robots_txt():
    client = RobotsClient()

    result = crawl(
        "https://example.com",
        client=client,
        follow=FollowRule(css="a.next", same_domain=True),
        extract={"title": "h1"},
        max_depth=1,
        robots_txt=True,
        user_agent="webuse-test",
    )

    assert result.items == [{"title": "Home"}, {"title": "Allowed"}]
    assert result.stats.skipped_robots == 1
    assert "https://example.com/private" not in result.visited
    assert client.requests.count("https://example.com/robots.txt") == 1
    assert {page.url for page in result.pages} == {
        "https://example.com/",
        "https://example.com/allowed",
    }


def test_crawl_ignore_request_skips_callback_result():
    def parse(response):
        if response.url == "https://example.com/page-1":
            raise webuse.IgnoreRequest()
        return {"title": response.css_first("h1").text()}

    result = crawl(
        "https://example.com",
        client=FakeClient(),
        follow=FollowRule(css="a.next", same_domain=True),
        extract=parse,
        max_depth=1,
    )

    assert result.items == [{"title": "Home"}]
    assert result.stats.skipped_ignored == 1


def test_crawl_close_spider_stops_scheduling():
    def parse(response):
        raise webuse.CloseSpider("enough")

    result = crawl(
        "https://example.com",
        client=FakeClient(),
        follow=FollowRule(css="a.next", same_domain=True),
        extract=parse,
        max_depth=2,
    )

    assert result.close_reason == "enough"
    assert result.stats.fetched == 1
    assert "https://example.com/page-1" not in result.visited


def test_crawl_extracts_rich_rules(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    pages = {
        "https://example.com/": b"""
        <html><body>
          <h1>Catalog</h1>
          <a class="product" href="/products/alpha">Alpha</a>
          <a class="product" href="/products/beta">Beta</a>
          <a class="cta" href="/checkout">Buy now</a>
        </body></html>
        """,
    }

    class RichFakeClient:
        def request(self, method, url, **kwargs):
            _ = (method, kwargs)
            return Response(url=url, status_code=200, content=pages[url])

        def close(self):
            return None

    result = crawl(
        "https://example.com",
        client=RichFakeClient(),
        extract={
            "title": {"xpath": "//h1"},
            "product_links": {"css": "a.product", "attr": "href", "all": True},
            "primary_cta": {"smart": "buy now cta", "attr": "href"},
        },
    )

    assert result.items == [
        {
            "title": "Catalog",
            "product_links": [
                "https://example.com/products/alpha",
                "https://example.com/products/beta",
            ],
            "primary_cta": "https://example.com/checkout",
        }
    ]
