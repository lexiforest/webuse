import csv
import asyncio
import hashlib
import json
import sqlite3

import pytest
import webuse
from pydantic import BaseModel
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
from webuse.spider import AsyncSpider, Spider
from webuse.models import CrawlRequest, FollowRule
from webuse.pipelines import (
    AssetDownloadPipeline,
    DropItem,
    Pipeline,
    WebhookPipeline,
    resolve_pipeline,
)
from webuse.response import Response


PAGES = {
    "https://example.com/": b"""
    <html><body>
      <a class="next" href="/page-1">Page 1</a>
      <h1>Home</h1>
    </body></html>
    """,
    "https://example.com/page-1": b"""
    <html><body>
      <a class="next" href="/page-2">Page 2</a>
      <h1>Page One</h1>
    </body></html>
    """,
    "https://example.com/page-2": b"""
    <html><body><h1>Page Two</h1></body></html>
    """,
}


class FakeClient:
    def request(self, method, url, **kwargs):
        _ = (method, kwargs)
        return Response(url=url, status_code=200, content=PAGES[url])

    def close(self):
        return None


class AsyncFakeClient:
    async def request(self, method, url, **kwargs):
        _ = (method, kwargs)
        return Response(url=url, status_code=200, content=PAGES[url])


class SampleItem(BaseModel):
    title: str
    source: str = ""


class AssetItem(BaseModel):
    title: str = ""
    asset_urls: list[str] = []
    assets: list[dict[str, object]] = []


class FakeAssetResponse:
    def __init__(self, status_code=200, content=b"asset-bytes"):
        self.status_code = status_code
        self.content = content


class FakeAssetSession:
    def __init__(self, response=None):
        self.response = response or FakeAssetResponse()
        self.requests = []
        self.closed = False

    def request(self, method, url, **kwargs):
        self.requests.append((method, url, kwargs))
        return self.response

    def close(self):
        self.closed = True


class FakeWebhookResponse:
    def __init__(self, status_code=200, text="ok"):
        self.status_code = status_code
        self.text = text


class FakeWebhookSession:
    def __init__(self, response=None):
        self.response = response or FakeWebhookResponse()
        self.requests = []
        self.closed = False

    def request(self, method, url, **kwargs):
        self.requests.append((method, url, kwargs))
        return self.response

    def close(self):
        self.closed = True


ROBOTS_PAGES = {
    "https://example.com/": b"""
    <html><body>
      <a class="next" href="/allowed">Allowed</a>
      <a class="next" href="/private">Private</a>
      <h1>Home</h1>
    </body></html>
    """,
    "https://example.com/allowed": b"""
    <html><body><h1>Allowed</h1></body></html>
    """,
    "https://example.com/private": b"""
    <html><body><h1>Private</h1></body></html>
    """,
    "https://example.com/robots.txt": b"""
    User-agent: *
    Disallow: /private
    """,
}


class RobotsClient:
    def __init__(self):
        self.requests = []

    def request(self, method, url, **kwargs):
        _ = (method, kwargs)
        self.requests.append(url)
        return Response(url=url, status_code=200, content=ROBOTS_PAGES[url])

    def close(self):
        return None


class AsyncRobotsClient:
    def __init__(self):
        self.requests = []

    async def request(self, method, url, **kwargs):
        _ = (method, kwargs)
        self.requests.append(url)
        return Response(url=url, status_code=200, content=ROBOTS_PAGES[url])


class FakeRedis:
    def __init__(self):
        self.lists = {}
        self.sets = {}

    def rpush(self, key, value):
        self.lists.setdefault(key, []).append(value)

    def lpop(self, key):
        values = self.lists.setdefault(key, [])
        return values.pop(0) if values else None

    def llen(self, key):
        return len(self.lists.get(key, []))

    def delete(self, key):
        self.lists.pop(key, None)
        self.sets.pop(key, None)

    def sadd(self, key, value):
        values = self.sets.setdefault(key, set())
        if value in values:
            return 0
        values.add(value)
        return 1

    def sismember(self, key, value):
        return value in self.sets.get(key, set())


class QueryClient:
    def __init__(self):
        self.requests = []

    def request(self, method, url, **kwargs):
        _ = (method, kwargs)
        self.requests.append(url)
        return Response(
            url=url, status_code=200, content=b"<html><body><h1>Home</h1></body></html>"
        )

    def close(self):
        return None


def test_canonical_request_url_sorts_params_and_removes_tracking_params():
    assert (
        canonical_request_url("HTTPS://Example.COM/path?b=2&utm_source=x&a=1#frag")
        == "https://example.com/path?a=1&b=2"
    )


def test_default_request_hasher_uses_method_and_canonical_url_by_default():
    hasher = DefaultRequestHasher()
    first = CrawlRequest(
        url="https://example.com/path?b=2&utm_source=x&a=1", method="GET"
    )
    second = CrawlRequest(url="https://example.com/path?a=1&b=2", method="GET")
    third = CrawlRequest(url="https://example.com/path?a=1&b=2", method="POST")

    assert hasher.hash(first) == hasher.hash(second)
    assert hasher.hash(first) != hasher.hash(third)


def test_default_request_hasher_can_include_headers():
    plain = DefaultRequestHasher()
    with_headers = DefaultRequestHasher(include_headers=["Accept-Language"])
    first = CrawlRequest(
        url="https://example.com",
        options=webuse.RequestOptions(headers={"Accept-Language": "en"}),
    )
    second = CrawlRequest(
        url="https://example.com",
        options=webuse.RequestOptions(headers={"Accept-Language": "fr"}),
    )

    assert plain.hash(first) == plain.hash(second)
    assert with_headers.hash(first) != with_headers.hash(second)


def test_memory_request_queue_uses_queue_object():
    request = CrawlRequest(url="https://example.com")
    queue = MemoryRequestQueue([request])

    assert queue._queue.__class__.__module__ == "queue"
    assert queue.pop() == request
    assert queue.pop() is None


def test_file_request_queue_persists_jsonl(tmp_path):
    path = tmp_path / "queue.jsonl"
    queue = FileRequestQueue(path)
    request = CrawlRequest(url="https://example.com", category="detail")

    queue.put(request)
    loaded = FileRequestQueue(path)

    assert loaded.pop() == request
    assert path.read_text(encoding="utf-8").count("\n") == 1


def test_file_request_seen_persists_jsonl(tmp_path):
    path = tmp_path / "seen.jsonl"
    seen = FileRequestSeen(path)

    assert seen.add("hash-1")
    assert not seen.add("hash-1")
    assert FileRequestSeen(path).contains("hash-1")
    assert path.read_text(encoding="utf-8").splitlines() == ['{"hash": "hash-1"}']


def test_redis_request_queue_and_seen_use_list_and_set():
    client = FakeRedis()
    queue = RedisRequestQueue("queue", client=client)
    seen = RedisRequestSeen("seen", client=client)
    request = CrawlRequest(url="https://example.com")

    queue.put(request)

    assert not queue.empty()
    assert queue.pop() == request
    assert queue.empty()
    assert seen.add("hash-1")
    assert not seen.add("hash-1")
    assert seen.contains("hash-1")


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


def test_acrawl_close_spider_stops_scheduling():
    async def parse(response):
        raise webuse.CloseSpider("async-enough")

    async def run_crawl():
        return await acrawl(
            "https://example.com",
            client=AsyncFakeClient(),
            follow=FollowRule(css="a.next", same_domain=True),
            extract=parse,
            max_depth=2,
        )

    result = asyncio.run(run_crawl())

    assert result.close_reason == "async-enough"
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


def test_spider_runs_from_toml_config(tmp_path):
    config = tmp_path / "books.toml"
    config.write_text(
        """
name = "books"
start_urls = ["https://example.com"]
allowed_domains = ["example.com"]
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

    spider = ConfigSpider()
    result = spider.run(client=FakeClient())

    assert result.items == [{"title": "Home"}, {"title": "Page One"}]
    assert result.stats.followed_links == 1
    assert spider.name is None


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


def test_spider_pipelines_process_and_drop_items():
    events = []

    class CleanPipeline(Pipeline):
        def open_spider(self):
            events.append("open")

        def process_item(self, item):
            return item.model_copy(update={"title": item.title.upper()})

        def close_spider(self):
            events.append("close")

    class DropPageOnePipeline(Pipeline):
        def process_item(self, item):
            if item.title == "PAGE ONE":
                raise DropItem("duplicate")
            return item

    class PipelineSpider(Spider):
        start_urls = ["https://example.com"]
        follow = [FollowRule(css="a.next", same_domain=True)]
        extract = {"title": "h1"}
        item_model = SampleItem
        max_depth = 1
        pipelines = [CleanPipeline(), DropPageOnePipeline()]

    result = PipelineSpider().run(client=FakeClient())

    assert result.items == [SampleItem(title="HOME")]
    assert events == ["open", "close"]


def test_spider_pipelines_require_pydantic_items():
    class PipelineSpider(Spider):
        start_urls = ["https://example.com"]
        extract = {"title": "h1"}
        pipelines = [Pipeline()]

    with pytest.raises(webuse.PipelineError, match="BaseModel"):
        PipelineSpider().run(client=FakeClient())


def test_project_level_jsonl_pipeline_from_webuse_toml(tmp_path):
    (tmp_path / "webuse.toml").write_text(
        """
[items.pipelines]
default = [
  { type = "jsonl", path = "items.jsonl" },
]
""",
        encoding="utf-8",
    )

    class ProjectSpider(Spider):
        project_dir = tmp_path
        start_urls = ["https://example.com"]
        extract = {"title": "h1"}
        item_model = SampleItem

    result = ProjectSpider().run(client=FakeClient())
    lines = (tmp_path / "items.jsonl").read_text(encoding="utf-8").splitlines()

    assert result.items == [SampleItem(title="Home")]
    assert lines == ['{"title": "Home", "source": ""}']


def test_spider_does_not_search_upwards_for_project_config(tmp_path, monkeypatch):
    project = tmp_path / "project"
    nested = project / "nested"
    nested.mkdir(parents=True)
    (project / "webuse.toml").write_text(
        """
[items.pipelines]
default = [
  { type = "jsonl", path = "items.jsonl" },
]
""",
        encoding="utf-8",
    )
    monkeypatch.chdir(nested)

    class ProjectSpider(Spider):
        start_urls = ["https://example.com"]
        extract = {"title": "h1"}
        item_model = SampleItem

    result = ProjectSpider().run(client=FakeClient())

    assert result.items == [{"title": "Home"}]
    assert not (project / "items.jsonl").exists()


def test_project_level_jsonl_pipeline_from_webuse_yaml(tmp_path):
    (tmp_path / "webuse.yaml").write_text(
        """
items:
  pipelines:
    default:
      - type: jsonl
        path: items.jsonl
""",
        encoding="utf-8",
    )

    class ProjectSpider(Spider):
        project_dir = tmp_path
        start_urls = ["https://example.com"]
        extract = {"title": "h1"}
        item_model = SampleItem

    result = ProjectSpider().run(client=FakeClient())
    lines = (tmp_path / "items.jsonl").read_text(encoding="utf-8").splitlines()

    assert result.items == [SampleItem(title="Home")]
    assert lines == ['{"title": "Home", "source": ""}']


def test_spider_pipelines_take_precedence_over_project_config(tmp_path):
    (tmp_path / "webuse.toml").write_text(
        """
[items.pipelines]
default = [
  { type = "jsonl", path = "project.jsonl" },
]
""",
        encoding="utf-8",
    )

    class OverridePipeline(Pipeline):
        def process_item(self, item):
            return item.model_copy(update={"source": "spider"})

    class OverrideSpider(Spider):
        project_dir = tmp_path
        start_urls = ["https://example.com"]
        extract = {"title": "h1"}
        item_model = SampleItem
        pipelines = [OverridePipeline()]

    result = OverrideSpider().run(client=FakeClient())

    assert result.items == [SampleItem(title="Home", source="spider")]
    assert not (tmp_path / "project.jsonl").exists()


def test_project_level_custom_pipeline_imports_from_project_dir(tmp_path):
    (tmp_path / "project_pipelines.py").write_text(
        """
class MarkPipeline:
    def process_item(self, item):
        return item.model_copy(update={"source": "project"})
""",
        encoding="utf-8",
    )
    (tmp_path / "webuse.toml").write_text(
        """
[items.pipelines]
default = [
  { class = "project_pipelines.MarkPipeline" },
]
""",
        encoding="utf-8",
    )

    class ProjectSpider(Spider):
        project_dir = tmp_path
        start_urls = ["https://example.com"]
        extract = {"title": "h1"}
        item_model = SampleItem

    result = ProjectSpider().run(client=FakeClient())

    assert result.items == [SampleItem(title="Home", source="project")]


def test_run_pipeline_override_takes_precedence(tmp_path):
    class ClassPipeline(Pipeline):
        def process_item(self, item):
            return item.model_copy(update={"source": "class"})

    class RunPipeline(Pipeline):
        def process_item(self, item):
            return item.model_copy(update={"source": "run"})

    class OverrideSpider(Spider):
        start_urls = ["https://example.com"]
        extract = {"title": "h1"}
        item_model = SampleItem
        pipelines = [ClassPipeline()]

    result = OverrideSpider().run(client=FakeClient(), pipelines=[RunPipeline()])

    assert result.items == [SampleItem(title="Home", source="run")]


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
