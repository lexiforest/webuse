from dataclasses import fields

import pytest

from webuse import cli
from webuse.exceptions import SmartSelectorError
from webuse.models import RequestOptions


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


def test_crawl_command_streams_items(monkeypatch, capsys):
    class FakeResult:
        items = [{"title": "One"}]
        errors = []

    monkeypatch.setattr(cli, "crawl", lambda *args, **kwargs: FakeResult())

    code = cli.main(["crawl", "https://example.com", "--extract-css", "title=h1"])
    out = capsys.readouterr().out.strip()

    assert code == 0
    assert '"title": "One"' in out


def test_fetch_command_with_smart_store_and_key(monkeypatch, capsys, tmp_path):
    store_path = tmp_path / "selectors.json"

    class FakeResponse:
        url = "https://example.com"

        def smart(self, prompt, *, key=None, store=None, use_llm=False, resolver=None):
            assert prompt == "product link"
            assert key == "product"
            assert store is not None
            assert store.path == store_path
            assert use_llm is False
            assert resolver is None

            class FakeElement:
                def text(self):
                    return "Open"

            return FakeElement()

    monkeypatch.setattr(cli, "request", lambda *args, **kwargs: FakeResponse())

    code = cli.main(
        [
            "fetch",
            "https://example.com",
            "--smart",
            "product link",
            "--smart-store",
            str(store_path),
            "--smart-key",
            "product",
        ]
    )
    out = capsys.readouterr().out.strip()

    assert code == 0
    assert '"Open"' in out


def test_fetch_command_uses_configured_smart_store_and_key(monkeypatch, capsys, tmp_path):
    store_path = tmp_path / "configured-selectors.json"
    config_path = tmp_path / "webuse.toml"
    config_path.write_text(
        "\n".join(
            [
                "[fetch]",
                'url = "https://example.com"',
                f'smart_store = "{store_path}"',
                'smart_key = "configured"',
            ]
        ),
        encoding="utf-8",
    )

    class FakeResponse:
        url = "https://example.com"

        def smart(self, prompt, *, key=None, store=None, use_llm=False, resolver=None):
            assert prompt == "configured prompt"
            assert key == "configured"
            assert store is not None
            assert store.path == store_path
            assert use_llm is False
            assert resolver is None

            class FakeElement:
                def text(self):
                    return "Configured"

            return FakeElement()

    monkeypatch.setattr(cli, "request", lambda *args, **kwargs: FakeResponse())

    code = cli.main(["fetch", "--config", str(config_path), "--smart", "configured prompt"])
    out = capsys.readouterr().out.strip()

    assert code == 0
    assert '"Configured"' in out


def test_config_request_option_names_match_request_options():
    expected = {field.name for field in fields(RequestOptions) if field.name != "extra_kwargs"}
    config = {name: name for name in expected}
    config["extra_kwargs"] = {"custom_option": "custom"}

    options = cli._request_options_from_config(config)

    assert set(options) == expected | {"custom_option"}


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


def test_crawl_config_builds_rich_follow_extract_and_request_defaults(monkeypatch, capsys, tmp_path):
    config_path = tmp_path / "webuse.toml"
    config_path.write_text(
        "\n".join(
            [
                "[crawl]",
                'seeds = ["https://example.com"]',
                "max_depth = 2",
                "max_requests = 10",
                "concurrency = 3",
                'allowed_domains = ["example.com"]',
                "[crawl.request_defaults]",
                "timeout = 7",
                'impersonate = "chrome"',
                "[crawl.request_defaults.headers]",
                'User-Agent = "webuse"',
                "[crawl.extract.title]",
                'xpath = "//h1"',
                "[crawl.extract.links]",
                'css = "a.product"',
                'attr = "href"',
                "all = true",
                "[crawl.extract.cta]",
                'smart = "primary cta"',
                'attr = "href"',
                "[[crawl.follow]]",
                'xpath = "//a[@data-next]"',
                'attr = "data-next"',
                'include = "/products/"',
                'exclude = "/archive/"',
                "same_domain = true",
                "max_depth = 1",
                'allowed_domains = ["example.com"]',
            ]
        ),
        encoding="utf-8",
    )
    captured = {}

    class FakeResult:
        items = [{"title": "One"}]
        errors = []

    def fake_crawl(seeds, **options):
        captured.update({"seeds": seeds, "options": options})
        return FakeResult()

    monkeypatch.setattr(cli, "crawl", fake_crawl)

    code = cli.main(["crawl", "--config", str(config_path)])
    out = capsys.readouterr().out.strip()

    assert code == 0
    assert '"title": "One"' in out
    assert captured["seeds"] == ["https://example.com"]
    assert captured["options"]["max_depth"] == 2
    assert captured["options"]["max_requests"] == 10
    assert captured["options"]["concurrency"] == 3
    assert captured["options"]["allowed_domains"] == {"example.com"}
    assert captured["options"]["request_defaults"] == {
        "timeout": 7,
        "impersonate": "chrome",
        "headers": {"User-Agent": "webuse"},
    }
    assert captured["options"]["extract"]["links"] == {
        "css": "a.product",
        "attr": "href",
        "all": True,
    }
    assert captured["options"]["follow"][0].xpath == "//a[@data-next]"
    assert captured["options"]["follow"][0].attr == "data-next"
    assert captured["options"]["follow"][0].include == "/products/"
    assert captured["options"]["follow"][0].exclude == "/archive/"
    assert captured["options"]["follow"][0].same_domain is True
    assert captured["options"]["follow"][0].max_depth == 1
    assert captured["options"]["follow"][0].allowed_domains == {"example.com"}


def test_fetch_command_supports_body_files_and_request_options(monkeypatch, capsys, tmp_path):
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
    assert out == '{"link": "/alpha"}'


def test_fetch_smart_llm_failure_can_emit_empty(monkeypatch, capsys):
    class FakeResolver:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class FakeResponse:
        url = "https://example.com"

        def smart(self, prompt, *, key=None, store=None, use_llm=False, resolver=None):
            assert prompt == "missing cta"
            assert use_llm is True
            assert isinstance(resolver, FakeResolver)
            assert resolver.kwargs["model"] == "test-model"
            raise SmartSelectorError("missing")

    monkeypatch.setattr(cli, "LlmSmartResolver", FakeResolver)
    monkeypatch.setattr(cli, "request", lambda *args, **kwargs: FakeResponse())

    code = cli.main(
        [
            "fetch",
            "https://example.com",
            "--smart",
            "missing cta",
            "--smart-use-llm",
            "--smart-model",
            "test-model",
            "--smart-failure",
            "empty",
        ]
    )
    out = capsys.readouterr().out.strip()

    assert code == 0
    assert '"match": null' in out


def test_crawl_cli_builds_rich_extract_rules(monkeypatch, capsys):
    captured = {}

    class FakeResult:
        items = [{"ok": True}]
        errors = []

    def fake_crawl(seeds, **options):
        captured.update({"seeds": seeds, "options": options})
        return FakeResult()

    monkeypatch.setattr(cli, "crawl", fake_crawl)

    code = cli.main(
        [
            "crawl",
            "https://example.com",
            "--extract-css",
            "links=a.product",
            "--extract-xpath",
            "title=//h1",
            "--extract-smart",
            "cta=primary cta",
            "--extract-attr",
            "links=href",
            "--extract-all",
            "links",
        ]
    )
    _ = capsys.readouterr()

    assert code == 0
    assert captured["options"]["extract"] == {
        "links": {"css": "a.product", "attr": "href", "all": True},
        "title": {"xpath": "//h1"},
        "cta": {"smart": "primary cta"},
    }


def test_websocket_command_sends_and_receives(monkeypatch, capsys):
    captured = {}

    class FakeWebSocket:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def send_json(self, payload):
            captured["payload"] = payload

        def recv(self):
            return "pong"

    def fake_ws_connect(url, **kwargs):
        captured["url"] = url
        captured["kwargs"] = kwargs
        return FakeWebSocket()

    monkeypatch.setattr(cli, "ws_connect", fake_ws_connect)

    code = cli.main(
        [
            "websocket",
            "wss://example.com/socket",
            "--send-json",
            '{"ping": true}',
            "--recv",
            "2",
            "--header",
            "X-Test=yes",
        ]
    )
    out = capsys.readouterr().out.strip().splitlines()

    assert code == 0
    assert captured["url"] == "wss://example.com/socket"
    assert captured["kwargs"]["headers"] == {"X-Test": "yes"}
    assert captured["payload"] == {"ping": True}
    assert out == [
        '{"url": "wss://example.com/socket", "message": "pong"}',
        '{"url": "wss://example.com/socket", "message": "pong"}',
    ]


def test_malformed_key_value_arguments_have_clear_errors(monkeypatch):
    monkeypatch.setattr(cli, "request", lambda *args, **kwargs: None)

    with pytest.raises(SystemExit) as exc:
        cli.main(["fetch", "https://example.com", "--header", "missing-equals"])

    assert "KEY=VALUE" in str(exc.value)
