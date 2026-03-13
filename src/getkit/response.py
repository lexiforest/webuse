from __future__ import annotations

import json as json_module
from typing import Any

from .parser import Document
from .smart import SmartResolver, SmartSelectorStore, resolve_smart


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

    def smart(
        self,
        prompt: str,
        *,
        key: str | None = None,
        use_llm: bool = False,
        resolver: SmartResolver | None = None,
        store: SmartSelectorStore | None = None,
    ):
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
        use_llm: bool = False,
        resolver: SmartResolver | None = None,
        store: SmartSelectorStore | None = None,
    ) -> dict[str, Any]:
        return {
            prompt: self.smart(prompt, use_llm=use_llm, resolver=resolver, store=store)
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
