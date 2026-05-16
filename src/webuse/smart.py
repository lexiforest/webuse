from __future__ import annotations

import json
import re
from dataclasses import asdict
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
                key: SmartSelectorRecord(**value)
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
    return f"//{element.tag}"


def _tokenize(prompt: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9]+", prompt.lower()) if len(token) > 1}


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
    if record:
        for selector in record.selectors:
            match = document.css_first(selector)
            if match:
                return match
        for selector in record.xpath_selectors:
            match = document.xpath_first(selector)
            if match:
                return match

    candidates = list(document.iter_elements())
    prompt_tokens = _tokenize(prompt)
    ranked = sorted(candidates, key=lambda item: _score(prompt_tokens, item), reverse=True)
    match = ranked[0] if ranked and _score(prompt_tokens, ranked[0]) > 0 else None

    if match is None and use_llm and resolver is not None:
        match = resolver.resolve(prompt, document, ranked[:20])

    if match is None:
        raise SmartSelectorError(f"Unable to resolve smart selector for prompt: {prompt!r}")

    store.save(
        SmartSelectorRecord(
            key=record_key,
            prompt=prompt,
            selectors=[generate_selector(match)],
            xpath_selectors=[generate_xpath(match)],
            hints={"tag": match.tag, "attrs": match.attrs},
        )
    )
    return match
