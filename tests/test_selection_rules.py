import asyncio
import json
from types import SimpleNamespace

import pytest

from webuse import ExtractionError, FollowRule, Response, acrawl, crawl
from webuse.extract import aextract_items, extract_items
from webuse.extract.schema import compile_extraction
from webuse.exceptions import ConfigError


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("backend", ["css", "llm"])
@pytest.mark.parametrize("all_matches", [False, True])
def test_fields_and_follow_share_selection_and_policy(
    monkeypatch, asynchronous, backend, all_matches
):
    pages = {
        "https://test/": '<a href="/a#one">A</a><a href="/a#two">Again</a>'
        '<a href="/b">B</a><a href="https://outside/">Outside</a>',
        "https://test/a": "<h1>A</h1>",
        "https://test/b": "<h1>B</h1>",
    }

    class Client:
        def request(self, method, url, **kwargs):
            return Response(url=url, content=pages[url].encode())

    class AsyncClient:
        async def request(self, method, url, **kwargs):
            return Client().request(method, url, **kwargs)

    calls = []

    def reply(**payload):
        data = json.loads(payload["messages"][1]["content"])
        calls.append(data)
        indices = [c["index"] for c in data["candidates"] if c["tag"] == "a"]
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=json.dumps({"indices": indices[::-1]})
                    )
                )
            ]
        )

    class Model:
        def __init__(self):
            self.chat = SimpleNamespace(completions=self)

        def create(self, **payload):
            assert not asynchronous
            return reply(**payload)

        def close(self):
            pass

    async def async_reply(**payload):
        assert asynchronous
        payload.pop("settings")
        payload.pop("client")
        payload.pop("api_key")
        payload.pop("base_url")
        return reply(**payload).choices[0].message.content

    monkeypatch.setattr(
        "webuse.extract.resolver.create_openai_client", lambda **kw: Model()
    )
    monkeypatch.setattr("webuse.extract.resolver.acompletion_content", async_reply)
    selection = {backend: "a" if backend == "css" else "links", "all": all_matches}
    options = dict(
        follow=FollowRule(
            **selection, source_page_type="default", page_type="detail", same_domain=True
        ),
        extract={
            "default": {"page": {"fields": {"links": {**selection, "attr": "href"}}}}
        },
        max_depth=1,
        concurrency=1,
    )
    if asynchronous:
        result = asyncio.run(acrawl("https://test/", client=AsyncClient(), **options))
    else:
        result = crawl("https://test/", client=Client(), **options)
    expected = [
        "https://test/a#one",
        "https://test/a#two",
        "https://test/b",
        "https://outside/",
    ]
    assert result.items[0]["links"] == (expected if all_matches else expected[0])
    assert result.visited == (
        {"https://test/", "https://test/a", "https://test/b"}
        if all_matches
        else {"https://test/", "https://test/a"}
    )
    assert len(calls) == (2 if backend == "llm" else 0)


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize(
    "rule",
    [
        {"css": "missing", "required": True},
        {"css": "a", "attr": "title", "required": True},
        {"css": "missing", "all": True, "required": True},
    ],
)
def test_required_field_failure(asynchronous, rule):
    rules = {"default": {"page": {"fields": {"value": rule}}}}
    response = Response(content=b"<a>A</a>")

    async def run():
        return [item async for item in aextract_items(response, rules)]

    with pytest.raises(ExtractionError, match="Required field"):
        asyncio.run(run()) if asynchronous else extract_items(response, rules)


@pytest.mark.parametrize(
    "spec",
    [
        {"llm_extract": "record"},
        {"llm_extract": "record", "schema": {"type": "invalid"}},
        {"fields": {"value": {"llm_extract": "value", "schema": {"type": "invalid"}}}},
        {"fields": {}, "llm_extract": "record", "schema": {"type": "object"}},
        {"fields": {"value": {"llm_extract": "value", "schema": str, "all": True}}},
    ],
)
def test_invalid_structured_schema_fails_at_compilation(spec):
    with pytest.raises(ConfigError, match="default.record"):
        compile_extraction({"default": {"record": spec}})


@pytest.mark.parametrize("asynchronous", [False, True])
def test_one_structured_call_emits_multiple_validated_records(monkeypatch, asynchronous):
    calls = []
    schema = {
        "type": "array",
        "items": {"$ref": "#/$defs/product"},
        "$defs": {
            "product": {
                "type": "object",
                "required": ["title"],
                "properties": {"title": {"type": "string"}},
                "additionalProperties": False,
            }
        },
    }
    content = '[{"title":"A"},{"title":"B"}]'

    class Model:
        def __init__(self):
            self.chat = SimpleNamespace(completions=self)

        def create(self, **payload):
            calls.append(payload)
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
            )

        def close(self):
            pass

    async def async_content(**payload):
        calls.append(payload)
        return content

    monkeypatch.setattr("webuse.extract.structured.create_openai_client", lambda **kw: Model())
    monkeypatch.setattr("webuse.extract.structured.acompletion_content", async_content)
    rules = {"default": {"product": {"llm_extract": "products", "schema": schema}}}
    response = Response(content=b"<h1>A</h1><h1>B</h1>")

    async def run():
        return [item async for item in aextract_items(response, rules)]

    result = asyncio.run(run()) if asynchronous else extract_items(response, rules)
    assert result == [{"title": "A", "_type": "product"}, {"title": "B", "_type": "product"}]
    assert len(calls) == 1
    assert response._tree is None
    content = '[{"title":12}]'
    with pytest.raises(ExtractionError):
        asyncio.run(run()) if asynchronous else extract_items(response, rules)
