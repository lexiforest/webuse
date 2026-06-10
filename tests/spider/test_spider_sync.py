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


def test_spider_runs_declarative_crawl():
    class ExampleSpider(Spider):
        start_urls = ["https://example.com"]
        follow = [FollowRule(css="a.next", same_domain=True)]
        extract = {"title": "h1"}
        max_depth = 1
        concurrency = 2

    result = ExampleSpider().run(client=FakeClient())

    assert result.items == [{"title": "Home"}, {"title": "Page One"}]
    assert result.stats.followed_links == 1
    assert webuse.Spider is Spider
    assert webuse.AsyncSpider is AsyncSpider

def test_custom_parse_replaces_declarative_extract():
    class ExampleSpider(Spider):
        start_urls = ["https://example.com"]
        extract = {"title": "h1"}

        def parse(self, response):
            return {"url": response.url}

    result = ExampleSpider().run(client=FakeClient())

    assert result.items == [{"url": "https://example.com/"}]

def test_spider_start_method_can_override_initial_requests():
    class StartSpider(Spider):
        start_urls = ["https://example.com/page-2"]
        extract = {"title": "h1"}

        def start(self):
            return ["https://example.com"]

    result = StartSpider().run(client=FakeClient())

    assert result.items == [{"title": "Home"}]

def test_spider_runs_from_yaml_config(tmp_path):
    config = tmp_path / "books.yaml"
    config.write_text(
        """
name: books
start_urls:
  - https://example.com
allowed_domains:
  - example.com
max_depth: 1
follow:
  - css: a.next
    same_domain: true
extract:
  title: h1
""",
        encoding="utf-8",
    )

    class ConfigSpider(Spider):
        spider_config_path = config

    spider = ConfigSpider()
    result = spider.run(client=FakeClient())

    assert result.items == [{"title": "Home"}, {"title": "Page One"}]
    assert result.stats.followed_links == 1
    assert spider.name is None

def test_spider_config_extracts_records_with_item_css(tmp_path):
    config = tmp_path / "items.yaml"
    config.write_text(
        """
start_urls:
  - https://example.com
extract:
  item_css: article.product
  fields:
    title:
      css: h3 a
      attr: title
    price: .price
""",
        encoding="utf-8",
    )

    class ItemClient:
        def request(self, method, url, **kwargs):
            return Response(
                url=url,
                status_code=200,
                content=b"""
<html><body>
  <article class="product">
    <h3><a title="One">One</a></h3>
    <p class="price">$1.00</p>
  </article>
  <article class="product">
    <h3><a title="Two">Two</a></h3>
  </article>
</body></html>
""",
            )

    class ConfigSpider(Spider):
        spider_config_path = config

    result = ConfigSpider().run(client=ItemClient())

    assert result.items == [
        {"title": "One", "price": "$1.00"},
        {"title": "Two", "price": None},
    ]

def test_spider_settings_precedence_config_then_run_overrides(tmp_path):
    config = tmp_path / "books.toml"
    config.write_text(
        """
start_urls = ["https://example.com"]
max_depth = 1

[[follow]]
css = "a.next"
same_domain = true

[extract]
title = "h1"
""",
        encoding="utf-8",
    )

    class ConfigSpider(Spider):
        spider_config_path = config
        start_urls = ["https://example.com/page-2"]
        max_depth = 0

    config_result = ConfigSpider().run(client=FakeClient())
    override_result = ConfigSpider().run(client=FakeClient(), max_depth=0)

    assert config_result.items == [{"title": "Home"}, {"title": "Page One"}]
    assert override_result.items == [{"title": "Home"}]

def test_spider_parse_can_return_items_and_followups():
    class ParseSpider(Spider):
        start_urls = ["https://example.com"]
        max_depth = 1

        def parse(self, response):
            title = response.css_first("h1").text()
            if response.url == "https://example.com/":
                return {"title": title}, CrawlRequest(url="https://example.com/page-1")
            return {"title": title}

    result = ParseSpider().run(client=FakeClient())

    assert result.items == [{"title": "Home"}, {"title": "Page One"}]

def test_spider_parse_can_yield_items_and_follow_requests():
    class ParseSpider(Spider):
        start_urls = ["https://example.com"]
        max_depth = 1

        def parse(self, response):
            yield {"title": response.css_first("h1").text()}
            if response.url == "https://example.com/":
                yield response.follow("/page-1", meta={"source": "home"})

    result = ParseSpider().run(client=FakeClient())

    assert result.items == [{"title": "Home"}, {"title": "Page One"}]
    assert any(page.url == "https://example.com/page-1" for page in result.pages)

def test_spider_routes_follow_request_by_category():
    class ParseSpider(Spider):
        start_urls = ["https://example.com"]
        max_depth = 1
        routes = {"detail": "parse_detail"}

        def parse(self, response):
            yield {"title": response.css_first("h1").text()}
            yield response.follow("/page-1", category="detail")

        def parse_detail(self, response):
            yield {"detail": response.css_first("h1").text()}

    result = ParseSpider().run(client=FakeClient())

    assert result.items == [{"title": "Home"}, {"detail": "Page One"}]

def test_spider_routes_follow_request_by_parse_method_name():
    class ParseSpider(Spider):
        start_urls = ["https://example.com"]
        max_depth = 1

        def parse(self, response):
            yield response.follow("/page-1", category="detail")

        def parse_detail(self, response):
            yield {"detail": response.css_first("h1").text()}

    result = ParseSpider().run(client=FakeClient())

    assert result.items == [{"detail": "Page One"}]

def test_spider_routes_can_use_handler_function():
    class ParseSpider(Spider):
        start_urls = ["https://example.com"]
        max_depth = 1

        def parse(self, response):
            yield response.follow("/page-1", category="detail")

        def parse_detail(self, response):
            yield {"detail": response.css_first("h1").text()}

        routes = {"detail": parse_detail}

    result = ParseSpider().run(client=FakeClient())

    assert result.items == [{"detail": "Page One"}]

def test_spider_parse_can_yield_pydantic_items():
    class ParseSpider(Spider):
        start_urls = ["https://example.com"]

        def parse(self, response):
            yield SampleItem(title=response.css_first("h1").text())

    result = ParseSpider().run(client=FakeClient())

    assert result.items == [SampleItem(title="Home")]

def test_response_follow_builds_crawl_request_with_options():
    response = Response(url="https://example.com/catalog/", status_code=200)

    request = response.follow(
        "../page-1",
        method="POST",
        options=webuse.RequestOptions(headers={"Accept": "text/html"}),
        category="detail",
        headers={"User-Agent": "webuse"},
        timeout=3,
        meta={"source": "catalog"},
    )

    assert request.url == "https://example.com/page-1"
    assert request.method == "POST"
    assert request.category == "detail"
    assert request.options.headers == {"User-Agent": "webuse"}
    assert request.options.extra_kwargs == {}
    assert request.options.timeout == 3
    assert request.meta == {"source": "catalog"}
    assert request.model_dump(mode="json")["category"] == "detail"
