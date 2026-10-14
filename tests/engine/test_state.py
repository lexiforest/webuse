import webuse
from webuse.engine import (
    DefaultRequestHasher,
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
