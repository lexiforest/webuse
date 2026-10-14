import pytest

from webuse import cli
from webuse.cli import fetch as fetch_cli
from webuse.exceptions import SmartSelectorError


def test_fetch_command_with_selector(monkeypatch, capsys):
    class FakeResponse:
        url = "https://example.com"

        def css(self, selector):
            assert selector == ".title"

            class FakeElement:
                def text(self):
                    return "Hello"

            return [FakeElement()]

    monkeypatch.setattr(fetch_cli, "request", lambda *args, **kwargs: FakeResponse())

    code = cli.main(["fetch", "https://example.com", "--css", ".title"])
    out = capsys.readouterr().out.strip()

    assert code == 0
    assert '"Hello"' in out


@pytest.mark.parametrize("first", [False, True])
@pytest.mark.parametrize("method", ["css_find", "llm_find"])
def test_fetch_finds_element(monkeypatch, capsys, first, method):
    import json
    from types import SimpleNamespace
    from webuse import Response

    class Completions:
        def create(self, **kwargs):
            payload = json.loads(kwargs["messages"][1]["content"])
            assert payload["prompt"] == "primary product link"
            selected = next(c for c in payload["candidates"] if c["tag"] == "a")
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
                content=json.dumps({"index": selected["index"]})
            ))])

    client = SimpleNamespace(chat=SimpleNamespace(completions=Completions()))
    monkeypatch.setattr("webuse.extract.resolver.create_openai_client", lambda **kw: client)
    monkeypatch.setattr(
        fetch_cli,
        "request",
        lambda *args, **kwargs: Response(
            url="https://example.com/page",
            content=b'<a class="primary product" href="/buy">Buy</a>',
        ),
    )
    args = [
        "fetch", "https://example.com/page", "--" + method.replace("_", "-"),
        "a.primary" if method == "css_find" else "primary product link", "--attr", "href",
    ]
    if first:
        args.append("--first")
    assert cli.main(args) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["match" if first else "matches"] == (
        "https://example.com/buy" if first else ["https://example.com/buy"]
    )


@pytest.mark.parametrize("first", [False, True])
def test_fetch_css_find_missing_match(monkeypatch, capsys, first):
    import json
    from webuse import Response

    monkeypatch.setattr(
        fetch_cli, "request", lambda *args, **kwargs: Response(
            url="https://example.com", content=b"<h1>Title</h1>"
        )
    )
    args = ["fetch", "https://example.com", "--css-find", "a"]
    if first:
        args.append("--first")
    assert cli.main(args) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["match" if first else "matches"] == (None if first else [])


def test_fetch_rejects_combined_smart_and_llm_find():
    with pytest.raises(SystemExit) as error:
        cli.build_parser().parse_args(
            ["fetch", "https://example.com", "--llm-extract", "title", "--llm-find", "link"]
        )
    assert error.value.code == 2


def test_fetch_command_with_smart_extraction(monkeypatch, capsys):
    captured = {}

    class FakeResponse:
        url = "https://example.com"

        def llm_extract_first(self, prompt, **kwargs):
            captured["prompt"] = prompt
            captured["kwargs"] = kwargs
            return "Alpha Gadget"

    monkeypatch.setattr(fetch_cli, "request", lambda *args, **kwargs: FakeResponse())

    code = cli.main(
        [
            "fetch",
            "https://example.com",
            "--llm-extract",
            "Which product is first?",
            "--llm-model",
            "test-model",
            "--llm-max-chars",
            "100",
            "--llm-temperature",
            "0.2",
            "--output-shape",
            "item",
            "--field",
            "product",
            "--first",
        ]
    )
    out = capsys.readouterr().out.strip()

    assert code == 0
    assert out == '{\n  "product": "Alpha Gadget"\n}'
    assert captured["prompt"] == "Which product is first?"
    assert captured["kwargs"]["model"] == "test-model"
    assert captured["kwargs"]["max_chars"] == 100
    assert captured["kwargs"]["temperature"] == 0.2
    assert "first matching JSON value" in captured["kwargs"]["system_prompt"]


def test_fetch_command_with_explicit_llm_options(monkeypatch, capsys):
    captured = {}

    class FakeResponse:
        url = "https://example.com"

        def llm_extract_first(self, prompt, **kwargs):
            captured["prompt"] = prompt
            captured["kwargs"] = kwargs
            return "Configured Title"

    monkeypatch.setattr(fetch_cli, "request", lambda *args, **kwargs: FakeResponse())

    code = cli.main([
        "fetch", "https://example.com", "--llm-extract", "Extract the primary title",
        "--first", "--llm-system-prompt", "Return only the title.",
        "--llm-model", "configured-model", "--llm-base-url", "https://llm.example.com/v1",
        "--llm-api-key", "test-key", "--output-shape", "item", "--field", "title",
    ])
    out = capsys.readouterr().out.strip()

    assert code == 0
    assert out == '{\n  "title": "Configured Title"\n}'
    assert captured["prompt"] == "Extract the primary title"
    assert captured["kwargs"]["model"] == "configured-model"
    assert captured["kwargs"]["system_prompt"] == "Return only the title."
    assert captured["kwargs"]["base_url"] == "https://llm.example.com/v1"
    assert captured["kwargs"]["api_key"] == "test-key"


def test_fetch_command_prints_smart_json_array(monkeypatch, capsys):
    class FakeResponse:
        url = "https://example.com"

        def llm_extract(self, prompt, **kwargs):
            assert "JSON array" in kwargs["system_prompt"]
            return ["Alpha", "Beta"]

    monkeypatch.setattr(fetch_cli, "request", lambda *args, **kwargs: FakeResponse())

    code = cli.main(["fetch", "https://example.com", "--llm-extract", "All titles"])
    out = capsys.readouterr().out.strip()

    assert code == 0
    assert out == (
        "{\n"
        '  "url": "https://example.com",\n'
        '  "matches": [\n'
        '    "Alpha",\n'
        '    "Beta"\n'
        "  ],\n"
        '  "selector": "All titles"\n'
        "}"
    )


def test_fetch_passes_request_options(monkeypatch, capsys):
    captured = {}

    class FakeResponse:
        text = "ok\n"

    def fake_request(method, url, **kwargs):
        captured.update({"method": method, "url": url, "kwargs": kwargs})
        return FakeResponse()

    monkeypatch.setattr(fetch_cli, "request", fake_request)

    code = cli.main([
        "fetch", "https://example.com", "--method", "POST", "--timeout", "5",
        "--allow-redirects", "--impersonate", "chrome", "--header", "User-Agent=webuse",
        "--json", '{"query": "alpha"}',
    ])
    _ = capsys.readouterr()

    assert code == 0
    assert captured["method"] == "POST"
    assert captured["url"] == "https://example.com"
    assert captured["kwargs"]["headers"] == {"User-Agent": "webuse"}
    assert captured["kwargs"]["json"] == {"query": "alpha"}
    assert captured["kwargs"]["timeout"] == 5
    assert captured["kwargs"]["allow_redirects"] is True
    assert captured["kwargs"]["impersonate"] == "chrome"


def test_fetch_command_leaves_impersonation_default_to_client(monkeypatch, capsys):
    captured = {}

    class FakeResponse:
        text = "ok\n"

    def fake_request(method, url, **kwargs):
        captured.update({"method": method, "url": url, "kwargs": kwargs})
        return FakeResponse()

    monkeypatch.setattr(fetch_cli, "request", fake_request)

    code = cli.main(["fetch", "https://example.com"])
    _ = capsys.readouterr()

    assert code == 0
    assert "impersonate" not in captured["kwargs"]


def test_fetch_command_supports_body_files_and_request_options(
    monkeypatch, capsys, tmp_path
):
    upload = tmp_path / "upload.txt"
    upload.write_text("payload", encoding="utf-8")
    captured = {}

    class FakeResponse:
        text = "ok\n"

    def fake_request(method, url, **kwargs):
        captured.update({"method": method, "url": url, "kwargs": kwargs})
        assert kwargs["files"]["upload"].read() == b"payload"
        return FakeResponse()

    monkeypatch.setattr(fetch_cli, "request", fake_request)

    code = cli.main(
        [
            "fetch",
            "https://example.com",
            "--method",
            "POST",
            "--form",
            "name=alpha",
            "--file",
            f"upload={upload}",
            "--cookie",
            "session=abc",
            "--auth",
            "user:pass",
            "--no-verify",
            "--allow-redirects",
            "--max-redirects",
            "3",
            "--http-version",
            "v2",
            "--ja3",
            "ja3-value",
            "--akamai",
            "akamai-value",
            "--extra-fp",
            'tls="abc"',
        ]
    )
    _ = capsys.readouterr()

    assert code == 0
    assert captured["method"] == "POST"
    assert captured["kwargs"]["data"] == {"name": "alpha"}
    assert captured["kwargs"]["cookies"] == {"session": "abc"}
    assert captured["kwargs"]["auth"] == ("user", "pass")
    assert captured["kwargs"]["verify"] is False
    assert captured["kwargs"]["allow_redirects"] is True
    assert captured["kwargs"]["max_redirects"] == 3
    assert captured["kwargs"]["http_version"] == "v2"
    assert captured["kwargs"]["ja3"] == "ja3-value"
    assert captured["kwargs"]["akamai"] == "akamai-value"
    assert captured["kwargs"]["extra_fp"] == {"tls": "abc"}


def test_fetch_command_outputs_first_attr_as_item(monkeypatch, capsys):
    class FakeElement:
        def __init__(self, href):
            self.href = href

        def attr(self, name):
            assert name == "href"
            return self.href

    class FakeResponse:
        url = "https://example.com"

        def css(self, selector):
            assert selector == "a.product"
            return [FakeElement("/alpha"), FakeElement("/beta")]

    monkeypatch.setattr(fetch_cli, "request", lambda *args, **kwargs: FakeResponse())

    code = cli.main(
        [
            "fetch",
            "https://example.com",
            "--css",
            "a.product",
            "--attr",
            "href",
            "--first",
            "--output-shape",
            "item",
            "--field",
            "link",
        ]
    )
    out = capsys.readouterr().out.strip()

    assert code == 0
    assert out == '{\n  "link": "/alpha"\n}'


def test_fetch_command_can_output_jsonl(monkeypatch, capsys):
    class FakeElement:
        def text(self):
            return "Hello"

    class FakeResponse:
        url = "https://example.com"

        def css(self, selector):
            assert selector == ".title"
            return [FakeElement()]

    monkeypatch.setattr(fetch_cli, "request", lambda *args, **kwargs: FakeResponse())

    code = cli.main(
        ["fetch", "https://example.com", "--css", ".title", "--first", "--jsonl"]
    )
    out = capsys.readouterr().out.strip()

    assert code == 0
    assert (
        out == '{"url": "https://example.com", "match": "Hello", "selector": ".title"}'
    )


def test_fetch_command_outputs_all_matches_as_jsonl(monkeypatch, capsys):
    class FakeElement:
        def __init__(self, title):
            self.title = title

        def attr(self, name):
            assert name == "title"
            return self.title

    class FakeResponse:
        url = "https://books.toscrape.com/"

        def css(self, selector):
            assert selector == ".product_pod h3 a"
            return [FakeElement("Alpha"), FakeElement("Beta")]

    monkeypatch.setattr(fetch_cli, "request", lambda *args, **kwargs: FakeResponse())

    code = cli.main(
        [
            "fetch",
            "https://books.toscrape.com/",
            "--css",
            ".product_pod h3 a",
            "--attr",
            "title",
            "--all",
            "--jsonl",
        ]
    )
    out = capsys.readouterr().out.strip().splitlines()

    assert code == 0
    assert out == [
        '{"url": "https://books.toscrape.com/", "match": "Alpha", "selector": ".product_pod h3 a"}',
        '{"url": "https://books.toscrape.com/", "match": "Beta", "selector": ".product_pod h3 a"}',
    ]


def test_fetch_command_outputs_all_items_as_jsonl(monkeypatch, capsys):
    class FakeElement:
        def text(self):
            return "Hello"

    class FakeResponse:
        url = "https://example.com"

        def css(self, selector):
            assert selector == ".title"
            return [FakeElement(), FakeElement()]

    monkeypatch.setattr(fetch_cli, "request", lambda *args, **kwargs: FakeResponse())

    code = cli.main(
        [
            "fetch",
            "https://example.com",
            "--css",
            ".title",
            "--all",
            "--jsonl",
            "--output-shape",
            "item",
            "--field",
            "title",
        ]
    )
    out = capsys.readouterr().out.strip().splitlines()

    assert code == 0
    assert out == ['{"title": "Hello"}', '{"title": "Hello"}']


def test_fetch_command_outputs_all_matches_as_csv(monkeypatch, capsys):
    class FakeElement:
        def __init__(self, title):
            self.title = title

        def attr(self, name):
            assert name == "title"
            return self.title

    class FakeResponse:
        url = "https://books.toscrape.com/"

        def css(self, selector):
            assert selector == ".product_pod h3 a"
            return [FakeElement("Alpha"), FakeElement("Beta")]

    monkeypatch.setattr(fetch_cli, "request", lambda *args, **kwargs: FakeResponse())

    code = cli.main(
        [
            "fetch",
            "https://books.toscrape.com/",
            "--css",
            ".product_pod h3 a",
            "--attr",
            "title",
            "--all",
            "--csv",
        ]
    )
    out = capsys.readouterr().out.strip().splitlines()

    assert code == 0
    assert out == [
        "url,match,selector",
        "https://books.toscrape.com/,Alpha,.product_pod h3 a",
        "https://books.toscrape.com/,Beta,.product_pod h3 a",
    ]


def test_fetch_command_outputs_item_csv(monkeypatch, capsys):
    class FakeElement:
        def text(self):
            return "Hello"

    class FakeResponse:
        url = "https://example.com"

        def css(self, selector):
            assert selector == ".title"
            return [FakeElement(), FakeElement()]

    monkeypatch.setattr(fetch_cli, "request", lambda *args, **kwargs: FakeResponse())

    code = cli.main(
        [
            "fetch",
            "https://example.com",
            "--css",
            ".title",
            "--all",
            "--csv",
            "--output-shape",
            "item",
            "--field",
            "title",
        ]
    )
    out = capsys.readouterr().out.strip().splitlines()

    assert code == 0
    assert out == ["title", "Hello", "Hello"]


def test_fetch_command_rejects_csv_with_jsonl():
    with pytest.raises(SystemExit):
        cli.main(["fetch", "https://example.com", "--csv", "--jsonl"])


def test_fetch_smart_llm_failure_can_emit_empty(monkeypatch, capsys):
    class FakeResolver:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class FakeResponse:
        url = "https://example.com"

        def llm_find(
            self,
            prompt,
            *,
            resolver=None,
        ):
            assert prompt == "missing cta"
            assert isinstance(resolver, FakeResolver)
            assert resolver.kwargs["model"] == "test-model"
            raise SmartSelectorError("missing")

    monkeypatch.setattr(fetch_cli, "LlmSmartResolver", FakeResolver)
    monkeypatch.setattr(fetch_cli, "request", lambda *args, **kwargs: FakeResponse())

    code = cli.main(
        [
            "fetch",
            "https://example.com",
            "--llm-model",
            "test-model",
            "--llm-find",
            "missing cta",
            "--find-failure",
            "empty",
        ]
    )
    out = capsys.readouterr().out.strip()

    assert code == 0
    assert '"matches": []' in out


def test_malformed_key_value_arguments_have_clear_errors(monkeypatch):
    monkeypatch.setattr(fetch_cli, "request", lambda *args, **kwargs: None)

    with pytest.raises(SystemExit) as exc:
        cli.main(["fetch", "https://example.com", "--header", "missing-equals"])

    assert "KEY=VALUE" in str(exc.value)
