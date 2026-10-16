import json
from pathlib import Path

import pytest

from webuse.extract.parser import Document


CASES = json.loads(
    (
        Path(__file__).resolve().parents[1] / "crates/webuse/tests/fixtures/urls.json"
    ).read_text()
)


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["html"])
def test_shared_url_resolution(case):
    document = Document(case["html"], url="https://example.com/catalog/page")
    node = document.find(css=case["css"])
    actual = node.attr(case["attr"]) if case["attr"] else node.text()
    assert actual == case["expected"]
    assert document.text == case["html"]  # Raw source remains available.
    assert document.find(css=case["css"]).html() == node.html()


def test_url_resolution_without_document_url():
    document = Document('<img src="a.png" srcset="a.png 1x, b.png 2x">')
    assert document.find(css="img").attr("src") == "a.png"
    document = Document('<base href="https://cdn.test/"><img src="a.png">')
    assert document.find(css="img").attr("src") == "https://cdn.test/a.png"


def test_malformed_base_does_not_break_extraction():
    document = Document(
        '<base href="http://[bad"><h1>Title</h1><a href="/ok">OK</a>',
        url="https://example.com/",
    )
    assert document.find(css="h1").text() == "Title"
    assert document.find(css="a").attr("href") == "https://example.com/ok"


def test_serialized_css_preserves_relative_urls_and_content():
    document = Document(
        '<style>a {background:url("image?a=1&b=2");content:"<hello>"}</style>',
        url="https://example.com/",
    )
    assert 'url("image?a=1&b=2")' in document.find(css="style").html()
    assert 'content:"<hello>"' in document.find(css="style").html()
