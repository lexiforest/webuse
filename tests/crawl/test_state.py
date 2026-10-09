import webuse
from webuse.crawl import (
    DefaultRequestHasher,
    FileRequestQueue,
    FileRequestSeen,
    RedisRequestQueue,
    RedisRequestSeen,
    canonical_request_url,
)
from webuse.models import CrawlRequest

from crawl_helpers import (
    FakeRedis,
)


def test_canonical_request_url_sorts_params_and_removes_tracking_params():
    assert (
        canonical_request_url("HTTPS://Example.COM/path?b=2&utm_source=x&a=1#frag")
        == "https://example.com/path?a=1&b=2"
    )


def test_default_request_hasher_uses_method_and_canonical_url_by_default():
    hasher = DefaultRequestHasher()
    first = CrawlRequest(
        url="https://example.com/path?b=2&utm_source=x&a=1", method="GET"
    )
    second = CrawlRequest(url="https://example.com/path?a=1&b=2", method="GET")
    third = CrawlRequest(url="https://example.com/path?a=1&b=2", method="POST")

    assert hasher.hash(first) == hasher.hash(second)
    assert hasher.hash(first) != hasher.hash(third)


def test_default_request_hasher_can_include_headers():
    plain = DefaultRequestHasher()
    with_headers = DefaultRequestHasher(include_headers=["Accept-Language"])
    first = CrawlRequest(
        url="https://example.com",
        options=webuse.RequestOptions(headers={"Accept-Language": "en"}),
    )
    second = CrawlRequest(
        url="https://example.com",
        options=webuse.RequestOptions(headers={"Accept-Language": "fr"}),
    )

    assert plain.hash(first) == plain.hash(second)
    assert with_headers.hash(first) != with_headers.hash(second)


def test_file_request_queue_persists_jsonl(tmp_path):
    path = tmp_path / "queue.jsonl"
    queue = FileRequestQueue(path)
    request = CrawlRequest(url="https://example.com", category="detail")

    queue.put(request)
    assert path.read_text(encoding="utf-8").count("\n") == 1
    loaded = FileRequestQueue(path)

    assert loaded.pop() == request
    assert path.read_text(encoding="utf-8") == ""
    assert FileRequestQueue(path).empty()


def test_file_queue_persists_pending_order_and_clear(tmp_path):
    path = tmp_path / "queue.jsonl"
    queue = FileRequestQueue(path)
    first = CrawlRequest(url="https://example.com/first")
    second = CrawlRequest(url="https://example.com/second")
    queue.put(first)
    queue.put(second)
    assert queue.pop() == first
    queue = FileRequestQueue(path)
    assert queue.pop() == second
    queue.put(first)
    queue.clear()
    assert FileRequestQueue(path).pop() is None


def test_file_queue_failed_replace_keeps_previous_state(tmp_path, monkeypatch):
    import importlib

    state = importlib.import_module("webuse.crawl.state")

    path = tmp_path / "queue.jsonl"
    queue = FileRequestQueue(path)
    request = CrawlRequest(url="https://example.com")
    queue.put(request)

    def fail(*args):
        raise OSError("disk error")

    monkeypatch.setattr(state.os, "replace", fail)
    import pytest

    with pytest.raises(OSError):
        queue.pop()
    assert len(queue) == 1
    assert len(FileRequestQueue(path)) == 1
    assert list(tmp_path.iterdir()) == [path]


def test_file_request_seen_persists_jsonl(tmp_path):
    path = tmp_path / "seen.jsonl"
    seen = FileRequestSeen(path)

    assert seen.add("hash-1")
    assert not seen.add("hash-1")
    assert FileRequestSeen(path).contains("hash-1")
    assert path.read_text(encoding="utf-8").splitlines() == ['{"hash": "hash-1"}']


def test_redis_request_queue_and_seen_use_list_and_set():
    client = FakeRedis()
    queue = RedisRequestQueue("queue", client=client)
    seen = RedisRequestSeen("seen", client=client)
    request = CrawlRequest(url="https://example.com")

    queue.put(request)

    assert not queue.empty()
    assert queue.pop() == request
    assert queue.empty()
    assert seen.add("hash-1")
    assert not seen.add("hash-1")
    assert seen.contains("hash-1")
