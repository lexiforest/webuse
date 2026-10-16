import json
import re as re_module
from types import SimpleNamespace

import pytest
import asyncio
from pydantic import BaseModel
from selectolax.lexbor import LexborHTMLParser

from webuse.extract import extract_items
from webuse.exceptions import LlmSelectionError, ExtractionError
from webuse.extract import Document
from webuse.http import Response
from webuse.extract import LlmSelector, AsyncLlmSelector


class ModelClient:
    def __init__(self, content):
        self.content = content
        self.calls = []
        self.closed = False
        self.chat = SimpleNamespace(completions=self)

    def create(self, **kwargs):
        self.calls.append(kwargs)
        content = self.content(kwargs) if callable(self.content) else self.content
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
        )

    def close(self):
        self.closed = True


def test_selection_is_scoped_ordered_and_reads_real_nodes():
    document = Document(
        '<article><a href="/a">A</a><a href="/b">B</a></article><a>Outside</a>',
        url="https://test/",
    )
    scope = document.find(css="article")

    def select(payload):
        candidates = json.loads(payload["messages"][1]["content"])["candidates"]
        assert all("Outside" not in candidate["text"] for candidate in candidates)
        indices = [c["index"] for c in candidates if c["tag"] == "a"]
        return json.dumps({"indices": [indices[1], indices[0], indices[1]]})

    client = ModelClient(select)
    selector = LlmSelector(client=client, model="test")
    matches = scope.find_all(llm="links", selector=selector)
    assert [m.attr("href") for m in matches] == ["https://test/a", "https://test/b"]
    assert matches[0].element == scope.find(css="a").element
    assert scope.find(llm="links", selector=selector).text() == "A"
    assert len(client.calls) == 2
    assert not client.closed


@pytest.mark.parametrize(
    "options", [{}, {"css": "a", "llm": "link"}, {"css": ""}, {"llm": " "}]
)
def test_invalid_selection_options_fail(options):
    with pytest.raises(ValueError):
        Document("<a>A</a>").find(**options)


@pytest.mark.parametrize(
    "content",
    [
        "not json",
        "null",
        '{"indices": [true]}',
        '{"indices": [-1]}',
        '{"indices": [999]}',
        '{"indices": "0"}',
        '{"indices": [0], "extra": 1}',
    ],
)
def test_invalid_model_selection_is_an_error(content):
    with pytest.raises(LlmSelectionError):
        Document("<p>P</p>").find(
            llm="p", selector=LlmSelector(client=ModelClient(content))
        )


def test_absent_matches_are_consistent_and_css_never_calls_model(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("CSS must not invoke a model")

    monkeypatch.setattr("webuse.extract.resolver.openai_defaults", forbidden)
    document = Document("<p>P</p>")
    assert document.find(css="a") is None
    assert document.find_all(css="a") == []
    monkeypatch.undo()
    selector = LlmSelector(client=ModelClient('{"indices": []}'))
    assert document.find(llm="missing", selector=selector) is None
    assert document.find_all(llm="missing", selector=selector) == []
    with pytest.raises(Exception):
        document.find(css="[")


class Product(BaseModel):
    title: str
    price: float


def test_structured_schema_controls_shape_and_is_validated():
    document = Document("<h1>Book</h1><p>12.50</p>")
    client = ModelClient('{"title":"Book","price":12.5}')
    result = document.llm_extract("product", schema=Product, client=client)
    assert result == Product(title="Book", price=12.5)
    assert document._tree is None
    payload = json.loads(client.calls[0]["messages"][1]["content"])
    assert payload["schema"]["properties"]["price"]["type"] == "number"
    client.content = '[{"title":"Book","price":12.5}]'
    assert document.llm_extract("products", schema=list[Product], client=client) == [
        result
    ]
    client.content = '"12.50"'
    with pytest.raises(ExtractionError):
        document.llm_extract("price", schema=float, client=client)
    client.content = '{"price": "bad"}'
    with pytest.raises(ExtractionError):
        document.llm_extract("product", schema=Product, client=client)
    assert not client.closed


@pytest.mark.parametrize(
    "content", ["plain text", "```json\n42\n```", "NaN", '"42"', "null"]
)
def test_structured_extraction_does_not_coerce_invalid_output(content):
    with pytest.raises(ExtractionError):
        Document("<p>42</p>").llm_extract(
            "number",
            schema={"type": "number"},
            client=ModelClient(content),
        )


def test_scoped_structured_extraction_and_options():
    scope = Document("<article>Inside</article><p>Outside</p>").find(css="article")
    client = ModelClient('"Inside"')
    assert (
        scope.llm_extract(
            "text",
            schema=str,
            client=client,
            model="test",
            temperature=0.2,
            max_tokens=42,
        )
        == "Inside"
    )
    call = client.calls[0]
    assert "Outside" not in call["messages"][1]["content"]
    assert call["model"] == "test" and call["max_tokens"] == 42
    assert call["temperature"] == 0.2


def test_model_transport_errors_propagate_and_owned_clients_close(monkeypatch):
    def fail(payload):
        raise RuntimeError("provider unavailable")

    for module, operation in [
        ("resolver", lambda doc: doc.find(llm="p")),
        ("structured", lambda doc: doc.llm_extract("p", schema=str)),
    ]:
        client = ModelClient(fail)
        monkeypatch.setattr(
            f"webuse.extract.{module}.create_openai_client", lambda **kw: client
        )
        with pytest.raises(RuntimeError, match="provider unavailable"):
            operation(Document("<p>P</p>"))
        assert client.closed


def test_declarative_selection_and_structured_records_share_scopes(monkeypatch):
    def output(payload):
        data = json.loads(payload["messages"][1]["content"])
        if "candidates" in data:
            return json.dumps(
                {"indices": [c["index"] for c in data["candidates"] if c["tag"] == "a"]}
            )
        return '{"title":"Book","price":12.5}'

    client = ModelClient(output)
    for module in ("resolver", "structured"):
        monkeypatch.setattr(
            f"webuse.extract.{module}.create_openai_client", lambda **kw: client
        )
    doc = Document('<article><a href="/book">Book</a></article>', url="https://test/")
    rules = {
        "default": {
            "link": {
                "item_css": "article",
                "fields": {"url": {"llm": "product link", "attr": "href"}},
            },
            "product": {
                "item_css": "article",
                "llm_extract": "product",
                "schema": Product,
            },
        }
    }
    assert extract_items(doc, rules) == [
        {"url": "https://test/book", "_type": "link"},
        {"title": "Book", "price": 12.5, "_type": "product"},
    ]
    assert len(client.calls) == 2


def test_async_selection_and_extraction_on_elements():
    class AsyncClient(ModelClient):
        async def create(self, **kwargs):
            return super().create(**kwargs)

    async def run():
        scope = Document("<article><p>P</p></article>").find(css="article")
        client = AsyncClient('{"indices": [1]}')
        selector = AsyncLlmSelector(client=client)
        assert (await scope.afind(llm="p", selector=selector)).text() == "P"
        assert len(await scope.afind_all(llm="p", selector=selector)) == 1
        assert (await scope.afind(css="p")).text() == "P"
        client.content = '"P"'
        assert await scope.allm_extract("p", schema=str, client=client) == "P"
        assert not client.closed

    asyncio.run(run())


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


def test_response_css_and_links():
    response = Response(
        url="https://example.com/catalog", status_code=200, content=HTML
    )

    cards = response.find_all(css=".product-card")
    assert len(cards) == 2
    assert cards[0].find(css="h2").text() == "Alpha Gadget"

    link = response.find(css="a.product-link")
    assert link is not None
    assert link.attr("href") == "https://example.com/products/alpha"
    assert response.links() == [
        "https://example.com/products/alpha",
        "https://example.com/products/beta",
    ]


def test_response_re_and_re_first_do_not_build_tree():
    response = Response(
        url="https://example.com/catalog", status_code=200, content=HTML
    )

    assert response.re(r"/products/([a-z]+)") == ["alpha", "beta"]
    assert response.re_first(r"/products/([a-z]+)") == "alpha"
    assert response.re_first(r"missing", default="fallback") == "fallback"
    assert response.re_first(r"alpha gadget", flags=re_module.IGNORECASE) == (
        "Alpha Gadget"
    )
    assert response._tree is None


def test_response_re_returns_tuples_for_multiple_capture_groups():
    response = Response(
        url="https://example.com/catalog",
        status_code=200,
        content=b"<a href='/products/alpha'>Alpha</a>",
    )

    assert response.re(r"href='([^']+)'>([^<]+)") == [("/products/alpha", "Alpha")]
    assert response.re_first(r"href='([^']+)'>([^<]+)") == (
        "/products/alpha",
        "Alpha",
    )


def test_element_re_matches_element_html():
    response = Response(
        url="https://example.com/catalog", status_code=200, content=HTML
    )
    card = response.find(css=".product-card")
    assert card is not None

    assert card.re(r"/products/([a-z]+)") == ["alpha"]
    assert card.re_first(r"<h2>([^<]+)</h2>") == "Alpha Gadget"


def test_document_builds_tree_lazily_on_selector_use():
    response = Response(
        url="https://example.com/catalog", status_code=200, content=HTML
    )

    assert response._tree is None
    assert response.find(css="article") is not None
    assert response._tree is not None


@pytest.mark.parametrize("content", ["<h1>caf\u00e9</h1>", b"<h1>caf\xc3\xa9</h1>"])
def test_document_text_and_url_do_not_build_tree(content):
    document = Document(content, url="https://example.com/page")
    assert document.text == "<h1>caf\u00e9</h1>"
    assert document.url == "https://example.com/page"
    assert document.re_first(r"<h1>(.*?)</h1>") == "caf\u00e9"
    assert document._tree is None
    assert document.text_content() == "caf\u00e9"


def test_response_parsing_uses_current_native_url():
    response = Response(content=b'<a href="next">Next</a>')
    response.url = "https://example.com/final/page"
    assert response.text == '<a href="next">Next</a>'
    assert response._tree is None
    assert response.links() == ["https://example.com/final/next"]


def test_lexbor_handles_empty_and_malformed_html():
    empty = Document("")
    assert empty.find_all(css="a") == []
    assert empty.find(css="a") is None
    assert empty.text_content() == ""
    document = Document("<p>one<p>two")
    assert [node.text() for node in document.find_all(css="p")] == ["one", "two"]
    assert isinstance(document._tree, LexborHTMLParser)
    assert [node.tag for node in document.iter_elements()] == [
        "html",
        "head",
        "body",
        "p",
        "p",
    ]


def test_css_scoping_text_attributes_and_serialization():
    document = Document(
        "<article><p> A <b>B</b> C </p>tail<input disabled></article>"
        "<article><p>outside</p></article>"
    )
    article = document.find(css="article:has(input[disabled])")
    paragraph = article.find(css="p")
    assert [node.text() for node in article.find_all(css="p")] == ["A B C"]
    assert paragraph.text(separator="|") == "A|B|C"
    assert paragraph.text(separator="", strip=False) == " A B C "
    assert paragraph.html() == "<p> A <b>B</b> C </p>"
    assert article.find(css="input").attr("disabled") == ""
    assert article.find(css="input").attr("missing", "fallback") == "fallback"
    assert document.text_content() == "A B C tail outside"


def test_links_resolve_against_first_html_base():
    document = Document(
        '<base href="../assets/"><base href="/ignored/">'
        '<a href="item" data="value">Item</a><img src="image.png">'
        '<object data="file.pdf"></object>',
        url="https://example.com/catalog/page",
    )
    assert document.links() == ["https://example.com/assets/item"]
    assert document.find(css="a").attr("href") == "https://example.com/assets/item"
    assert (
        document.find(css="img").attr("src") == "https://example.com/assets/image.png"
    )
    assert document.find(css="base").attr("href") == "https://example.com/assets/"
    assert document.find(css="a").attr("data") == "value"
    assert (
        document.find(css="object").attr("data")
        == "https://example.com/assets/file.pdf"
    )
