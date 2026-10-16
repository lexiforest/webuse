import asyncio

from webuse.engine import (
    acrawl,
)
from webuse.models import FollowRule
from webuse.http import Response

from crawl_helpers import (
    AsyncRobotsClient,
)


def test_request_limit_caps_seeds_with_concurrent_workers():
    requests = []

    class Client:
        async def request(self, method, url, **kwargs):
            requests.append(url)
            await asyncio.sleep(0)
            return Response(url=url, status_code=200, content=b"<h1>Page</h1>")

    result = asyncio.run(
        acrawl(
            [f"https://example.com/{index}" for index in range(10)],
            client=Client(),
            max_requests=2,
            concurrency=5,
        )
    )
    assert result.stats.queued == 2
    assert len(requests) == 2


def test_acrawl_follow_rule_assigns_request_page_type():
    pages = {
        "https://example.com/": b"""
        <html><body>
          <a class="detail" href="/detail">Detail</a>
          <h1>Listing</h1>
        </body></html>
        """,
        "https://example.com/detail": b"<html><body><h1>Detail</h1></body></html>",
    }

    class PageTypeClient:
        async def request(self, method, url, **kwargs):
            _ = (method, kwargs)
            return Response(url=url, status_code=200, content=pages[url])

        async def __aexit__(self, exc_type, exc, tb):
            return None

    def parse(response):
        return {
            "title": response.find(css="h1").text(),
            "page_type": response.crawl_request.page_type,
        }

    async def run_crawl():
        return await acrawl(
            "https://example.com/",
            client=PageTypeClient(),
            follow=FollowRule(css="a.detail", page_type="detail"),
            extract=parse,
            max_depth=1,
        )

    result = asyncio.run(run_crawl())

    assert result.items == [
        {"title": "Listing", "page_type": None},
        {"title": "Detail", "page_type": "detail"},
    ]


def test_acrawl_follow_rule_can_be_limited_to_source_page_type():
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

    class PageTypeClient:
        async def request(self, method, url, **kwargs):
            _ = (method, kwargs)
            return Response(url=url, status_code=200, content=pages[url])

        async def __aexit__(self, exc_type, exc, tb):
            return None

    async def run_crawl():
        return await acrawl(
            "https://example.com/",
            client=PageTypeClient(),
            follow=FollowRule(
                css="a.detail", source_page_type="default", page_type="detail"
            ),
            extract=lambda response: {"title": response.find(css="h1").text()},
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
            extract={"default": {"page": {"fields": {"title": "h1"}}}},
            max_depth=1,
            robots_txt=True,
            user_agent="webuse-test",
        )

    result = asyncio.run(run_crawl())

    assert result.items == [
        {"title": "Home", "_type": "page"},
        {"title": "Allowed", "_type": "page"},
    ]
    assert result.stats.skipped_robots == 1
    assert "https://example.com/private" not in result.visited
    assert client.requests.count("https://example.com/robots.txt") == 1
