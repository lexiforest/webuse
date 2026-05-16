from pathlib import Path

from webuse.response import Response
from webuse.smart import SmartSelectorStore


HTML = b"""
<html>
  <body>
    <main>
      <article class="product-card">
        <h2>Alpha Gadget</h2>
        <a class="product-link" href="/products/alpha">Open</a>
      </article>
      <article class="product-card">
        <h2>Beta Gadget</h2>
        <a class="product-link" href="/products/beta">Open</a>
      </article>
    </main>
  </body>
</html>
"""


def test_response_css_xpath_and_links():
    response = Response(url="https://example.com/catalog", status_code=200, content=HTML)

    cards = response.css(".product-card")
    assert len(cards) == 2
    assert cards[0].css_first("h2").text() == "Alpha Gadget"

    link = response.xpath_first("//a[@class='product-link']")
    assert link is not None
    assert link.attr("href") == "https://example.com/products/alpha"
    assert response.links() == [
        "https://example.com/products/alpha",
        "https://example.com/products/beta",
    ]


def test_smart_selector_persists_record(tmp_path: Path):
    store = SmartSelectorStore(tmp_path / "selectors.json")
    response = Response(url="https://example.com/catalog", status_code=200, content=HTML)

    match = response.smart("alpha gadget product link", store=store)
    assert match.attr("href") == "https://example.com/products/alpha"

    persisted = store.get("alpha-gadget-product-link")
    assert persisted is not None
    assert persisted.selectors
