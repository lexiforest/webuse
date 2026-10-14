import asyncio

import pytest
from pydantic import BaseModel

from webuse import (
    AsyncSpider,
    ConfigError,
    CrawlRequest,
    ItemPipeline,
    Response,
    Spider,
    acrawl,
    crawl,
)
from webuse.extract import extract_handles_category, extract_items
from webuse.extract.schema import compile_extraction
from webuse.spider.config import SpiderConfig


def test_named_items_select_scopes_and_preserve_metadata():
    class Product(BaseModel):
        title: str

    response = Response(
        url="https://example.com/",
        content=b'<h1>Catalog</h1><article><a href="/one">One</a></article>'
        b'<article><a href="/two">Two</a></article>',
    )
    rules = compile_extraction(
        {
            "default": {
                "products": {
                    "type": "product",
                    "item_model": Product,
                    "item_css": "article",
                    "fields": {"title": "a", "url": {"css_find": "a", "attr": "href"}},
                },
                "page": {
                    "fields": {
                        "title": "h1",
                        "links": {"css": "a", "attr": "href", "all": True},
                    }
                },
                "links": {"item_css": "a", "fields": {"text": "."}},
            }
        }
    )
    items = extract_items(response, rules)
    assert items == [
        {
            "title": "One",
            "url": "https://example.com/one",
            "_type": "product",
            "_item_model": Product,
        },
        {
            "title": "Two",
            "url": "https://example.com/two",
            "_type": "product",
            "_item_model": Product,
        },
        {
            "title": "Catalog",
            "links": ["https://example.com/one", "https://example.com/two"],
            "_type": "page",
        },
        {"text": "One", "_type": "links"},
        {"text": "Two", "_type": "links"},
    ]


@pytest.mark.parametrize(
    "category,item_type",
    [
        (None, "page"),
        ("detail", "product"),
        ("other", "fallback"),
        ("empty", None),
    ],
)
def test_category_selection_and_wildcard(category, item_type):
    rules = compile_extraction(
        {
            "default": {"page": {"fields": {"title": "h1"}}},
            "detail": {"product": {"fields": {"title": "h1"}}},
            "empty": {},
            "*": {"fallback": {"fields": {"title": "h1"}}},
        }
    )
    response = Response(content=b"<h1>Title</h1>")
    response.crawl_request = CrawlRequest(url="https://example.com", category=category)
    assert extract_handles_category(rules, category)
    assert extract_items(response, rules) == (
        [{"title": "Title", "_type": item_type}] if item_type else []
    )


def test_unknown_category_without_fallback_produces_no_items():
    rules = compile_extraction({"default": {"page": {"fields": {"title": "h1"}}}})
    response = Response(content=b"<h1>Title</h1>")
    response.crawl_request = CrawlRequest(url="https://example.com", category="other")
    assert not extract_handles_category(rules, "other")
    assert extract_items(response, rules) == []


def test_category_and_item_names_are_not_inferred_from_reserved_words():
    response = Response(content=b"<h1>Title</h1>")
    response.crawl_request = CrawlRequest(url="https://example.com", category="fields")
    rules = {"fields": {"css": {"fields": {"item_css": "h1"}}}}
    assert extract_items(response, rules) == [{"item_css": "Title", "_type": "css"}]


@pytest.mark.parametrize(
    "spec",
    [
        {"item_css": "article"},
        {"fields": []},
        {"fields": {"title": {}}},
        {"fields": {"title": {"css": "h1", "llm_find": "heading"}}},
        {"fields": {"title": {"css": "h1", "unknown": True}}},
        {"fields": {"title": {"css": "h1", "all": "yes"}}},
        {"fields": {"title": {"llm_find": "heading", "all": True}}},
        {"fields": {"title": {"llm_extract": "heading", "attr": "href"}}},
        {"fields": {"title": {"css": None}}},
        {"fields": {"title": ""}},
        {"fields": {"title": "h1"}, "unknown": True},
    ],
)
def test_invalid_rule_reports_its_category_and_item(spec):
    with pytest.raises(ConfigError, match=r"detail\.product"):
        compile_extraction({"detail": {"product": spec}})


@pytest.mark.parametrize("mode", ["sync", "async", "spider", "async_spider", "yaml"])
def test_invalid_unused_category_fails_before_downloading_or_opening_pipelines(mode):
    class UnusedClient:
        def request(self, *args, **kwargs):
            pytest.fail("invalid configuration must fail before downloading")

    class UnopenedPipeline(ItemPipeline):
        def open_spider(self):
            pytest.fail("invalid configuration must fail before opening pipelines")

    rules = {
        "default": {"page": {"fields": {"title": "h1"}}},
        "unvisited": {"product": {"item_css": "article"}},
    }
    options = {"client": UnusedClient()}
    with pytest.raises(ConfigError, match=r"unvisited\.product\.fields"):
        if mode == "sync":
            crawl("https://example.com", extract=rules, **options)
        elif mode == "async":
            asyncio.run(acrawl("https://example.com", extract=rules, **options))
        else:
            base = AsyncSpider if mode == "async_spider" else Spider
            spider = base(
                start_urls=["https://example.com"],
                extract=rules,
                pipelines=[UnopenedPipeline()],
            )
            if mode == "yaml":
                spider.spider_config = SpiderConfig(
                    pages={
                        category: {"extract": items}
                        for category, items in rules.items()
                    }
                )
            if mode == "async_spider":
                asyncio.run(spider.run(**options))
            else:
                spider.run(**options)
