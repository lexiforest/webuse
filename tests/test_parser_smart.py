import re as re_module
from pathlib import Path
from types import SimpleNamespace

import pytest
from selectolax.lexbor import LexborHTMLParser

from webuse import FollowRule, cli
from webuse.crawl.utils import extract_items, follow_rule_from_config
from webuse.exceptions import ConfigError
from webuse.parser import Document
from webuse.response import Response
from webuse.smart import LlmSmartResolver, SmartSelectorStore


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
    assert cards[0].css_first("h2").text() == "Alpha Gadget"

    link = response.css_first("a.product-link")
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
    card = response.css_first(".product-card")
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

    result = response.smart(
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

    assert response.smart_first("First title", client=client) == "Alpha"


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

    result = response.smart_first("Extract title attribute", client=client)

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

    response.smart("Read text", client=client, max_chars=3)

    assert (
        "Document text:\nabc\n\nDocument HTML:\n<p>"
        in captured["messages"][1]["content"]
    )


def test_document_builds_tree_lazily_on_selector_use():
    response = Response(
        url="https://example.com/catalog", status_code=200, content=HTML
    )

    assert response._tree is None
    assert response.css_first("article") is not None
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
    assert document.smart("titles", client=client) == ["Alpha"]
    assert document.smart_first("title", client=client) == "Alpha"
    assert document.smart_all(["titles", "headings"], client=client) == {
        "titles": ["Alpha"],
        "headings": ["Alpha"],
    }
    assert len(calls) == 4
    assert "array containing all matches" in calls[0]["messages"][0]["content"]
    assert "first matching JSON value" in calls[1]["messages"][0]["content"]
    assert "Document HTML:\n<h1>Alpha</h1>" in calls[0]["messages"][1]["content"]
    assert document._tree is None


@pytest.mark.parametrize("method", ["smart", "smart_first", "smart_all"])
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
    prompts = ["title", "heading"] if method == "smart_all" else "title"
    getattr(document, method)(
        prompts,
        client=client,
        model="custom-model",
        system_prompt="Custom instructions",
        temperature=0.25,
        max_chars=3,
        max_tokens=42,
    )
    assert len(captured) == (2 if method == "smart_all" else 1)
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


def test_document_finds_elements_and_reuses_local_selectors(tmp_path):
    store = SmartSelectorStore(tmp_path / "selectors.json")
    document = Document(
        '<a id="product" href="/alpha">Alpha</a>', url="https://example.com"
    )
    prompt = "alpha product link"
    match = document.find_element(prompt, store=store)
    assert match.attr("href") == "https://example.com/alpha"
    assert store.get("alpha-product-link").selectors == ["#product"]

    reloaded = Document('<a id="product" href="/beta">Beta</a>')
    store = SmartSelectorStore(store.path)
    assert reloaded.find_element(prompt, store=store).text() == "Beta"


@pytest.mark.parametrize("method", ["smart", "smart_first", "smart_all"])
def test_smart_methods_reject_removed_translation_switch(method):
    document = Document("<h1>Alpha</h1>")
    prompt = ["title"] if method == "smart_all" else "title"
    with pytest.raises(TypeError, match="find_element"):
        getattr(document, method)(prompt, translate_css=True)


def test_crawler_separates_value_extraction_and_item_element_lookup(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("WEBUSE_SELECTOR_STORE", str(tmp_path / "selectors.json"))
    calls = []

    class Completions:
        def create(self, **kwargs):
            calls.append(kwargs)
            html = kwargs["messages"][1]["content"]
            value = "Alpha" if "Alpha" in html else "Beta"
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=f'"{value}"'))]
            )

    client = SimpleNamespace(chat=SimpleNamespace(completions=Completions()))
    monkeypatch.setattr(
        "webuse.smart.extract.create_openai_client", lambda **kwargs: client
    )
    document = Document(
        '<article><a class="product" href="/alpha">Alpha</a></article>'
        '<article><a class="product" href="/beta">Beta</a></article>',
        url="https://example.com",
    )
    items = extract_items(
        document,
        {
            "item_css": "article",
            "fields": {
                "title": {"smart": "Extract the title"},
                "link": {"find_element": "product link", "attr": "href"},
            },
        },
    )
    assert items == [
        {"title": "Alpha", "link": "https://example.com/alpha"},
        {"title": "Beta", "link": "https://example.com/beta"},
    ]
    assert len(calls) == 2


def test_crawler_rejects_selector_options_on_value_extraction():
    with pytest.raises(ConfigError, match="use find_element"):
        extract_items(
            Document("<a>Buy</a>"), {"link": {"smart": "buy link", "attr": "href"}}
        )


def test_smart_selector_persists_record(tmp_path: Path):
    store = SmartSelectorStore(tmp_path / "selectors.json")
    response = Response(
        url="https://example.com/catalog", status_code=200, content=HTML
    )

    match = response.find_element("alpha gadget product link", store=store)
    assert match.attr("href") == "https://example.com/products/alpha"

    persisted = store.get("alpha-gadget-product-link")
    assert persisted is not None
    assert persisted.selectors
    assert set(persisted.model_dump()) == {"key", "prompt", "selectors"}


def test_smart_selector_uses_deterministic_match_before_resolver(tmp_path: Path):
    class FailingResolver:
        def resolve(self, prompt, document, candidates):
            raise AssertionError("resolver should not be called")

    store = SmartSelectorStore(tmp_path / "selectors.json")
    response = Response(
        url="https://example.com/catalog", status_code=200, content=HTML
    )

    first_match = response.find_element("alpha gadget product link", store=store)
    assert first_match.attr("href") == "https://example.com/products/alpha"

    match = response.find_element(
        "alpha gadget product link",
        store=store,
        use_llm=True,
        resolver=FailingResolver(),
    )

    assert match.attr("href") == "https://example.com/products/alpha"


def test_smart_selector_uses_resolver_fallback(tmp_path: Path):
    class FakeResolver:
        called = False

        def resolve(self, prompt, document, candidates):
            self.called = True
            for candidate in candidates:
                if candidate.attr("data-answer") == "yes":
                    return candidate
            return None

    html = b"""
    <html>
      <body>
        <button data-answer="yes">Choose</button>
      </body>
    </html>
    """
    resolver = FakeResolver()
    store = SmartSelectorStore(tmp_path / "selectors.json")
    response = Response(
        url="https://example.com/actions", status_code=200, content=html
    )

    match = response.find_element(
        "unmatched prompt",
        store=store,
        use_llm=True,
        resolver=resolver,
    )

    assert resolver.called
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
    assert empty.css_first("a") is None
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
    article = document.css_first("article:has(input[disabled])")
    paragraph = article.css_first("p")
    assert [node.text() for node in article.css("p")] == ["A B C"]
    assert paragraph.text(separator="|") == "A|B|C"
    assert paragraph.text(separator="", strip=False) == " A B C "
    assert paragraph.html() == "<p> A <b>B</b> C </p>"
    assert article.css_first("input").attr("disabled") == ""
    assert article.css_first("input").attr("missing", "fallback") == "fallback"
    assert document.text_content() == "A B C tail outside"


def test_links_resolve_against_first_html_base():
    document = Document(
        '<base href="../assets/"><base href="/ignored/">'
        '<a href="item" data="value">Item</a><img src="image.png">'
        '<object data="file.pdf"></object>',
        url="https://example.com/catalog/page",
    )
    assert document.links() == ["https://example.com/assets/item"]
    assert document.css_first("a").attr("href") == "https://example.com/assets/item"
    assert (
        document.css_first("img").attr("src") == "https://example.com/assets/image.png"
    )
    assert document.css_first("base").attr("href") == "https://example.com/assets/"
    assert document.css_first("a").attr("data") == "value"
    assert (
        document.css_first("object").attr("data")
        == "https://example.com/assets/file.pdf"
    )


@pytest.mark.parametrize(
    "extract",
    [
        {"title": {"xpath": "//h1"}},
        {"fields": {"title": {"xpath": "//h1"}}},
        {"item_xpath": "//article", "fields": {"title": "h1"}},
    ],
)
def test_xpath_extraction_configs_are_rejected(extract):
    with pytest.raises(ConfigError, match="no longer supported"):
        extract_items(Response(content=b"<h1>Title</h1>"), extract)


def test_xpath_follow_rules_are_rejected():
    with pytest.raises(ConfigError, match="XPath"):
        follow_rule_from_config({"xpath": "//a"})
    with pytest.raises(ValueError, match="xpath"):
        FollowRule(xpath="//a")


@pytest.mark.parametrize(
    "arguments",
    [
        ["fetch", "https://example.com", "--xpath", "//h1"],
        ["crawl", "https://example.com", "--follow-xpath", "//a"],
        ["fetch", "https://example.com", "--translate-xpath"],
    ],
)
def test_xpath_cli_flags_are_rejected(arguments):
    with pytest.raises(SystemExit) as error:
        cli.build_parser().parse_args(arguments)
    assert error.value.code == 2
