from webuse.crawl import crawl
from webuse.models import FollowRule
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
