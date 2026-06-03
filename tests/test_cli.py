from webuse import cli


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

        def smart(self, prompt, *, key=None, store=None):
            assert prompt == "product link"
            assert key == "product"
            assert store is not None
            assert store.path == store_path

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

        def smart(self, prompt, *, key=None, store=None):
            assert prompt == "configured prompt"
            assert key == "configured"
            assert store is not None
            assert store.path == store_path

            class FakeElement:
                def text(self):
                    return "Configured"

            return FakeElement()

    monkeypatch.setattr(cli, "request", lambda *args, **kwargs: FakeResponse())

    code = cli.main(["fetch", "--config", str(config_path), "--smart", "configured prompt"])
    out = capsys.readouterr().out.strip()

    assert code == 0
    assert '"Configured"' in out
