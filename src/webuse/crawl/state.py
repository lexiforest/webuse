import json
import queue as queue_module
import hashlib
from pathlib import Path
from typing import Any, Iterable, Protocol
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from ..models import CrawlRequest


DEFAULT_IGNORED_QUERY_PARAMS = {
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
    "utm_campaign",
    "utm_content",
    "utm_medium",
    "utm_source",
    "utm_term",
}


class RequestQueue(Protocol):
    def put(self, request: CrawlRequest) -> None: ...

    def pop(self) -> CrawlRequest | None: ...

    def empty(self) -> bool: ...

    def clear(self) -> None: ...


class RequestSeen(Protocol):
    def add(self, request_hash: str) -> bool: ...

    def contains(self, request_hash: str) -> bool: ...


class RequestHasher(Protocol):
    def hash(self, request: CrawlRequest) -> str: ...


def canonical_request_url(
    url: str, *, ignored_query_params: Iterable[str] | None = None
) -> str:
    ignored = {
        value.lower()
        for value in (ignored_query_params or DEFAULT_IGNORED_QUERY_PARAMS)
    }
    parsed = urlparse(url)
    query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if key.lower() not in ignored
    ]
    query.sort()
    path = parsed.path or "/"
    normalized = parsed._replace(
        scheme=parsed.scheme.lower(),
        netloc=parsed.netloc.lower(),
        path=path,
        params="",
        query=urlencode(query, doseq=True),
        fragment="",
    )
    return urlunparse(normalized)


class DefaultRequestHasher:
    def __init__(
        self,
        *,
        include_headers: Iterable[str] | None = None,
        ignored_query_params: Iterable[str] | None = None,
    ) -> None:
        self.include_headers = [header.lower() for header in include_headers or []]
        self.ignored_query_params = ignored_query_params

    def hash(self, request: CrawlRequest) -> str:
        headers = {
            key.lower(): value for key, value in (request.options.headers or {}).items()
        }
        payload: dict[str, Any] = {
            "method": request.method.upper(),
            "url": canonical_request_url(
                request.url, ignored_query_params=self.ignored_query_params
            ),
        }
        if self.include_headers:
            payload["headers"] = {
                key: headers[key]
                for key in sorted(self.include_headers)
                if key in headers
            }
        text = json.dumps(
            payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")
        )
        return hashlib.sha1(text.encode("utf-8")).hexdigest()


class MemoryRequestQueue:
    def __init__(self, requests: list[CrawlRequest] | None = None) -> None:
        self._queue: queue_module.Queue[CrawlRequest] = queue_module.Queue()
        for request in requests or []:
            self.put(request)

    def put(self, request: CrawlRequest) -> None:
        self._queue.put(request)

    def pop(self) -> CrawlRequest | None:
        try:
            return self._queue.get_nowait()
        except queue_module.Empty:
            return None

    def empty(self) -> bool:
        return self._queue.empty()

    def clear(self) -> None:
        while self.pop() is not None:
            pass


class MemoryRequestSeen:
    def __init__(
        self, request_hashes: set[str] | list[str] | tuple[str, ...] | None = None
    ) -> None:
        self._hashes = set(request_hashes or [])

    def add(self, request_hash: str) -> bool:
        if request_hash in self._hashes:
            return False
        self._hashes.add(request_hash)
        return True

    def contains(self, request_hash: str) -> bool:
        return request_hash in self._hashes


class FileRequestQueue:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._queue = MemoryRequestQueue()
        if self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    self._queue.put(CrawlRequest.model_validate_json(line))

    def put(self, request: CrawlRequest) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as file:
            file.write(request.model_dump_json())
            file.write("\n")
        self._queue.put(request)

    def pop(self) -> CrawlRequest | None:
        return self._queue.pop()

    def empty(self) -> bool:
        return self._queue.empty()

    def clear(self) -> None:
        self._queue.clear()


class FileRequestSeen:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._hashes: set[str] = set()
        if self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                payload = json.loads(line)
                if isinstance(payload, str):
                    self._hashes.add(payload)
                elif isinstance(payload, dict) and isinstance(payload.get("hash"), str):
                    self._hashes.add(payload["hash"])
                elif isinstance(payload, dict) and isinstance(payload.get("url"), str):
                    self._hashes.add(payload["url"])

    def add(self, request_hash: str) -> bool:
        if request_hash in self._hashes:
            return False
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as file:
            file.write(json.dumps({"hash": request_hash}, ensure_ascii=True))
            file.write("\n")
        self._hashes.add(request_hash)
        return True

    def contains(self, request_hash: str) -> bool:
        return request_hash in self._hashes


def _redis_client(redis_url: str | None = None, client: Any | None = None) -> Any:
    if client is not None:
        return client
    from redis import Redis

    return Redis.from_url(redis_url or "redis://localhost:6379/0")


def _decode(value: Any) -> str:
    return value.decode("utf-8") if isinstance(value, bytes) else str(value)


class RedisRequestQueue:
    def __init__(
        self,
        key: str = "webuse:requests:queue",
        *,
        redis_url: str | None = None,
        client: Any | None = None,
    ) -> None:
        self.key = key
        self.client = _redis_client(redis_url, client)

    def put(self, request: CrawlRequest) -> None:
        self.client.rpush(self.key, request.model_dump_json())

    def pop(self) -> CrawlRequest | None:
        value = self.client.lpop(self.key)
        if value is None:
            return None
        return CrawlRequest.model_validate_json(_decode(value))

    def empty(self) -> bool:
        return int(self.client.llen(self.key)) == 0

    def clear(self) -> None:
        self.client.delete(self.key)


class RedisRequestSeen:
    def __init__(
        self,
        key: str = "webuse:requests:seen",
        *,
        redis_url: str | None = None,
        client: Any | None = None,
    ) -> None:
        self.key = key
        self.client = _redis_client(redis_url, client)

    def add(self, request_hash: str) -> bool:
        return bool(self.client.sadd(self.key, request_hash))

    def contains(self, request_hash: str) -> bool:
        return bool(self.client.sismember(self.key, request_hash))


__all__ = [
    "DefaultRequestHasher",
    "FileRequestQueue",
    "FileRequestSeen",
    "MemoryRequestQueue",
    "MemoryRequestSeen",
    "RedisRequestQueue",
    "RedisRequestSeen",
    "RequestHasher",
    "RequestQueue",
    "RequestSeen",
    "canonical_request_url",
]
