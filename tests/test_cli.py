from getkit import cli


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
