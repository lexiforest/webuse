import json
import re
from typing import Any, Protocol

from ..llm import create_openai_client, openai_defaults
from ..parser import Document, Element


class SmartResolver(Protocol):
    def resolve(
        self, prompt: str, document: Document, candidates: list[Element]
    ) -> Element | None: ...


def _text_excerpt(element: Element, *, limit: int = 240) -> str:
    text = element.text()
    return text[:limit]


def _candidate_summary(element: Element, index: int) -> dict[str, Any]:
    attrs = {
        key: value
        for key, value in element.attrs.items()
        if key in {"id", "class", "href", "aria-label", "name", "role", "title"}
    }
    return {
        "index": index,
        "tag": element.tag,
        "attrs": attrs,
        "text": _text_excerpt(element, limit=160),
    }


class LlmSmartResolver:
    def __init__(
        self,
        *,
        model: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        client: Any = None,
    ):
        defaults = openai_defaults()
        self.model = model or defaults.model or "gpt-4.1-mini"
        api_key = api_key or defaults.api_key
        base_url = base_url or defaults.base_url
        if client is not None:
            self.client = client
        else:
            self.client = create_openai_client(api_key=api_key, base_url=base_url)

    def resolve(
        self, prompt: str, document: Document, candidates: list[Element]
    ) -> Element | None:
        if not candidates:
            return None
        payload = {
            "prompt": prompt,
            "url": document.base_url,
            "candidates": [
                _candidate_summary(element, index)
                for index, element in enumerate(candidates)
            ],
        }
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Choose the best HTML element for the user's scraping prompt. "
                        "Return only JSON with a zero-based integer field named index, "
                        "or null if none match."
                    ),
                },
                {"role": "user", "content": json.dumps(payload, ensure_ascii=True)},
            ],
            temperature=0,
        )
        content = response.choices[0].message.content or ""
        index = _parse_llm_index(content)
        if index is None or index < 0 or index >= len(candidates):
            return None
        return candidates[index]


def _parse_llm_index(content: str) -> int | None:
    text = content.strip()
    if not text:
        return None
    if text.startswith("```"):
        text = re.sub(
            r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE | re.DOTALL
        ).strip()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"-?\d+", text)
        return int(match.group(0)) if match else None
    if payload is None:
        return None
    if isinstance(payload, int):
        return payload
    if isinstance(payload, dict):
        value = payload.get("index")
        return (
            int(value)
            if isinstance(value, int | str) and str(value).lstrip("-").isdigit()
            else None
        )
    return None
