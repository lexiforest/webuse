from __future__ import annotations

from dataclasses import fields, replace
from typing import Any

from curl_cffi.requests import AsyncSession, Session

from .models import RequestOptions
from .response import Response, from_curl_response


class BaseClient:
    session_class_name = "Session"

    def __init__(self, **defaults: Any):
        self.default_options = RequestOptions(extra_kwargs={})
        self._apply_defaults(defaults)
        self._session = None

    def _apply_defaults(self, defaults: dict[str, Any]) -> None:
        extra = {
            key: value
            for key, value in defaults.items()
            if not hasattr(self.default_options, key)
        }
        known = {
            key: value
            for key, value in defaults.items()
            if hasattr(self.default_options, key)
        }
        self.default_options = replace(self.default_options, **known)
        self.default_options.extra_kwargs.update(extra)

    def _build_request_kwargs(self, options: RequestOptions | None, extra_kwargs: dict[str, Any]) -> dict[str, Any]:
        combined = replace(self.default_options)
        combined.extra_kwargs = dict(self.default_options.extra_kwargs)
        if options is not None:
            option_values = {
                field.name: getattr(options, field.name)
                for field in fields(RequestOptions)
                if field.name != "extra_kwargs" and getattr(options, field.name) is not None
            }
            combined = replace(combined, **option_values)
            combined.extra_kwargs.update(options.extra_kwargs)
        combined.extra_kwargs.update(extra_kwargs)
        return combined.to_request_kwargs()

    def _ensure_session(self):
        if self._session is None:
            session_class = Session if self.session_class_name == "Session" else AsyncSession
            self._session = session_class()
        return self._session

    def close(self) -> None:
        if self._session is not None and hasattr(self._session, "close"):
            self._session.close()
        self._session = None

    def __enter__(self):
        self._ensure_session()
        return self

    def __exit__(self, exc_type, exc, tb):
        _ = (exc_type, exc, tb)
        self.close()


class Client(BaseClient):
    session_class_name = "Session"

    def request(self, method: str, url: str, *, options: RequestOptions | None = None, **kwargs: Any) -> Response:
        session = self._ensure_session()
        request_kwargs = self._build_request_kwargs(options, kwargs)
        response = session.request(method.upper(), url, **request_kwargs)
        return from_curl_response(response)

    def stream(self, method: str, url: str, *, options: RequestOptions | None = None, **kwargs: Any):
        session = self._ensure_session()
        request_kwargs = self._build_request_kwargs(options, kwargs)
        return session.stream(method.upper(), url, **request_kwargs)

    def get(self, url: str, **kwargs: Any) -> Response:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> Response:
        return self.request("POST", url, **kwargs)

    def put(self, url: str, **kwargs: Any) -> Response:
        return self.request("PUT", url, **kwargs)

    def delete(self, url: str, **kwargs: Any) -> Response:
        return self.request("DELETE", url, **kwargs)


class AsyncClient(BaseClient):
    session_class_name = "AsyncSession"

    async def _ensure_async_session(self):
        if self._session is None:
            self._session = AsyncSession()
        return self._session

    async def request(self, method: str, url: str, *, options: RequestOptions | None = None, **kwargs: Any) -> Response:
        session = await self._ensure_async_session()
        request_kwargs = self._build_request_kwargs(options, kwargs)
        response = await session.request(method.upper(), url, **request_kwargs)
        return from_curl_response(response)

    async def astream(self, method: str, url: str, *, options: RequestOptions | None = None, **kwargs: Any):
        session = await self._ensure_async_session()
        request_kwargs = self._build_request_kwargs(options, kwargs)
        stream = session.stream(method.upper(), url, **request_kwargs)
        return await stream if hasattr(stream, "__await__") else stream

    async def get(self, url: str, **kwargs: Any) -> Response:
        return await self.request("GET", url, **kwargs)

    async def post(self, url: str, **kwargs: Any) -> Response:
        return await self.request("POST", url, **kwargs)

    async def put(self, url: str, **kwargs: Any) -> Response:
        return await self.request("PUT", url, **kwargs)

    async def delete(self, url: str, **kwargs: Any) -> Response:
        return await self.request("DELETE", url, **kwargs)

    async def __aenter__(self):
        await self._ensure_async_session()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        _ = (exc_type, exc, tb)
        if self._session is not None and hasattr(self._session, "close"):
            close = self._session.close()
            if hasattr(close, "__await__"):
                await close
        self._session = None


def request(method: str, url: str, **kwargs: Any) -> Response:
    with Client() as client:
        return client.request(method, url, **kwargs)


def get(url: str, **kwargs: Any) -> Response:
    return request("GET", url, **kwargs)


def post(url: str, **kwargs: Any) -> Response:
    return request("POST", url, **kwargs)


def put(url: str, **kwargs: Any) -> Response:
    return request("PUT", url, **kwargs)


def delete(url: str, **kwargs: Any) -> Response:
    return request("DELETE", url, **kwargs)


async def arequest(method: str, url: str, **kwargs: Any) -> Response:
    async with AsyncClient() as client:
        return await client.request(method, url, **kwargs)


async def aget(url: str, **kwargs: Any) -> Response:
    return await arequest("GET", url, **kwargs)


async def apost(url: str, **kwargs: Any) -> Response:
    return await arequest("POST", url, **kwargs)


async def aput(url: str, **kwargs: Any) -> Response:
    return await arequest("PUT", url, **kwargs)


async def adelete(url: str, **kwargs: Any) -> Response:
    return await arequest("DELETE", url, **kwargs)
