from __future__ import annotations

import json
from typing import Any

from curl_cffi.requests import AsyncSession, Session


class WebSocketConnection:
    def __init__(self, raw: Any, owner: Any = None):
        self.raw = raw
        self._owner = owner

    def send_text(self, data: str) -> Any:
        return self.raw.send(data)

    def send_bytes(self, data: bytes) -> Any:
        return self.raw.send(data)

    def send_json(self, data: Any) -> Any:
        return self.send_text(json.dumps(data))

    def recv(self) -> Any:
        return self.raw.recv()

    def recv_text(self) -> str:
        message = self.recv()
        return message.decode("utf-8") if isinstance(message, bytes) else str(message)

    def recv_json(self) -> Any:
        return json.loads(self.recv_text())

    def close(self, code: int | None = None, reason: str | None = None) -> Any:
        kwargs = {}
        if code is not None:
            kwargs["code"] = code
        if reason is not None:
            kwargs["reason"] = reason
        result = self.raw.close(**kwargs)
        if self._owner is not None:
            self._owner.close()
        return result

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        _ = (exc_type, exc, tb)
        self.close()


class AsyncWebSocketConnection:
    def __init__(self, raw: Any, owner: Any = None):
        self.raw = raw
        self._owner = owner

    async def send_text(self, data: str) -> Any:
        return await self.raw.send(data)

    async def send_bytes(self, data: bytes) -> Any:
        return await self.raw.send(data)

    async def send_json(self, data: Any) -> Any:
        return await self.send_text(json.dumps(data))

    async def recv(self) -> Any:
        return await self.raw.recv()

    async def recv_text(self) -> str:
        message = await self.recv()
        return message.decode("utf-8") if isinstance(message, bytes) else str(message)

    async def recv_json(self) -> Any:
        return json.loads(await self.recv_text())

    async def close(self, code: int | None = None, reason: str | None = None) -> Any:
        kwargs = {}
        if code is not None:
            kwargs["code"] = code
        if reason is not None:
            kwargs["reason"] = reason
        result = self.raw.close(**kwargs)
        if hasattr(result, "__await__"):
            result = await result
        if self._owner is not None:
            await self._owner.close()
        return result

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        _ = (exc_type, exc, tb)
        await self.close()

    def __aiter__(self):
        return self

    async def __anext__(self):
        message = await self.recv()
        if message is None:
            raise StopAsyncIteration
        return message


class WebSocketClient:
    def __init__(self, **defaults: Any):
        self.defaults = defaults
        self._session = None

    def _ensure_session(self):
        if self._session is None:
            self._session = Session()
        return self._session

    def connect(self, url: str, **kwargs: Any) -> WebSocketConnection:
        session = self._ensure_session()
        raw = session.ws_connect(url, **{**self.defaults, **kwargs})
        return WebSocketConnection(raw)

    def close(self):
        if self._session is not None and hasattr(self._session, "close"):
            self._session.close()
        self._session = None


class AsyncWebSocketClient:
    def __init__(self, **defaults: Any):
        self.defaults = defaults
        self._session = None

    async def _ensure_session(self):
        if self._session is None:
            self._session = AsyncSession()
        return self._session

    async def connect(self, url: str, **kwargs: Any) -> AsyncWebSocketConnection:
        session = await self._ensure_session()
        raw = await session.ws_connect(url, **{**self.defaults, **kwargs})
        return AsyncWebSocketConnection(raw)

    async def close(self):
        if self._session is not None and hasattr(self._session, "close"):
            result = self._session.close()
            if hasattr(result, "__await__"):
                await result
        self._session = None


def ws_connect(url: str, **kwargs: Any) -> WebSocketConnection:
    client = WebSocketClient()
    connection = client.connect(url, **kwargs)
    connection._owner = client
    return connection


async def aws_connect(url: str, **kwargs: Any) -> AsyncWebSocketConnection:
    client = AsyncWebSocketClient()
    connection = await client.connect(url, **kwargs)
    connection._owner = client
    return connection
