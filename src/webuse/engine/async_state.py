"""Async request state. Persistence does not include active worker state."""

from collections import deque
from typing import Any, Protocol

from ..models import CrawlRequest
from .state import _decode


class AsyncRequestQueue(Protocol):
    async def put(self, request: CrawlRequest) -> None: ...
    async def pop(self) -> CrawlRequest | None: ...
    async def empty(self) -> bool: ...
    async def clear(self) -> None: ...
    async def size(self) -> int: ...


class AsyncRequestSeen(Protocol):
    async def add(self, request_hash: str) -> bool:
        """Atomically add a hash and return whether it was new."""
        ...

    async def contains(self, request_hash: str) -> bool: ...
    async def size(self) -> int: ...


class AsyncMemoryRequestQueue:
    def __init__(self, requests: list[CrawlRequest] | None = None):
        self._queue = deque(requests or ())

    async def put(self, request: CrawlRequest) -> None:
        self._queue.append(request)

    async def pop(self) -> CrawlRequest | None:
        return self._queue.popleft() if self._queue else None

    async def empty(self) -> bool:
        return not self._queue

    async def clear(self) -> None:
        self._queue.clear()

    async def size(self) -> int:
        return len(self._queue)


class AsyncMemoryRequestSeen:
    def __init__(self, request_hashes=None):
        self._hashes = set(request_hashes or ())

    async def add(self, request_hash: str) -> bool:
        if request_hash in self._hashes:
            return False
        self._hashes.add(request_hash)
        return True

    async def contains(self, request_hash: str) -> bool:
        return request_hash in self._hashes

    async def size(self) -> int:
        return len(self._hashes)


class _AsyncRedisState:
    def __init__(self, key: str, *, redis_url: str | None = None, client: Any = None):
        from redis.asyncio import Redis

        self.key = key
        self._owns_client = client is None
        self.client = (
            client
            if client is not None
            else Redis.from_url(redis_url or "redis://localhost:6379/0")
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self.client.aclose()


class AsyncRedisRequestQueue(_AsyncRedisState):
    def __init__(self, key="webuse:requests:queue", **kwargs):
        super().__init__(key, **kwargs)

    async def put(self, request: CrawlRequest) -> None:
        await self.client.rpush(self.key, request.model_dump_json())

    async def pop(self) -> CrawlRequest | None:
        value = await self.client.lpop(self.key)
        return (
            CrawlRequest.model_validate_json(_decode(value))
            if value is not None
            else None
        )

    async def empty(self) -> bool:
        return await self.size() == 0

    async def clear(self) -> None:
        await self.client.delete(self.key)

    async def size(self) -> int:
        return int(await self.client.llen(self.key))


class AsyncRedisRequestSeen(_AsyncRedisState):
    def __init__(self, key="webuse:requests:seen", **kwargs):
        super().__init__(key, **kwargs)

    async def add(self, request_hash: str) -> bool:
        return bool(await self.client.sadd(self.key, request_hash))

    async def contains(self, request_hash: str) -> bool:
        return bool(await self.client.sismember(self.key, request_hash))

    async def size(self) -> int:
        return int(await self.client.scard(self.key))


async def async_state_info(queue: AsyncRequestQueue, seen: AsyncRequestSeen) -> dict:
    return dict(
        backend=type(queue).__name__,
        queue_size=await queue.size(),
        seen_size=await seen.size(),
    )
