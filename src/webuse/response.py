from typing import Any
from urllib.parse import urljoin

from curl_cffi import Curl
from curl_cffi.requests import Response as CurlResponse
from curl_cffi.requests.models import Request

from .models import CrawlRequest, RequestOptions
from .parser import Document


class Response(CurlResponse, Document):
    """Native HTTP response with lazy HTML parsing and crawler helpers."""

    def __init__(
        self,
        curl: Curl | None = None,
        request: Request | None = None,
        *,
        url: str = "",
        status_code: int = 200,
        content: bytes = b"",
        encoding: str | None = None,
    ):
        super().__init__(curl, request)
        # Optional body/URL arguments also support offline parsing and fixtures.
        self.url = url
        self.status_code = status_code
        self.content = content
        self.ok = 200 <= status_code < 400
        if encoding is not None:
            self.encoding = encoding
        self._tree = None
        self.crawl_request: CrawlRequest | None = None

    def follow(
        self,
        url: str,
        *,
        method: str = "GET",
        options: RequestOptions | None = None,
        category: str | None = None,
        meta: dict[str, Any] | None = None,
        **request_options: Any,
    ) -> CrawlRequest:
        merged_options = options or RequestOptions()
        if request_options:
            values = {
                name: getattr(merged_options, name)
                for name in merged_options.model_fields_set
                if name != "extra_kwargs"
            }
            extra_kwargs = dict(merged_options.extra_kwargs)
            for key, value in request_options.items():
                if key in RequestOptions.model_fields and key != "extra_kwargs":
                    values[key] = value
                else:
                    extra_kwargs[key] = value
            values["extra_kwargs"] = extra_kwargs
            merged_options = RequestOptions.model_validate(values)
        return CrawlRequest(
            url=urljoin(self.url, url),
            method=method,
            options=merged_options,
            category=category,
            meta=meta or {},
        )
