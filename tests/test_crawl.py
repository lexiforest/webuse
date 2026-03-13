from getkit.crawl import crawl
from getkit.models import FollowRule
from getkit.response import Response


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
    assert result.stats.followed_links == 2
    assert "https://example.com/page-2" not in result.visited
