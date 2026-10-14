"""Declarative extraction and adapters for response-handler results."""

from __future__ import annotations

import inspect
from collections.abc import AsyncIterable, AsyncIterator, Iterable
from contextlib import aclosing
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

from ..exceptions import ConfigError
from ..models import CrawlRequest
from .schema import ExtractionRules, FieldRule, ItemSpec, compile_extraction

if TYPE_CHECKING:
    from .parser import Document


def element_value(element: Any, attr: str | None) -> Any:
    if attr:
        return element.attr(attr)
    return element.text()


def extract_by_css(scope: Any, rule: FieldRule) -> Any:
    selector = rule.css
    attr = rule.attr
    if selector in {".", "&"}:
        if rule.all:
            return [element_value(scope, attr)]
        return element_value(scope, attr)
    if rule.all:
        matches = scope.css(selector)
        return [element_value(match, attr) for match in matches]
    match = scope.css_find(selector)
    return element_value(match, attr) if match else None


def convert_to_document(scope: Any) -> Document:
    from .parser import Document, Element

    if isinstance(scope, Element):
        return Document(scope.html(), url=scope.base_url)
    return scope


def extract_by_llm_find(scope: Any, rule: FieldRule) -> Any:
    match = convert_to_document(scope).llm_find(rule.llm_find)
    return element_value(match, rule.attr)


def extract_by_css_find(scope: Any, rule: FieldRule) -> Any:
    match = scope.css_find(rule.css_find)
    return element_value(match, rule.attr) if match is not None else None


def extract_by_llm_extract(scope: Any, rule: FieldRule) -> Any:
    document = convert_to_document(scope)
    extractor = document.llm_extract if rule.all else document.llm_extract_first
    return extractor(rule.llm_extract)


def extract_item(scope: Any, fields: dict[str, FieldRule]) -> dict[str, Any]:
    item: dict[str, Any] = {}
    for key, rule in fields.items():
        if rule.css is not None:
            item[key] = extract_by_css(scope, rule)
        elif rule.css_find is not None:
            item[key] = extract_by_css_find(scope, rule)
        elif rule.llm_extract is not None:
            item[key] = extract_by_llm_extract(scope, rule)
        else:
            item[key] = extract_by_llm_find(scope, rule)
    return item


def select_scopes(response: Any, extract: ItemSpec) -> list[Any]:
    item_css = extract.item_css
    if item_css:
        return response.css(item_css)
    return [response]


def extract_spec_items(response: Any, name: str, spec: ItemSpec) -> list[Any]:
    fields = spec.fields
    if not fields:
        return []
    items = [extract_item(scope, fields) for scope in select_scopes(response, spec)]
    item_type = spec.type or name
    item_model = spec.item_model
    for item in items:
        item.setdefault("_type", item_type)
        if item_model is not None:
            item.setdefault("_item_model", item_model)
    return items


def extract_specs_for_response(
    response: Any, extract: ExtractionRules
) -> list[tuple[str, ItemSpec]]:
    request = getattr(response, "crawl_request", None)
    category = getattr(request, "category", None)
    category_key = str(category) if category else "default"
    selected = extract.root.get(category_key)
    if selected is None:
        selected = extract.root.get("*")
    if selected is None:
        return []

    return list(selected.items())


def extract_handles_category(extract: Any, category: str | None) -> bool:
    if not isinstance(extract, ExtractionRules):
        return False
    category_key = str(category) if category else "default"
    return category_key in extract.root or "*" in extract.root


def extract_items(response: Any, extract: Any) -> list[Any]:
    extract = compile_extraction(extract)
    if extract is None:
        return []
    if not isinstance(extract, ExtractionRules):
        raise ConfigError("extract_items requires declarative extraction rules")
    items: list[Any] = []
    for name, spec in extract_specs_for_response(response, extract):
        items.extend(extract_spec_items(response, name, spec))
    return items


@dataclass
class ParseResult:
    """Internal response-handler contract consumed by the engines."""

    items: list[Any] = field(default_factory=list)
    requests: list[CrawlRequest] = field(default_factory=list)


def normalize_parse_result(value: Any) -> ParseResult:
    if isinstance(value, ParseResult):
        return value
    parsed = ParseResult()

    def add_request(request: Any) -> None:
        parsed.requests.append(
            request
            if isinstance(request, CrawlRequest)
            else CrawlRequest(url=str(request))
        )

    if value is None:
        return parsed
    if isinstance(value, tuple) and len(value) == 2:
        items, requests = value
        if items is not None:
            parsed.items.extend(items if isinstance(items, list) else [items])
        if requests is not None:
            for request in requests if isinstance(requests, list) else [requests]:
                add_request(request)
        return parsed
    if not isinstance(
        value, (str, bytes, dict, BaseModel, CrawlRequest)
    ) and isinstance(value, Iterable):
        entries = value
    else:
        entries = [value]
    for entry in entries:
        if isinstance(entry, (CrawlRequest, str)):
            add_request(entry)
        else:
            parsed.items.append(entry)
    return parsed


def extract_response(response: Any, extract: Any) -> ParseResult:
    value = extract(response) if callable(extract) else extract_items(response, extract)
    if inspect.isawaitable(value) or isinstance(value, AsyncIterable):
        close = getattr(value, "close", None)
        if close is not None:
            close()
        raise TypeError("Async parse results require acrawl() or AsyncSpider.run()")
    return normalize_parse_result(value)


async def aextract_items(response: Any, extract: Any) -> AsyncIterator[Any]:
    """Extract one item at a time, awaiting model-backed fields."""
    extract = compile_extraction(extract)
    if extract is None:
        return
    if not isinstance(extract, ExtractionRules):
        raise ConfigError("aextract_items requires declarative extraction rules")
    for name, spec in extract_specs_for_response(response, extract):
        if not spec.fields:
            continue
        for scope in select_scopes(response, spec):
            item = {}
            for key, rule in spec.fields.items():
                if rule.css is not None:
                    item[key] = extract_by_css(scope, rule)
                elif rule.css_find is not None:
                    item[key] = extract_by_css_find(scope, rule)
                elif rule.llm_extract is not None:
                    document = convert_to_document(scope)
                    extractor = (
                        document.allm_extract
                        if rule.all
                        else document.allm_extract_first
                    )
                    item[key] = await extractor(rule.llm_extract)
                else:
                    match = await convert_to_document(scope).allm_find(rule.llm_find)
                    item[key] = element_value(match, rule.attr)
            item.setdefault("_type", spec.type or name)
            if spec.item_model is not None:
                item.setdefault("_item_model", spec.item_model)
            yield item


async def _aiter_values(value: Any) -> AsyncIterator[Any]:
    """Iterate a scalar or iterable, closing generators on early exit."""
    if inspect.isawaitable(value):
        value = await value
    try:
        if isinstance(value, AsyncIterable):
            async for entry in value:
                yield entry
        elif isinstance(value, Iterable) and not isinstance(
            value, (str, bytes, dict, BaseModel, CrawlRequest)
        ):
            for entry in value:
                yield entry
        elif value is not None:
            yield value
    finally:
        if inspect.isasyncgen(value):
            await value.aclose()
        elif inspect.isgenerator(value):
            value.close()


@dataclass
class AsyncParseResult:
    items: AsyncIterator[Any]
    requests: list[CrawlRequest] = field(default_factory=list)


async def aextract_response(response: Any, extract: Any) -> AsyncParseResult:
    value = (
        extract(response) if callable(extract) else aextract_items(response, extract)
    )
    if inspect.isawaitable(value):
        value = await value
    if isinstance(value, AsyncParseResult):
        return value
    requests: list[CrawlRequest] = []

    async def items():
        if isinstance(value, ParseResult) or (
            isinstance(value, tuple) and len(value) == 2
        ):
            item_values, request_values = (
                (value.items, value.requests)
                if isinstance(value, ParseResult)
                else value
            )
            async with aclosing(_aiter_values(item_values)) as entries:
                async for item in entries:
                    yield item
            async with aclosing(_aiter_values(request_values)) as entries:
                async for request in entries:
                    requests.append(
                        request
                        if isinstance(request, CrawlRequest)
                        else CrawlRequest(url=str(request))
                    )
        else:
            async with aclosing(_aiter_values(value)) as entries:
                async for entry in entries:
                    if isinstance(entry, (CrawlRequest, str)):
                        requests.append(
                            entry
                            if isinstance(entry, CrawlRequest)
                            else CrawlRequest(url=entry)
                        )
                    else:
                        yield entry

    return AsyncParseResult(items(), requests)
