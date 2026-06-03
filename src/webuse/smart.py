from __future__ import annotations

import json
import re
from dataclasses import asdict, fields
from pathlib import Path
from typing import Any, Protocol

from .exceptions import SmartSelectorError
from .models import SmartSelectorRecord
from .parser import Document, Element


class SmartResolver(Protocol):
    def resolve(self, prompt: str, document: Document, candidates: list[Element]) -> Element | None:
        ...


class SmartSelectorStore:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path or ".webuse/selectors.json")
        self._records: dict[str, SmartSelectorRecord] | None = None

    def _load(self) -> dict[str, SmartSelectorRecord]:
        if self._records is not None:
            return self._records
        if self.path.exists():
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            self._records = {
                key: _record_from_payload(key, value)
                for key, value in payload.items()
            }
        else:
            self._records = {}
        return self._records

    def get(self, key: str) -> SmartSelectorRecord | None:
        return self._load().get(key)

    def save(self, record: SmartSelectorRecord) -> None:
        records = self._load()
        records[record.key] = record
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps({key: asdict(value) for key, value in records.items()}, indent=2),
            encoding="utf-8",
        )


def _record_from_payload(key: str, payload: dict[str, Any]) -> SmartSelectorRecord:
    valid_fields = {field.name for field in fields(SmartSelectorRecord)}
    values = {name: value for name, value in payload.items() if name in valid_fields}
    values.setdefault("key", key)
    values.setdefault("prompt", "")
    return SmartSelectorRecord(**values)


def prompt_key(prompt: str, key: str | None = None) -> str:
    if key:
        return key
    slug = re.sub(r"[^a-z0-9]+", "-", prompt.lower()).strip("-")
    return slug or "selector"


def generate_selector(element: Element) -> str:
    attrs = element.attrs
    element_id = attrs.get("id")
    if element_id:
        return f"#{element_id}"
    classes = attrs.get("class", "").split()
    if classes:
        return f"{element.tag}." + ".".join(classes[:3])
    return element.tag


def generate_xpath(element: Element) -> str:
    attrs = element.attrs
    element_id = attrs.get("id")
    if element_id:
        return f"//*[@id='{element_id}']"
    classes = attrs.get("class", "").split()
    if classes:
        predicates = " and ".join(
            f"contains(concat(' ', normalize-space(@class), ' '), ' {value} ')"
            for value in classes[:3]
        )
        return f"//{element.tag}[{predicates}]"
    href = attrs.get("href")
    if href:
        return f"//{element.tag}[@href={json.dumps(href)}]"
    return f"//{element.tag}"


def _tokenize(prompt: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9]+", prompt.lower()) if len(token) > 1}


def _normalize_text(value: str) -> str:
    return " ".join(value.split()).lower()


def _text_excerpt(element: Element, *, limit: int = 240) -> str:
    text = element.text()
    return text[:limit]


def _metadata_for(element: Element, prompt: str) -> dict[str, Any]:
    text = _text_excerpt(element)
    text_tokens = sorted(_tokenize(f"{prompt} {text}"))
    return {
        "tag": element.tag,
        "attrs": element.attrs,
        "text": text,
        "text_tokens": text_tokens,
        "url": element.base_url,
        "hints": {
            "tag": element.tag,
            "attrs": element.attrs,
            "text": text,
            "text_tokens": text_tokens,
            "url": element.base_url,
        },
    }


def _score(prompt_tokens: set[str], element: Element) -> float:
    haystack = " ".join(
        [
            element.tag,
            element.text(),
            " ".join(f"{key} {value}" for key, value in element.attrs.items()),
        ]
    ).lower()
    score = sum(2.0 for token in prompt_tokens if token in haystack)
    if element.attr("aria-label"):
        score += 1.5
    if element.attr("href"):
        score += 0.5
    if len(element.text()) > 120:
        score -= 0.5
    return score


def _record_tag(record: SmartSelectorRecord) -> str | None:
    return record.tag or record.hints.get("tag")


def _record_attrs(record: SmartSelectorRecord) -> dict[str, Any]:
    attrs = record.attrs or record.hints.get("attrs") or {}
    return attrs if isinstance(attrs, dict) else {}


def _record_text(record: SmartSelectorRecord) -> str:
    text = record.text or record.hints.get("text") or ""
    return text if isinstance(text, str) else ""


def _record_tokens(record: SmartSelectorRecord) -> set[str]:
    tokens = record.text_tokens or record.hints.get("text_tokens") or []
    if isinstance(tokens, list):
        return {str(token) for token in tokens}
    return set()


def _score_against_record(record: SmartSelectorRecord, element: Element) -> float:
    score = 0.0
    record_tag = _record_tag(record)
    if record_tag and element.tag == record_tag:
        score += 3.0

    element_attrs = element.attrs
    for key, value in _record_attrs(record).items():
        if not value:
            continue
        current = element_attrs.get(key)
        if current == value:
            score += 4.0 if key == "id" else 2.0
            continue
        if key == "class":
            old_classes = set(str(value).split())
            new_classes = set(str(current or "").split())
            score += min(len(old_classes & new_classes), 3) * 0.75

    record_text = _normalize_text(_record_text(record))
    element_text = _normalize_text(element.text())
    if record_text and element_text == record_text:
        score += 4.0
    elif record_text and element_text:
        record_tokens = _record_tokens(record) or _tokenize(record_text)
        element_tokens = _tokenize(element_text)
        overlap = record_tokens & element_tokens
        if overlap:
            score += min(len(overlap), 5) * 0.75

    return score


def _recover_from_record(
    record: SmartSelectorRecord,
    candidates: list[Element],
) -> Element | None:
    ranked = sorted(candidates, key=lambda item: _score_against_record(record, item), reverse=True)
    if not ranked:
        return None
    score = _score_against_record(record, ranked[0])
    return ranked[0] if score >= 4.0 else None


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
        model: str = "gpt-4.1-mini",
        api_key: str | None = None,
        base_url: str | None = None,
        client: Any = None,
    ):
        self.model = model
        if client is not None:
            self.client = client
        else:
            from openai import OpenAI

            kwargs = {key: value for key, value in {"api_key": api_key, "base_url": base_url}.items() if value}
            self.client = OpenAI(**kwargs)

    def resolve(self, prompt: str, document: Document, candidates: list[Element]) -> Element | None:
        if not candidates:
            return None
        payload = {
            "prompt": prompt,
            "url": document.base_url,
            "candidates": [_candidate_summary(element, index) for index, element in enumerate(candidates)],
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
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE | re.DOTALL).strip()
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
        return int(value) if isinstance(value, int | str) and str(value).lstrip("-").isdigit() else None
    return None


def resolve_smart(
    document: Document,
    prompt: str,
    *,
    key: str | None = None,
    store: SmartSelectorStore | None = None,
    use_llm: bool = False,
    resolver: SmartResolver | None = None,
) -> Element:
    store = store or SmartSelectorStore()
    record_key = prompt_key(prompt, key)
    record = store.get(record_key)
    candidates = list(document.iter_elements())
    if record:
        for selector in record.selectors:
            match = document.css_first(selector)
            if match:
                return match
        for selector in record.xpath_selectors:
            match = document.xpath_first(selector)
            if match:
                return match
        match = _recover_from_record(record, candidates)
        if match:
            store.save(_record_for_match(record_key, prompt, match))
            return match

    prompt_tokens = _tokenize(prompt)
    ranked = sorted(candidates, key=lambda item: _score(prompt_tokens, item), reverse=True)
    match = ranked[0] if ranked and _score(prompt_tokens, ranked[0]) > 0 else None

    if match is None and use_llm:
        resolver = resolver or LlmSmartResolver()
        match = resolver.resolve(prompt, document, ranked[:20])

    if match is None:
        raise SmartSelectorError(f"Unable to resolve smart selector for prompt: {prompt!r}")

    store.save(_record_for_match(record_key, prompt, match))
    return match


def _record_for_match(record_key: str, prompt: str, match: Element) -> SmartSelectorRecord:
    metadata = _metadata_for(match, prompt)
    return SmartSelectorRecord(
        key=record_key,
        prompt=prompt,
        selectors=[generate_selector(match)],
        xpath_selectors=[generate_xpath(match)],
        tag=metadata["tag"],
        attrs=metadata["attrs"],
        text=metadata["text"],
        text_tokens=metadata["text_tokens"],
        url=metadata["url"],
        hints=metadata["hints"],
    )
