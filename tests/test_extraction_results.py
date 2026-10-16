import asyncio

import pytest

import webuse
from crawl_helpers import AsyncFakeClient, FakeClient
from webuse.engine import acrawl, crawl
from webuse.extract import ParseResult, extract_response, normalize_parse_result
from webuse.models import CrawlRequest


@pytest.mark.parametrize("kind", ["dict", "generator", "tuple", "normalized"])
def test_engine_and_spider_share_parse_results(kind):
    def parse(response):
        item = {"title": response.find(css="h1").text()}
        requests = (
            [CrawlRequest(url="/page-1")] if response.crawl_request.depth == 0 else []
        )
        if kind == "dict":
            return item
        if kind == "generator":
            return (entry for entry in [item, *(request.url for request in requests)])
        if kind == "tuple":
            return [item], requests
        return ParseResult([item], requests)

    spider = webuse.Spider(start_urls=["https://example.com"], parse=parse, max_depth=1)
    direct = crawl(
        "https://example.com", extract=parse, max_depth=1, client=FakeClient()
    )
    adapted = spider.run(client=FakeClient())
    expected = [{"title": "Home"}]
    if kind != "dict":
        expected.append({"title": "Page One"})
    assert direct.items == adapted.items == expected
    assert (
        direct.stats.followed_links == adapted.stats.followed_links == len(expected) - 1
    )


@pytest.mark.parametrize("awaitable", [False, True])
def test_async_engine_and_spider_accept_async_iterables(awaitable):
    async def entries(response):
        yield {"title": response.find(css="h1").text()}
        if response.crawl_request.depth == 0:
            yield "/page-1"

    async def deferred(response):
        return entries(response)

    parse = deferred if awaitable else entries

    async def run():
        direct = await acrawl(
            "https://example.com", extract=parse, max_depth=1, client=AsyncFakeClient()
        )
        spider = webuse.AsyncSpider(
            start_urls=["https://example.com"], parse=parse, max_depth=1
        )
        adapted = await spider.run(client=AsyncFakeClient())
        assert (
            direct.items == adapted.items == [{"title": "Home"}, {"title": "Page One"}]
        )
        assert direct.stats.followed_links == adapted.stats.followed_links == 1

    asyncio.run(run())


def test_normalization_empty_and_request_only_results():
    assert normalize_parse_result(None) == ParseResult()
    parsed = normalize_parse_result((None, "/next"))
    assert parsed.items == []
    assert parsed.requests == [CrawlRequest(url="/next")]
    assert normalize_parse_result(parsed) is parsed


def test_sync_adapter_rejects_async_callback_and_closes_coroutine():
    async def parse():
        return {"title": "Home"}

    coroutine = parse()
    with pytest.raises(TypeError, match="Async parse results require"):
        extract_response(None, lambda response: coroutine)
    assert coroutine.cr_frame is None


def test_public_crawl_remains_a_function_after_engine_import():
    assert webuse.crawl is crawl
    assert webuse.acrawl is acrawl
    assert webuse.ItemPipeline is webuse.pipelines.ItemPipeline
