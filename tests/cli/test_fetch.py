import sqlite3

import pytest

from webuse import cli
from webuse.exceptions import SmartSelectorError
from webuse.models import CrawlResult, CrawlStats
from webuse.response import Response


def test_fetch_command_with_selector(monkeypatch, capsys):
    class FakeResponse:
        url = "https://example.com"

        def css(self, selector):
            assert selector == ".title"

            class FakeElement:
                def text(self):
                    return "Hello"

            return [FakeElement()]

    monkeypatch.setattr(cli, "request", lambda *args, **kwargs: FakeResponse())

    code = cli.main(["fetch", "https://example.com", "--css", ".title"])
    out = capsys.readouterr().out.strip()

    assert code == 0
    assert '"Hello"' in out


def test_fetch_command_with_smart_extraction(monkeypatch, capsys):
    captured = {}

    class FakeResponse:
        url = "https://example.com"

        def smart_first(self, prompt, **kwargs):
            captured["prompt"] = prompt
            captured["kwargs"] = kwargs
            return "Alpha Gadget"

    monkeypatch.setattr(cli, "request", lambda *args, **kwargs: FakeResponse())

    code = cli.main(
        [
            "fetch",
            "https://example.com",
            "--smart",
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
    assert captured["kwargs"]["translate_xpath"] is False
    assert captured["kwargs"]["model"] == "test-model"
    assert captured["kwargs"]["max_chars"] == 100
    assert captured["kwargs"]["temperature"] == 0.2


def test_fetch_command_with_configured_smart_extraction(monkeypatch, capsys, tmp_path):
    captured = {}
    config = tmp_path / "webuse.yaml"
    config.write_text(
        """
llm:
  model: configured-model
  base_url: https://llm.example.com/v1
  api_key: test-key
fetch:
  url: https://example.com
  smart: Extract the primary title
  first: true
  llm_system_prompt: Return only the title.
  output_shape: item
  field: title
""",
        encoding="utf-8",
    )

    class FakeResponse:
        url = "https://example.com"

        def smart_first(self, prompt, **kwargs):
            captured["prompt"] = prompt
            captured["kwargs"] = kwargs
            return "Configured Title"

    monkeypatch.setattr(cli, "request", lambda *args, **kwargs: FakeResponse())

    code = cli.main(["fetch", "--config", str(config)])
    out = capsys.readouterr().out.strip()

    assert code == 0
    assert out == '{\n  "title": "Configured Title"\n}'
    assert captured["prompt"] == "Extract the primary title"
    assert captured["kwargs"]["translate_xpath"] is False
    assert captured["kwargs"]["model"] == "configured-model"
    assert captured["kwargs"]["system_prompt"] == "Return only the title."
    assert captured["kwargs"]["base_url"] == "https://llm.example.com/v1"
    assert captured["kwargs"]["api_key"] == "test-key"


def test_fetch_command_prints_smart_json_array(monkeypatch, capsys):
    class FakeResponse:
        url = "https://example.com"

        def smart(self, prompt, **kwargs):
            assert "JSON array" in kwargs["system_prompt"]
            return ["Alpha", "Beta"]

    monkeypatch.setattr(cli, "request", lambda *args, **kwargs: FakeResponse())

    code = cli.main(["fetch", "https://example.com", "--smart", "All titles"])
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


def test_fetch_command_with_smart_store_and_key(monkeypatch, capsys, tmp_path):
    store_path = tmp_path / "selectors.json"

    class FakeResponse:
        url = "https://example.com"

        def smart(
            self,
            prompt,
            *,
            translate_xpath=False,
            key=None,
            store=None,
            use_llm=False,
            resolver=None,
        ):
            assert prompt == "product link"
            assert translate_xpath is True
            assert key == "product"
            assert store is not None
            assert store.path == store_path
            assert use_llm is False
            assert resolver is None

            class FakeElement:
                def text(self):
                    return "Open"

            return [FakeElement()]

    monkeypatch.setattr(cli, "request", lambda *args, **kwargs: FakeResponse())

    code = cli.main(
        [
            "fetch",
            "https://example.com",
            "--smart",
            "product link",
            "--translate-xpath",
            "--smart-store",
            str(store_path),
            "--smart-key",
            "product",
        ]
    )
    out = capsys.readouterr().out.strip()

    assert code == 0
    assert '"Open"' in out


def test_fetch_command_uses_configured_smart_store_and_key(
    monkeypatch, capsys, tmp_path
):
    store_path = tmp_path / "configured-selectors.json"
    config_path = tmp_path / "webuse.toml"
    config_path.write_text(
        "\n".join(
            [
                "[fetch]",
                'url = "https://example.com"',
                "translate_xpath = true",
                f'smart_store = "{store_path}"',
                'smart_key = "configured"',
            ]
        ),
        encoding="utf-8",
    )

    class FakeResponse:
        url = "https://example.com"

        def smart(
            self,
            prompt,
            *,
            translate_xpath=False,
            key=None,
            store=None,
            use_llm=False,
            resolver=None,
        ):
            assert prompt == "configured prompt"
            assert translate_xpath is True
            assert key == "configured"
            assert store is not None
            assert store.path == store_path
            assert use_llm is False
            assert resolver is None

            class FakeElement:
                def text(self):
                    return "Configured"

            return [FakeElement()]

    monkeypatch.setattr(cli, "request", lambda *args, **kwargs: FakeResponse())

    code = cli.main(
        ["fetch", "--config", str(config_path), "--smart", "configured prompt"]
    )
    out = capsys.readouterr().out.strip()

    assert code == 0
    assert '"Configured"' in out


def test_fetch_config_passes_request_options(monkeypatch, capsys, tmp_path):
    config_path = tmp_path / "webuse.toml"
    config_path.write_text(
        "\n".join(
            [
                "[fetch]",
                'url = "https://example.com"',
                'method = "POST"',
                "timeout = 5",
                "follow_redirects = true",
                'impersonate = "chrome"',
                "[fetch.headers]",
                'User-Agent = "webuse"',
                "[fetch.json]",
                'query = "alpha"',
            ]
        ),
        encoding="utf-8",
    )
    captured = {}

    class FakeResponse:
        text = "ok\n"

    def fake_request(method, url, **kwargs):
        captured.update({"method": method, "url": url, "kwargs": kwargs})
        return FakeResponse()

    monkeypatch.setattr(cli, "request", fake_request)

    code = cli.main(["fetch", "--config", str(config_path)])
    _ = capsys.readouterr()

    assert code == 0
    assert captured["method"] == "POST"
    assert captured["url"] == "https://example.com"
    assert captured["kwargs"]["headers"] == {"User-Agent": "webuse"}
    assert captured["kwargs"]["json"] == {"query": "alpha"}
    assert captured["kwargs"]["timeout"] == 5
    assert captured["kwargs"]["follow_redirects"] is True
    assert captured["kwargs"]["impersonate"] == "chrome"


def test_fetch_command_defaults_to_chrome_impersonation(monkeypatch, capsys):
    captured = {}

    class FakeResponse:
        text = "ok\n"

    def fake_request(method, url, **kwargs):
        captured.update({"method": method, "url": url, "kwargs": kwargs})
        return FakeResponse()

    monkeypatch.setattr(cli, "request", fake_request)

    code = cli.main(["fetch", "https://example.com"])
    _ = capsys.readouterr()

    assert code == 0
    assert captured["kwargs"]["impersonate"] == "chrome"


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

    monkeypatch.setattr(cli, "request", fake_request)

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
            "--follow-redirects",
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
    assert captured["kwargs"]["follow_redirects"] is True
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

    monkeypatch.setattr(cli, "request", lambda *args, **kwargs: FakeResponse())

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

    monkeypatch.setattr(cli, "request", lambda *args, **kwargs: FakeResponse())

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

    monkeypatch.setattr(cli, "request", lambda *args, **kwargs: FakeResponse())

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

    monkeypatch.setattr(cli, "request", lambda *args, **kwargs: FakeResponse())

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

    monkeypatch.setattr(cli, "request", lambda *args, **kwargs: FakeResponse())

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

    monkeypatch.setattr(cli, "request", lambda *args, **kwargs: FakeResponse())

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


def test_fetch_smart_llm_failure_can_emit_empty(monkeypatch, capsys, tmp_path):
    class FakeResolver:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class FakeResponse:
        url = "https://example.com"

        def smart(
            self,
            prompt,
            *,
            translate_xpath=False,
            key=None,
            store=None,
            use_llm=False,
            resolver=None,
        ):
            assert prompt == "missing cta"
            assert translate_xpath is True
            assert use_llm is True
            assert isinstance(resolver, FakeResolver)
            assert resolver.kwargs["model"] == "test-model"
            raise SmartSelectorError("missing")

    monkeypatch.setattr(cli, "LlmSmartResolver", FakeResolver)
    monkeypatch.setattr(cli, "request", lambda *args, **kwargs: FakeResponse())

    config_path = tmp_path / "webuse.yaml"
    config_path.write_text(
        """
llm:
  model: test-model
  api_key: test-key
  base_url: https://llm.example.com/v1
fetch:
  url: https://example.com
""",
        encoding="utf-8",
    )

    code = cli.main(
        [
            "fetch",
            "--config",
            str(config_path),
            "--smart",
            "missing cta",
            "--translate-xpath",
            "--smart-use-llm",
            "--smart-failure",
            "empty",
        ]
    )
    out = capsys.readouterr().out.strip()

    assert code == 0
    assert '"matches": []' in out


def test_malformed_key_value_arguments_have_clear_errors(monkeypatch):
    monkeypatch.setattr(cli, "request", lambda *args, **kwargs: None)

    with pytest.raises(SystemExit) as exc:
        cli.main(["fetch", "https://example.com", "--header", "missing-equals"])

    assert "KEY=VALUE" in str(exc.value)
