import asyncio

import pytest

from webuse import AsyncSpider, Response, Spider, acrawl, crawl
from webuse.exceptions import ConfigError
from webuse.models import CrawlRequest, FollowRule


class Client:
    def request(self, method, url, **kwargs):
        return Response(
            url=url,
            content=b'<h1>Title</h1><a href="/products/2#card">next</a>',
        )


class AsyncClient(Client):
    async def request(self, method, url, **kwargs):
        return super().request(method, url, **kwargs)


@pytest.fixture(params=[False, True], ids=["sync", "async"])
def run(request):
    def execute(seeds, **options):
        if request.param:
            return asyncio.run(acrawl(seeds, client=AsyncClient(), **options))
        return crawl(seeds, client=Client(), **options)

    return execute


def page_types(response):
    return {
        "url": response.crawl_request.url,
        "page_type": response.crawl_request.page_type,
    }


def test_page_types_cover_seeds_links_order_and_explicit_requests(run):
    result = run(
        [
            "https://test/",
            "https://test/products/1?source=seed#fragment",
            CrawlRequest(url="https://test/products/3", page_type="manual"),
        ],
        pages={
            "detail": {"url_patterns": [r"/products/\d+(?:\?|$)"]},
            "other": {"url_patterns": [r"/products/"]},
        },
        extract=page_types,
        follow=FollowRule(css="a", source_page_type="default"),
        max_depth=1,
    )
    assert {item["url"]: item["page_type"] for item in result.items} == {
        "https://test/": None,
        "https://test/products/1?source=seed": "detail",
        "https://test/products/2": "detail",
        "https://test/products/3": "manual",
    }


def test_explicit_follow_page_type_overrides_regex(run):
    result = run(
        "https://test/",
        pages={"detail": {"url_patterns": [r"/products/"]}},
        extract=page_types,
        follow=FollowRule(css="a", page_type="manual"),
        max_depth=1,
    )
    assert {item["url"]: item["page_type"] for item in result.items} == {
        "https://test/": None,
        "https://test/products/2": "manual",
    }


def test_parser_follow_requests_are_classified(run):
    def parse(response):
        yield page_types(response)
        if response.crawl_request.page_type is None:
            yield response.follow("/products/2")
            yield response.follow("/products/3", page_type="manual")

    result = run(
        "https://test/",
        extract=parse,
        pages={"detail": {"url_patterns": ["/products/"]}},
        max_depth=1,
    )
    assert {item["url"]: item["page_type"] for item in result.items} == {
        "https://test/": None,
        "https://test/products/2": "detail",
        "https://test/products/3": "manual",
    }


@pytest.mark.parametrize(
    "patterns",
    [
        [],
        {"detail": "pattern"},
        {"detail": {"url_patterns": ["["]}},
        {"detail": {"url_patterns": [""]}},
        {"detail": {"url_patterns": [3]}},
        {"detail": {"url_patterns": "/products/"}},
        {"detail": {"exclude_patterns": ["["]}},
        {"detail": {"exclude_patterns": [""]}},
        {"detail": {"exclude_patterns": None}},
        {"": {"url_patterns": ["."]}},
        {"*": {"url_patterns": ["."]}},
        {"detail": {"url_pattern": ["."]}},
    ],
)
def test_invalid_patterns_fail_before_downloading(run, patterns):
    with pytest.raises(ConfigError, match="pages"):
        run("https://test/", pages=patterns)


@pytest.mark.parametrize("spider_type", [Spider, AsyncSpider])
def test_python_spider_dispatch_and_run_override(spider_type):
    class Pages(spider_type):
        start_urls = ["https://test/", "https://test/products/1"]
        pages = {"wrong": {"url_patterns": ["/products/"]}}

        def parse(self, response):
            return {"handler": "default"}

        def parse_detail(self, response):
            return {"handler": "detail"}

    options = {
        "pages": {
            "detail": {"url_patterns": ["/products/"]},
            "default": {"url_patterns": [r"/$"]},
        }
    }
    if spider_type is AsyncSpider:
        result = asyncio.run(Pages().run(client=AsyncClient(), **options))
    else:
        result = Pages().run(client=Client(), **options)
    assert sorted(item["handler"] for item in result.items) == ["default", "detail"]


@pytest.mark.parametrize("spider_type", [Spider, AsyncSpider])
def test_yaml_page_types_choose_extraction_and_follow_rules(tmp_path, spider_type):
    path = tmp_path / "spider.yaml"
    path.write_text("""
start_urls: https://test/products/1
max_depth: 1
pages:
  detail:
    url_patterns: ['/products/']
    extract:
      book:
        fields:
          title: h1
    follow: a
""")
    spider = spider_type(spider_config_path=path)
    if spider_type is AsyncSpider:
        result = asyncio.run(spider.run(client=AsyncClient()))
    else:
        result = spider.run(client=Client())
    assert result.items == [{"title": "Title", "_type": "book"}] * 2


def test_invalid_spider_regex_fails_before_pipeline_open():
    class Pipeline:
        def open_spider(self):
            pytest.fail("invalid regex must fail before opening pipelines")

        def process_item(self, item):
            return item

    with pytest.raises(ConfigError, match="pages"):
        Spider(pages={"detail": {"url_patterns": ["["]}}, pipelines=[Pipeline()]).run(
            client=Client()
        )


def test_multiple_patterns_exclude_only_the_page_type(run):
    result = run(
        [
            "https://test/products/1",
            "https://test/books/1",
            "https://test/products/ads",
            "https://test/books/ads",
            "https://test/unmatched",
            CrawlRequest(url="https://test/books/ads?explicit", page_type="detail"),
        ],
        pages={
            "detail": {
                "url_patterns": ["/products/", "/books/"],
                "exclude_patterns": ["/products/ads", "/books/ads"],
            },
            "other": {"url_patterns": ["/books/"]},
            "exclude_only": {"exclude_patterns": ["/ads"]},
        },
        extract=page_types,
    )
    assert {item["url"]: item["page_type"] for item in result.items} == {
        "https://test/products/1": "detail",
        "https://test/books/1": "detail",
        "https://test/products/ads": None,
        "https://test/books/ads": "other",
        "https://test/unmatched": None,
    }
    assert result.stats.fetched == 5
    assert result.stats.skipped_rules == 1


@pytest.mark.parametrize(
    "page",
    [
        {"url_patterns": [r"/books/"]},
        {"url_patterns": [r"/products/"], "exclude_patterns": [r"/products/2$"]},
        {"exclude_patterns": [r"/products/2$"]},
    ],
)
@pytest.mark.parametrize("source", ["seed", "follow", "callback"])
def test_explicit_page_type_must_pass_patterns(run, page, source):
    def parse(response):
        yield page_types(response)
        if source == "callback":
            yield response.follow("/products/2#card", page_type="detail")

    seeds = (
        [CrawlRequest(url="https://test/products/2#card", page_type="detail")]
        if source == "seed"
        else "https://test/"
    )
    result = run(
        seeds,
        pages={"detail": page, "other": {"url_patterns": [r"/products/"]}},
        follow=FollowRule(css="a", page_type="detail") if source == "follow" else None,
        extract=parse,
        max_depth=1,
    )
    assert result.visited == (set() if source == "seed" else {"https://test/"})
    assert result.stats.skipped_rules == 1


@pytest.mark.parametrize(
    "page",
    [
        {},
        {"exclude_patterns": ["/ads"]},
        {
            "url_patterns": ["/books/", "/products/"],
            "exclude_patterns": ["/ads"],
        },
    ],
)
def test_explicit_page_type_passes_optional_inclusions_and_exclusions(run, page):
    result = run(
        "https://test/",
        pages={"detail": page},
        follow=FollowRule(css="a", page_type="detail"),
        extract=page_types,
        max_depth=1,
    )
    assert {item["url"]: item["page_type"] for item in result.items} == {
        "https://test/": None,
        "https://test/products/2": "detail",
    }


def test_direct_engine_pages_combine_routing_follow_and_extraction(run):
    result = run(
        "https://test/",
        pages={
            "default": {"follow": "a"},
            "detail": {
                "url_patterns": ["/products/"],
                "extract": {"book": {"fields": {"title": "h1"}}},
            },
        },
        max_depth=1,
    )
    assert result.items == [{"title": "Title", "_type": "book"}]


def test_explicit_engine_options_override_page_rules(run):
    result = run(
        "https://test/",
        pages={
            "default": {"follow": "a", "extract": {"book": {"fields": {"title": "h1"}}}}
        },
        extract=page_types,
        follow=[],
        max_depth=1,
    )
    assert result.items == [{"url": "https://test/", "page_type": None}]
    assert result.stats.fetched == 1


@pytest.mark.parametrize("spider_type", [Spider, AsyncSpider])
def test_python_pages_declare_fields_and_follow_rules(spider_type):
    spider = spider_type(
        start_urls=["https://test/"],
        max_depth=1,
        pages={
            "default": {"follow": "a"},
            "detail": {
                "url_patterns": ["/products/"],
                "extract": {"book": {"fields": {"title": "h1"}}},
            },
        },
    )
    if spider_type is AsyncSpider:
        result = asyncio.run(spider.run(client=AsyncClient()))
    else:
        result = spider.run(client=Client())
    assert result.items == [{"title": "Title", "_type": "book"}]
