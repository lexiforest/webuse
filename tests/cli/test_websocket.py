from contextlib import asynccontextmanager

import pytest

from webuse import cli
from webuse.cli import websocket as websocket_cli


@pytest.mark.parametrize("failure", [None, "connect", "recv"])
def test_websocket_command_sends_and_receives(monkeypatch, capsys, failure):
    captured = {}

    class FakeWebSocket:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            captured["closed"] = True

        def connect(self, url, **kwargs):
            captured["url"] = url
            captured["kwargs"] = kwargs
            if failure == "connect":
                raise ValueError("connect")

        def send_json(self, payload):
            captured["payload"] = payload

        def recv(self):
            if failure == "recv":
                raise ValueError("recv")
            return b"pong", 1

    monkeypatch.setattr(websocket_cli, "WebSocket", FakeWebSocket)

    args = [
        "websocket",
        "wss://example.com/socket",
        "--send-json",
        '{"ping": true}',
        "--recv",
        "2",
        "--header",
        "X-Test=yes",
    ]
    if failure:
        with pytest.raises(ValueError, match=failure):
            cli.main(args)
        assert captured["closed"]
        assert capsys.readouterr().out == ""
        return

    code = cli.main(args)
    out = capsys.readouterr().out.strip().splitlines()

    assert code == 0
    assert captured["url"] == "wss://example.com/socket"
    assert captured["kwargs"]["headers"] == {"X-Test": "yes"}
    assert captured["payload"] == {"ping": True}
    assert captured["closed"]
    assert out == [
        '{"url": "wss://example.com/socket", "message": "pong"}',
        '{"url": "wss://example.com/socket", "message": "pong"}',
    ]


@pytest.mark.parametrize("failure", [None, "connect", "recv"])
def test_async_websocket_command_uses_native_text_method(monkeypatch, capsys, failure):
    captured = []

    class Socket:
        async def send_str(self, value):
            captured.append(value)

        async def recv(self):
            if failure == "recv":
                raise ValueError("recv")
            return b"pong", 1

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            captured.append("session closed")

        @asynccontextmanager
        async def ws_connect(self, url, **kwargs):
            assert url == "wss://example.com"
            assert kwargs["headers"] == {"X-Test": "yes"}
            if failure == "connect":
                raise ValueError("connect")
            try:
                yield Socket()
            finally:
                captured.append("closed")

    monkeypatch.setattr(websocket_cli, "AsyncSession", Session)
    args = [
        "websocket",
        "wss://example.com",
        "--async",
        "--send",
        "ping",
        "--header",
        "X-Test=yes",
    ]
    if failure:
        with pytest.raises(ValueError, match=failure):
            cli.main(args)
        assert captured == (
            ["session closed"]
            if failure == "connect"
            else ["ping", "closed", "session closed"]
        )
        assert capsys.readouterr().out == ""
        return

    assert cli.main(args) == 0
    assert captured == ["ping", "closed", "session closed"]
    assert '"message": "pong"' in capsys.readouterr().out
