import sqlite3

import pytest

from webuse import cli
from webuse.exceptions import SmartSelectorError
from webuse.models import CrawlResult, CrawlStats
from webuse.response import Response


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
