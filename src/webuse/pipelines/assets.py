import hashlib
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from curl_cffi import Session
from pydantic import BaseModel

from ..exceptions import PipelineError, PipelineStateError
from .base import Pipeline
from .utils import ensure_pipeline_item, item_to_dict, resolve_path


def _safe_suffix(url: str) -> str:
    suffix = Path(unquote(urlparse(url).path)).suffix.lower()
    if re.fullmatch(r"\.[a-z0-9]{1,16}", suffix or ""):
        return suffix
    return ""


def _asset_path(url: str) -> str:
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()
    return f"{digest}{_safe_suffix(url)}"


def _content(response: Any) -> bytes:
    content = getattr(response, "content", b"")
    if isinstance(content, bytes):
        return content
    if isinstance(content, str):
        return content.encode("utf-8")
    return bytes(content)


def _urls_from_item(item: BaseModel, field: str) -> list[str]:
    value = item_to_dict(item).get(field)
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, Iterable):
        return [str(url) for url in value if url]
    raise PipelineError(
        f"AssetDownloadPipeline field {field!r} must be a URL string or iterable of URL strings"
    )


class AssetDownloadPipeline(Pipeline):
    def __init__(
        self,
        directory: str | Path = "assets",
        *,
        urls_field: str = "asset_urls",
        output_field: str = "assets",
        method: str = "GET",
        headers: dict[str, str] | None = None,
        timeout: float | None = 30,
        success_statuses: Iterable[int] | None = None,
        fail_on_error: bool = True,
        skip_existing: bool = True,
        session: Any | None = None,
        base_dir: str | Path | None = None,
        **request_kwargs: Any,
    ) -> None:
        self.directory = resolve_path(directory, base_dir)
        self.urls_field = urls_field
        self.output_field = output_field
        self.method = method.upper()
        self.headers = headers
        self.timeout = timeout
        self.success_statuses = (
            set(success_statuses) if success_statuses is not None else None
        )
        self.fail_on_error = fail_on_error
        self.skip_existing = skip_existing
        self.request_kwargs = request_kwargs
        self._session = session
        self._owns_session = session is None

    def open_spider(self) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        if self._session is None:
            self._session = Session()
            self._owns_session = True

    def _request_kwargs(self) -> dict[str, Any]:
        kwargs = dict(self.request_kwargs)
        if self.headers is not None:
            kwargs["headers"] = self.headers
        if self.timeout is not None:
            kwargs["timeout"] = self.timeout
        return kwargs

    def _download(self, url: str) -> dict[str, Any]:
        if self._session is None:
            raise PipelineStateError("AssetDownloadPipeline is not open")
        self.directory.mkdir(parents=True, exist_ok=True)
        relative_path = _asset_path(url)
        path = self.directory / relative_path
        if self.skip_existing and path.exists():
            content = path.read_bytes()
            return {
                "url": url,
                "path": relative_path,
                "checksum": hashlib.sha1(content).hexdigest(),
                "size": len(content),
                "status": "cached",
            }

        response = self._session.request(self.method, url, **self._request_kwargs())
        status_code = getattr(response, "status_code", None)
        ok = 200 <= status_code < 300 if isinstance(status_code, int) else False
        if self.success_statuses is not None:
            ok = status_code in self.success_statuses
        if not ok:
            if self.fail_on_error:
                raise PipelineError(
                    f"AssetDownloadPipeline {self.method} {url} returned HTTP {status_code}"
                )
            return {
                "url": url,
                "path": None,
                "checksum": None,
                "size": 0,
                "status": status_code,
            }

        content = _content(response)
        path.write_bytes(content)
        return {
            "url": url,
            "path": relative_path,
            "checksum": hashlib.sha1(content).hexdigest(),
            "size": len(content),
            "status": "downloaded",
        }

    def process_item(self, item: BaseModel) -> BaseModel:
        item = ensure_pipeline_item(item)
        assets = [self._download(url) for url in _urls_from_item(item, self.urls_field)]
        if not assets:
            return item
        return item.model_copy(update={self.output_field: assets})

    def close_spider(self) -> None:
        if (
            self._session is not None
            and self._owns_session
            and hasattr(self._session, "close")
        ):
            self._session.close()
        self._session = None


__all__ = ["AssetDownloadPipeline"]
