import re as re_module
from pathlib import Path
from types import SimpleNamespace

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


def test_response_css_xpath_and_links():
    response = Response(
        url="https://example.com/catalog", status_code=200, content=HTML
    )

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


def test_smart_selector_persists_record(tmp_path: Path):
    store = SmartSelectorStore(tmp_path / "selectors.json")
    response = Response(
        url="https://example.com/catalog", status_code=200, content=HTML
    )

    match = response.smart_first(
        "alpha gadget product link", translate_xpath=True, store=store
    )
    assert match.attr("href") == "https://example.com/products/alpha"

    persisted = store.get("alpha-gadget-product-link")
    assert persisted is not None
    assert persisted.selectors
    assert persisted.xpath_selectors


def test_smart_selector_uses_deterministic_match_before_resolver(tmp_path: Path):
    class FailingResolver:
        def resolve(self, prompt, document, candidates):
            raise AssertionError("resolver should not be called")

    store = SmartSelectorStore(tmp_path / "selectors.json")
    response = Response(
        url="https://example.com/catalog", status_code=200, content=HTML
    )

    matches = response.smart(
        "alpha gadget product link", translate_xpath=True, store=store
    )
    assert len(matches) == 1

    match = response.smart_first(
        "alpha gadget product link",
        translate_xpath=True,
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

    match = response.smart_first(
        "unmatched prompt",
        translate_xpath=True,
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
