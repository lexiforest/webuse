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
from webuse.exceptions import ConfigError
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
pages:
  default:
    follow:
      - css: a.next
        same_domain: true
    extract:
      page:
        fields:
          title: h1
""",
        encoding="utf-8",
    )

    class ConfigSpider(Spider):
        spider_config_path = config

    spider = ConfigSpider()
    result = spider.run(client=FakeClient())

    assert result.items == [
        {"title": "Home", "_type": "page"},
        {"title": "Page One", "_type": "page"},
    ]
    assert result.stats.followed_links == 1
    assert spider.name is None


def test_spider_config_rejects_old_top_level_follow_extract(tmp_path):
    config = tmp_path / "old.yaml"
    config.write_text(
        """
start_urls:
  - https://example.com
follow:
  - css: a.next
extract:
  title: h1
""",
        encoding="utf-8",
    )

    class ConfigSpider(Spider):
        spider_config_path = config

    with pytest.raises(ConfigError):
        ConfigSpider().run(client=FakeClient())


def test_spider_config_rejects_legacy_page_follow_from(tmp_path):
    config = tmp_path / "from.yaml"
    config.write_text(
        """
start_urls:
  - https://example.com
pages:
  default:
    follow:
      - css: a.next
        from: default
        category: detail
""",
        encoding="utf-8",
    )

    class ConfigSpider(Spider):
        spider_config_path = config

    with pytest.raises(ConfigError):
        ConfigSpider().run(client=FakeClient())


def test_spider_config_rejects_legacy_category_extract_shorthand(tmp_path):
    config = tmp_path / "extract.yaml"
    config.write_text(
        """
start_urls:
  - https://example.com
pages:
  default:
    extract:
      fields:
        title: h1
""",
        encoding="utf-8",
    )

    class ConfigSpider(Spider):
        spider_config_path = config

    with pytest.raises(ConfigError):
        ConfigSpider().run(client=FakeClient())


def test_spider_config_extracts_records_with_item_css(tmp_path):
    config = tmp_path / "items.yaml"
    config.write_text(
        """
start_urls:
  - https://example.com
pages:
  default:
    extract:
      products:
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
        {"title": "One", "price": "$1.00", "_type": "products"},
        {"title": "Two", "price": None, "_type": "products"},
    ]

def test_spider_config_extracts_by_request_category(tmp_path):
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
        def request(self, method, url, **kwargs):
            _ = (method, kwargs)
            return Response(url=url, status_code=200, content=pages[url])

    class ConfigSpider(Spider):
        spider_config_path = config

    result = ConfigSpider().run(client=CategoryClient())

    assert result.items == [
        {"title": "Listing", "_type": "listing"},
        {"detail_title": "Detail", "_type": "detail"},
    ]


def test_spider_config_follow_rule_can_be_limited_to_source_category(tmp_path):
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
        def request(self, method, url, **kwargs):
            _ = (method, kwargs)
            return Response(url=url, status_code=200, content=pages[url])

    class ConfigSpider(Spider):
        spider_config_path = config

    result = ConfigSpider().run(client=CategoryClient())

    assert result.items == [
        {"title": "Listing", "_type": "listing"},
        {"detail_title": "Detail", "_type": "detail"},
    ]
    assert "https://example.com/detail-2" not in result.visited


def test_spider_config_extracts_multiple_item_types_from_one_page(tmp_path):
    config = tmp_path / "multi-items.yaml"
    config.write_text(
        """
start_urls:
  - https://example.com/
pages:
  default:
    extract:
      books:
        item_css: article.product
        fields:
          title:
            css: h3 a
            attr: title
      categories:
        item_css: nav a
        fields:
          name: .
          url:
            css: .
            attr: href
""",
        encoding="utf-8",
    )

    class MultiItemClient:
        def request(self, method, url, **kwargs):
            _ = (method, kwargs)
            return Response(
                url=url,
                status_code=200,
                content=b"""
<html><body>
  <nav>
    <a href="/fiction">Fiction</a>
    <a href="/history">History</a>
  </nav>
  <article class="product"><h3><a title="One">One</a></h3></article>
  <article class="product"><h3><a title="Two">Two</a></h3></article>
</body></html>
""",
            )

    class ConfigSpider(Spider):
        spider_config_path = config

    result = ConfigSpider().run(client=MultiItemClient())

    assert result.items == [
        {"title": "One", "_type": "books"},
        {"title": "Two", "_type": "books"},
        {"name": "Fiction", "url": "https://example.com/fiction", "_type": "categories"},
        {"name": "History", "url": "https://example.com/history", "_type": "categories"},
    ]

def test_spider_settings_precedence_config_then_run_overrides(tmp_path):
    config = tmp_path / "books.toml"
    config.write_text(
        """
start_urls = ["https://example.com"]
max_depth = 1

[[pages.default.follow]]
css = "a.next"
same_domain = true

[pages.default.extract.page.fields]
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

    assert config_result.items == [
        {"title": "Home", "_type": "page"},
        {"title": "Page One", "_type": "page"},
    ]
    assert override_result.items == [{"title": "Home", "_type": "page"}]

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
