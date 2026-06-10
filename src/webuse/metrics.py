from time import perf_counter
from typing import Any

import ustats

from .signals import SignalBus


class UStatsMetrics:
    def __init__(
        self, *, client: Any = ustats, tags: dict[str, str] | None = None
    ) -> None:
        self.client = client
        self.tags = tags or {}
        self._crawl_started_at: float | None = None
        self._request_started_at: dict[int, float] = {}
        self._parse_started_at: dict[int, float] = {}
        self._pipeline_started_at: dict[tuple[int, str], float] = {}

    def bind(self, signals: SignalBus) -> "UStatsMetrics":
        signals.connect("crawl_started", self.crawl_started)
        signals.connect("crawl_finished", self.crawl_finished)
        signals.connect("crawl_error", self.crawl_error)
        signals.connect("state_loaded", self.state_loaded)
        signals.connect("state_updated", self.state_updated)
        signals.connect("request_queued", self.request_queued)
        signals.connect("request_skipped", self.request_skipped)
        signals.connect("request_before_downloader", self.request_before_downloader)
        signals.connect("request_after_downloader", self.request_after_downloader)
        signals.connect("request_error", self.request_error)
        signals.connect("response_received", self.response_received)
        signals.connect("parse_started", self.parse_started)
        signals.connect("parse_finished", self.parse_finished)
        signals.connect("parse_error", self.parse_error)
        signals.connect("pipeline_started", self.pipeline_started)
        signals.connect("pipeline_finished", self.pipeline_finished)
        signals.connect("pipeline_error", self.pipeline_error)
        signals.connect("item_extracted", self.item_extracted)
        signals.connect("item_processed", self.item_processed)
        signals.connect("item_dropped", self.item_dropped)
        signals.connect("item_error", self.item_error)
        return self

    def _tags(self, **tags: Any) -> dict[str, str]:
        merged = dict(self.tags)
        for key, value in tags.items():
            if value is not None:
                merged[key] = str(value)
        return merged

    def _counter(self, name: str, value: int | float = 1, **tags: Any) -> None:
        self.client.counter(name, value, tags=self._tags(**tags))

    def _gauge(self, name: str, value: int | float, **tags: Any) -> None:
        self.client.gauge(name, value, tags=self._tags(**tags))

    def _timer(self, name: str, value: float, **tags: Any) -> None:
        self.client.timer(name, value, tags=self._tags(**tags))

    def crawl_started(self, **kwargs: Any) -> None:
        self._crawl_started_at = perf_counter()
        self._counter("crawl_started")
        self.client.incr("crawl_in_flight", 1, tags=self._tags())

    def crawl_finished(self, reason: str | None = None, **kwargs: Any) -> None:
        self._counter("crawl_finished", reason=reason or "finished")
        self.client.decr("crawl_in_flight", 1, tags=self._tags())
        if self._crawl_started_at is not None:
            self._timer(
                "crawl_duration",
                perf_counter() - self._crawl_started_at,
                reason=reason or "finished",
            )
            self._crawl_started_at = None

    def crawl_error(self, error: Exception | None = None, **kwargs: Any) -> None:
        self._counter("crawl_error", error=error.__class__.__name__ if error else None)

    def state_loaded(
        self,
        backend: str | None = None,
        queue_size: int | None = None,
        seen_size: int | None = None,
        **kwargs: Any,
    ) -> None:
        self._counter("state_loaded", backend=backend)
        if queue_size is not None:
            self._gauge("state_queue_size", queue_size, backend=backend)
        if seen_size is not None:
            self._gauge("state_seen_size", seen_size, backend=backend)

    def state_updated(
        self, backend: str | None = None, queue_size: int | None = None, **kwargs: Any
    ) -> None:
        self._counter("state_updated", backend=backend)
        if queue_size is not None:
            self._gauge("state_queue_size", queue_size, backend=backend)

    def request_queued(self, source: str | None = None, **kwargs: Any) -> None:
        self._counter("request_queued", source=source)

    def request_skipped(self, reason: str | None = None, **kwargs: Any) -> None:
        self._counter("request_skipped", reason=reason)

    def request_before_downloader(self, request: Any = None, **kwargs: Any) -> None:
        if request is not None:
            self._request_started_at[id(request)] = perf_counter()
        self.client.incr("request_in_flight", 1, tags=self._tags())

    def request_after_downloader(
        self,
        request: Any = None,
        success: bool | None = None,
        error: Exception | None = None,
        **kwargs: Any,
    ) -> None:
        self.client.decr("request_in_flight", 1, tags=self._tags())
        self._counter(
            "request_finished",
            success=str(bool(success)).lower() if success is not None else None,
            error=error.__class__.__name__ if error else None,
        )
        if request is not None:
            started_at = self._request_started_at.pop(id(request), None)
            if started_at is not None:
                self._timer(
                    "request_duration",
                    perf_counter() - started_at,
                    success=str(bool(success)).lower() if success is not None else None,
                )

    def request_error(self, error: Exception | None = None, **kwargs: Any) -> None:
        self._counter(
            "request_error", error=error.__class__.__name__ if error else None
        )

    def response_received(self, response: Any = None, **kwargs: Any) -> None:
        status = getattr(response, "status_code", None)
        self._counter("response_received", status=status)
        content = getattr(response, "content", None)
        if content is not None:
            self._gauge("response_bytes", len(content), status=status)

    def parse_started(self, response: Any = None, **kwargs: Any) -> None:
        if response is not None:
            self._parse_started_at[id(response)] = perf_counter()
        self.client.incr("parse_in_flight", 1, tags=self._tags())

    def parse_finished(
        self,
        response: Any = None,
        items: list[Any] | None = None,
        followups: list[Any] | None = None,
        **kwargs: Any,
    ) -> None:
        self.client.decr("parse_in_flight", 1, tags=self._tags())
        self._counter("parse_finished")
        self._gauge("parse_items", len(items or []))
        self._gauge("parse_followups", len(followups or []))
        if response is not None:
            started_at = self._parse_started_at.pop(id(response), None)
            if started_at is not None:
                self._timer("parse_duration", perf_counter() - started_at)

    def parse_error(self, error: Exception | None = None, **kwargs: Any) -> None:
        self._counter("parse_error", error=error.__class__.__name__ if error else None)

    def pipeline_started(
        self, pipeline: Any = None, item: Any = None, **kwargs: Any
    ) -> None:
        if pipeline is not None and item is not None:
            self._pipeline_started_at[(id(item), pipeline.__class__.__name__)] = (
                perf_counter()
            )
        self.client.incr(
            "pipeline_in_flight",
            1,
            tags=self._tags(pipeline=pipeline.__class__.__name__ if pipeline else None),
        )

    def pipeline_finished(
        self, pipeline: Any = None, item: Any = None, **kwargs: Any
    ) -> None:
        pipeline_name = pipeline.__class__.__name__ if pipeline else None
        self.client.decr(
            "pipeline_in_flight", 1, tags=self._tags(pipeline=pipeline_name)
        )
        self._counter("pipeline_finished", pipeline=pipeline_name)
        if pipeline is not None:
            key = next(
                (
                    candidate
                    for candidate in self._pipeline_started_at
                    if candidate[1] == pipeline.__class__.__name__
                ),
                None,
            )
            if key is not None:
                started_at = self._pipeline_started_at.pop(key)
                self._timer(
                    "pipeline_duration",
                    perf_counter() - started_at,
                    pipeline=pipeline_name,
                )

    def pipeline_error(
        self, pipeline: Any = None, error: Exception | None = None, **kwargs: Any
    ) -> None:
        self._counter(
            "pipeline_error",
            pipeline=pipeline.__class__.__name__ if pipeline else None,
            error=error.__class__.__name__ if error else None,
        )

    def item_extracted(self, item: Any = None, **kwargs: Any) -> None:
        self._counter(
            "item_extracted",
            item_type=item.__class__.__name__ if item is not None else None,
        )

    def item_processed(self, item: Any = None, **kwargs: Any) -> None:
        self._counter(
            "item_processed",
            item_type=item.__class__.__name__ if item is not None else None,
        )

    def item_dropped(
        self, item: Any = None, error: Exception | None = None, **kwargs: Any
    ) -> None:
        self._counter(
            "item_dropped",
            item_type=item.__class__.__name__ if item is not None else None,
            error=error.__class__.__name__ if error else None,
        )

    def item_error(
        self, item: Any = None, error: Exception | None = None, **kwargs: Any
    ) -> None:
        self._counter(
            "item_error",
            item_type=item.__class__.__name__ if item is not None else None,
            error=error.__class__.__name__ if error else None,
        )


def attach_metrics(
    signals: SignalBus, *, client: Any = ustats, tags: dict[str, str] | None = None
) -> UStatsMetrics:
    return UStatsMetrics(client=client, tags=tags).bind(signals)


__all__ = ["UStatsMetrics", "attach_metrics"]
