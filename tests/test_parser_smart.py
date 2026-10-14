import json
import re as re_module
from types import SimpleNamespace

import pytest
from selectolax.lexbor import LexborHTMLParser

from webuse.extract import extract_items
from webuse.exceptions import ConfigError, SmartSelectorError
from webuse.extract import Document
from webuse.http import Response
from webuse.extract import LlmSmartResolver


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

    cards = response.css(".product-card")
    assert len(cards) == 2
    assert cards[0].css_find("h2").text() == "Alpha Gadget"

    link = response.css_find("a.product-link")
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
    card = response.css_find(".product-card")
    assert card is not None

    assert card.re(r"/products/([a-z]+)") == ["alpha"]
    assert card.re_first(r"<h2>([^<]+)</h2>") == "Alpha Gadget"


def test_smart_passes_prompt_and_text_to_model():
    captured = {}

    class FakeCompletions:
        def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(message=SimpleNamespace(content='["Alpha Gadget"]'))
                ]
            )

    client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))
    response = Response(
        url="https://example.com/catalog", status_code=200, content=HTML
    )

    result = response.llm_extract(
        "Which product is first?", model="test-model", client=client
    )

    assert result == ["Alpha Gadget"]
    assert response._tree is None
    assert captured["model"] == "test-model"
    assert captured["temperature"] == 0
    assert "array containing all matches" in captured["messages"][0]["content"]
    assert captured["messages"][1]["content"].startswith(
        "Prompt:\nWhich product is first?"
    )
    assert "Alpha Gadget" in captured["messages"][1]["content"]
    assert "<article" in captured["messages"][1]["content"]


def test_smart_first_returns_first_model_match():
    class FakeCompletions:
        def create(self, **kwargs):
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content='["Alpha", "Beta"]')
                    )
                ]
            )

    client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))
    response = Response(
        url="https://example.com/catalog", status_code=200, content=HTML
    )

    assert response.llm_extract_first("First title", client=client) == "Alpha"


def test_smart_includes_html_attributes_without_building_tree():
    captured = {}

    class FakeCompletions:
        def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(message=SimpleNamespace(content="Alpha Full Title"))
                ]
            )

    client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))
    response = Response(
        url="https://example.com/catalog",
        status_code=200,
        content=b'<a title="Alpha Full Title">Alpha...</a>',
    )

    result = response.llm_extract_first("Extract title attribute", client=client)

    assert result == "Alpha Full Title"
    assert response._tree is None
    assert "first matching JSON value" in captured["messages"][0]["content"]
    assert 'title="Alpha Full Title"' in captured["messages"][1]["content"]


def test_smart_can_limit_text_length():
    captured = {}

    class FakeCompletions:
        def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))]
            )

    client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))
    response = Response(
        url="https://example.com/catalog", status_code=200, content=b"<p>abcdef</p>"
    )

    response.llm_extract("Read text", client=client, max_chars=3)

    assert (
        "Document text:\nabc\n\nDocument HTML:\n<p>"
        in captured["messages"][1]["content"]
    )


def test_document_builds_tree_lazily_on_selector_use():
    response = Response(
        url="https://example.com/catalog", status_code=200, content=HTML
    )

    assert response._tree is None
    assert response.css_find("article") is not None
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


def test_document_smart_methods_extract_without_http_or_building_tree():
    calls = []

    class Completions:
        def create(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content='["Alpha"]'))]
            )

    document = Document(b"<h1>Alpha</h1>")
    client = SimpleNamespace(chat=SimpleNamespace(completions=Completions()))
    assert document.llm_extract("titles", client=client) == ["Alpha"]
    assert document.llm_extract_first("title", client=client) == "Alpha"
    assert document.llm_extract_many(["titles", "headings"], client=client) == {
        "titles": ["Alpha"],
        "headings": ["Alpha"],
    }
    assert len(calls) == 4
    assert "array containing all matches" in calls[0]["messages"][0]["content"]
    assert "first matching JSON value" in calls[1]["messages"][0]["content"]
    assert "Document HTML:\n<h1>Alpha</h1>" in calls[0]["messages"][1]["content"]
    assert document._tree is None


@pytest.mark.parametrize("method", ["llm_extract", "llm_extract_first", "llm_extract_many"])
def test_smart_methods_forward_extraction_options(method):
    captured = []

    class Completions:
        def create(self, **kwargs):
            captured.append(kwargs)
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content='["ok"]'))]
            )

    document = Document("<h1>Alpha</h1>")
    client = SimpleNamespace(chat=SimpleNamespace(completions=Completions()))
    prompts = ["title", "heading"] if method == "llm_extract_many" else "title"
    getattr(document, method)(
        prompts,
        client=client,
        model="custom-model",
        system_prompt="Custom instructions",
        temperature=0.25,
        max_chars=3,
        max_tokens=42,
    )
    assert len(captured) == (2 if method == "llm_extract_many" else 1)
    for call in captured:
        assert call["model"] == "custom-model"
        assert call["temperature"] == 0.25
        assert call["max_tokens"] == 42
        assert call["messages"][0]["content"] == "Custom instructions"
        assert (
            "Document text:\nAlp\n\nDocument HTML:\n<h1"
            in call["messages"][1]["content"]
        )
    assert document._tree is None


def test_crawler_separates_value_extraction_and_item_element_lookup(monkeypatch):
    calls = []

    class Completions:
        def create(self, **kwargs):
            calls.append(kwargs)
            html = kwargs["messages"][1]["content"]
            value = "Alpha" if "Alpha" in html else "Beta"
            if html.startswith("{"):
                candidates = json.loads(html)["candidates"]
                links = [candidate for candidate in candidates if candidate["tag"] == "a"]
                assert len(links) == 1
                content = json.dumps({"index": links[0]["index"]})
            else:
                content = json.dumps(value)
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
            )

    client = SimpleNamespace(chat=SimpleNamespace(completions=Completions()))
    monkeypatch.setattr(
        "webuse.extract.smart.create_openai_client", lambda **kwargs: client
    )
    monkeypatch.setattr(
        "webuse.extract.resolver.create_openai_client", lambda **kwargs: client
    )
    document = Document(
        '<article><a class="product" href="/alpha">Alpha</a></article>'
        '<article><a class="product" href="/beta">Beta</a></article>',
        url="https://example.com",
    )
    items = extract_items(
        document,
        {
            "default": {
                "product": {
                    "item_css": "article",
                    "fields": {
                        "title": {"llm_extract": "Extract the title"},
                        "link": {"llm_find": "product link", "attr": "href"},
                    },
                },
            },
        },
    )
    assert items == [
        {"title": "Alpha", "link": "https://example.com/alpha", "_type": "product"},
        {"title": "Beta", "link": "https://example.com/beta", "_type": "product"},
    ]
    assert len(calls) == 4


def test_crawler_rejects_selector_options_on_value_extraction():
    with pytest.raises(ConfigError, match="use llm_find"):
        extract_items(
            Document("<a>Buy</a>"),
            {"default": {"product": {"fields": {
                "link": {"llm_extract": "buy link", "attr": "href"}
            }}}},
        )


def test_element_lookup_uses_current_document_without_writing_files(tmp_path, monkeypatch):
    calls = []

    class Completions:
        def create(self, **kwargs):
            payload = json.loads(kwargs["messages"][1]["content"])
            calls.append(payload["url"])
            selected = next(
                c for c in payload["candidates"] if c["attrs"].get("aria-label") == "buy"
            )
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
                content=json.dumps({"index": selected["index"]})
            ))])

    client = SimpleNamespace(chat=SimpleNamespace(completions=Completions()))
    resolver = LlmSmartResolver(client=client)
    monkeypatch.chdir(tmp_path)
    for host, css_class in [("one.example", "action"), ("two.example", "purchase")]:
        document = Document(
            f'<button class="{css_class}">Cancel</button>'
            f'<button class="{css_class}" aria-label="buy">Buy</button>',
            url=f"https://{host}/",
        )
        for _ in range(2):
            assert document.llm_find("buy", resolver=resolver).text() == "Buy"
    assert calls == ["https://one.example/"] * 2 + ["https://two.example/"] * 2
    assert list(tmp_path.iterdir()) == []


def test_llm_find_always_calls_model_without_keyword_filtering(monkeypatch):
    calls = []

    class Completions:
        def create(self, **kwargs):
            payload = json.loads(kwargs["messages"][1]["content"])
            calls.append(payload)
            candidates = payload["candidates"]
            assert len(candidates) > 20
            selected = next(c for c in candidates if c["attrs"].get("id") == "target")
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(
                    content=json.dumps({"index": selected["index"]})
                ))]
            )

    client = SimpleNamespace(chat=SimpleNamespace(completions=Completions()))
    monkeypatch.setattr("webuse.extract.resolver.create_openai_client", lambda **kw: client)
    document = Document('<button>Buy</button>' * 30 + '<button id="target">Proceed</button>')
    for _ in range(2):
        assert document.llm_find("buy").text() == "Proceed"
    assert len(calls) == 2


def test_css_find_selects_first_match_and_returns_none_without_a_model(monkeypatch):
    def unexpected_resolver(*args, **kwargs):
        raise AssertionError("CSS lookup must not construct a resolver")

    monkeypatch.setattr("webuse.extract.resolver.LlmSmartResolver", unexpected_resolver)
    document = Document('<a>Outside</a><article><a>First</a><a>Second</a></article>')
    assert document.css_find("a").text() == "Outside"
    article = document.css_find("article")
    assert article.css_find("a").text() == "First"
    assert article.css_find("button") is None
    assert document.css_find("button") is None


@pytest.mark.parametrize("content", ["null", '{"index": -1}', '{"index": 999}'])
def test_llm_find_raises_when_model_selects_no_element(content):
    class Completions:
        def create(self, **kwargs):
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
            )

    client = SimpleNamespace(chat=SimpleNamespace(completions=Completions()))
    with pytest.raises(SmartSelectorError, match="buy"):
        Document("<button>Buy</button>").llm_find(
            "buy", resolver=LlmSmartResolver(client=client)
        )


def test_llm_find_uses_supplied_resolver():
    calls = []

    class Completions:
        def create(self, **kwargs):
            payload = json.loads(kwargs["messages"][1]["content"])
            assert payload["prompt"] == "unmatched prompt"
            calls.append(kwargs)
            selected = next(c for c in payload["candidates"] if c["tag"] == "button")
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
                content=json.dumps({"index": selected["index"]})
            ))])

    html = b"""
    <html>
      <body>
        <button data-answer="yes">Choose</button>
      </body>
    </html>
    """
    client = SimpleNamespace(chat=SimpleNamespace(completions=Completions()))
    resolver = LlmSmartResolver(model="custom-model", client=client)
    response = Response(
        url="https://example.com/actions", status_code=200, content=html
    )

    match = response.llm_find(
        "unmatched prompt",
        resolver=resolver,
    )

    assert len(calls) == 1
    assert calls[0]["model"] == "custom-model"
    assert match.attr("data-answer") == "yes"


def test_llm_smart_resolver_accepts_compatible_client():
    captured = {}

    class FakeCompletions:
        def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(message=SimpleNamespace(content='{"index": 1}'))
                ]
            )

    client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))
    resolver = LlmSmartResolver(model="test-model", client=client)
    response = Response(
        url="https://example.com/actions",
        status_code=200,
        content=b"<button>First</button><button>Second</button>",
    )

    match = resolver.resolve("second button", response, response.css("button"))

    assert match is not None
    assert match.text() == "Second"
    assert captured["model"] == "test-model"


def test_lexbor_handles_empty_and_malformed_html():
    empty = Document("")
    assert empty.css("a") == []
    assert empty.css_find("a") is None
    assert empty.text_content() == ""
    document = Document("<p>one<p>two")
    assert [node.text() for node in document.css("p")] == ["one", "two"]
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
    article = document.css_find("article:has(input[disabled])")
    paragraph = article.css_find("p")
    assert [node.text() for node in article.css("p")] == ["A B C"]
    assert paragraph.text(separator="|") == "A|B|C"
    assert paragraph.text(separator="", strip=False) == " A B C "
    assert paragraph.html() == "<p> A <b>B</b> C </p>"
    assert article.css_find("input").attr("disabled") == ""
    assert article.css_find("input").attr("missing", "fallback") == "fallback"
    assert document.text_content() == "A B C tail outside"


def test_links_resolve_against_first_html_base():
    document = Document(
        '<base href="../assets/"><base href="/ignored/">'
        '<a href="item" data="value">Item</a><img src="image.png">'
        '<object data="file.pdf"></object>',
        url="https://example.com/catalog/page",
    )
    assert document.links() == ["https://example.com/assets/item"]
    assert document.css_find("a").attr("href") == "https://example.com/assets/item"
    assert (
        document.css_find("img").attr("src") == "https://example.com/assets/image.png"
    )
    assert document.css_find("base").attr("href") == "https://example.com/assets/"
    assert document.css_find("a").attr("data") == "value"
    assert (
        document.css_find("object").attr("data")
        == "https://example.com/assets/file.pdf"
    )
