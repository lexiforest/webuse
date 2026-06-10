import json as json_module
from typing import Any
from urllib.parse import urljoin

from .models import CrawlRequest, RequestOptions
from .parser import Document
from .smart import SmartResolver, SmartSelectorStore, extract_smart, resolve_smart


class Response(Document):
    def __init__(
        self,
        *,
        url: str,
        status_code: int,
        reason: str = "",
        headers: dict[str, Any] | None = None,
        cookies: dict[str, Any] | None = None,
        content: bytes = b"",
        encoding: str | None = None,
        history: list[Any] | None = None,
        elapsed: float | None = None,
        raw: Any = None,
    ):
        self.url = url
        self.status_code = status_code
        self.reason = reason
        self.headers = headers or {}
        self.cookies = cookies or {}
        self.content = content
        self.encoding = encoding or "utf-8"
        self.history = history or []
        self.elapsed = elapsed
        self.raw = raw
        super().__init__(content, base_url=url)

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 400

    @property
    def text(self) -> str:
        return self.content.decode(self.encoding or "utf-8", errors="replace")

    def json(self) -> Any:
        return json_module.loads(self.text)

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
                for name in RequestOptions.model_fields
                if name != "extra_kwargs"
            }
            extra_kwargs = dict(merged_options.extra_kwargs)
            for key, value in request_options.items():
                if key in values:
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

    def smart(
        self,
        prompt: str,
        *,
        translate_xpath: bool = False,
        key: str | None = None,
        use_llm: bool = False,
        resolver: SmartResolver | None = None,
        store: SmartSelectorStore | None = None,
        model: str | None = None,
        client: Any = None,
        api_key: str | None = None,
        base_url: str | None = None,
        system_prompt: str | None = None,
        max_chars: int | None = 12000,
        temperature: float = 0,
        **kwargs: Any,
    ) -> list[Any]:
        if not translate_xpath:
            return extract_smart(
                self,
                prompt,
                first=False,
                model=model,
                client=client,
                api_key=api_key,
                base_url=base_url,
                system_prompt=system_prompt,
                max_chars=max_chars,
                temperature=temperature,
                **kwargs,
            )
        return [
            resolve_smart(
                self,
                prompt,
                key=key,
                use_llm=use_llm,
                resolver=resolver,
                store=store,
            )
        ]

    def smart_first(
        self,
        prompt: str,
        *,
        translate_xpath: bool = False,
        key: str | None = None,
        use_llm: bool = False,
        resolver: SmartResolver | None = None,
        store: SmartSelectorStore | None = None,
        model: str | None = None,
        client: Any = None,
        api_key: str | None = None,
        base_url: str | None = None,
        system_prompt: str | None = None,
        max_chars: int | None = 12000,
        temperature: float = 0,
        **kwargs: Any,
    ) -> Any:
        if not translate_xpath:
            return extract_smart(
                self,
                prompt,
                first=True,
                model=model,
                client=client,
                api_key=api_key,
                base_url=base_url,
                system_prompt=system_prompt,
                max_chars=max_chars,
                temperature=temperature,
                **kwargs,
            )
        return resolve_smart(
            self,
            prompt,
            key=key,
            use_llm=use_llm,
            resolver=resolver,
            store=store,
        )

    def smart_all(
        self,
        prompts: list[str],
        *,
        translate_xpath: bool = False,
        use_llm: bool = False,
        resolver: SmartResolver | None = None,
        store: SmartSelectorStore | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        return {
            prompt: self.smart(
                prompt,
                translate_xpath=translate_xpath,
                use_llm=use_llm,
                resolver=resolver,
                store=store,
                **kwargs,
            )
            for prompt in prompts
        }


def from_curl_response(response: Any) -> Response:
    header_items = dict(getattr(response, "headers", {}) or {})
    cookie_items = dict(getattr(response, "cookies", {}) or {})
    encoding = getattr(response, "encoding", None) or "utf-8"
    content = getattr(response, "content", None)
    if content is None:
        content = getattr(response, "text", "").encode(encoding, errors="replace")
    return Response(
        url=str(getattr(response, "url", "")),
        status_code=int(getattr(response, "status_code", 0)),
        reason=str(getattr(response, "reason", "")),
        headers=header_items,
        cookies=cookie_items,
        content=content,
        encoding=encoding,
        history=list(getattr(response, "history", []) or []),
        elapsed=getattr(response, "elapsed", None),
        raw=response,
    )
