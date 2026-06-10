from collections.abc import Iterable
from typing import Any

from curl_cffi import Session
from pydantic import BaseModel

from ..exceptions import PipelineError, PipelineStateError
from .base import Pipeline
from .utils import ensure_pipeline_item, item_to_dict


def _response_text(response: Any) -> str:
    text = getattr(response, "text", "")
    if not isinstance(text, str):
        return ""
    return text[:200]


class WebhookPipeline(Pipeline):
    def __init__(
        self,
        url: str,
        *,
        method: str = "POST",
        headers: dict[str, str] | None = None,
        timeout: float | None = 10,
        success_statuses: Iterable[int] | None = None,
        fail_on_error: bool = True,
        session: Any | None = None,
        base_dir: Any = None,
        **request_kwargs: Any,
    ) -> None:
        _ = base_dir
        if "json" in request_kwargs:
            raise PipelineError(
                "WebhookPipeline sends the item as JSON; do not pass a json request kwarg"
            )
        self.url = url
        self.method = method.upper()
        self.headers = headers
        self.timeout = timeout
        self.success_statuses = (
            set(success_statuses) if success_statuses is not None else None
        )
        self.fail_on_error = fail_on_error
        self.request_kwargs = request_kwargs
        self._session = session
        self._owns_session = session is None

    def open_spider(self) -> None:
        if self._session is None:
            self._session = Session()
            self._owns_session = True

    def process_item(self, item: BaseModel) -> BaseModel:
        if self._session is None:
            raise PipelineStateError("WebhookPipeline is not open")
        item = ensure_pipeline_item(item)
        kwargs = dict(self.request_kwargs)
        if self.headers is not None:
            kwargs["headers"] = self.headers
        if self.timeout is not None:
            kwargs["timeout"] = self.timeout

        response = self._session.request(
            self.method,
            self.url,
            json=item_to_dict(item),
            **kwargs,
        )
        status_code = getattr(response, "status_code", None)
        ok = 200 <= status_code < 300 if isinstance(status_code, int) else False
        if self.success_statuses is not None:
            ok = status_code in self.success_statuses
        if self.fail_on_error and not ok:
            body = _response_text(response)
            suffix = f": {body}" if body else ""
            raise PipelineError(
                f"WebhookPipeline {self.method} {self.url} returned HTTP {status_code}{suffix}"
            )
        return item

    def close_spider(self) -> None:
        if (
            self._session is not None
            and self._owns_session
            and hasattr(self._session, "close")
        ):
            self._session.close()
        self._session = None


__all__ = ["WebhookPipeline"]
