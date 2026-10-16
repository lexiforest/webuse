"""Declarative extraction and adapters for response-handler results."""

from __future__ import annotations

import inspect
from collections.abc import AsyncIterable, AsyncIterator, Iterable
from contextlib import aclosing
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

from ..exceptions import ConfigError, ExtractionError
from ..models import CrawlRequest
from .schema import (
    ExtractionRules,
    FieldRule,
    ItemSpec,
    StructuredValue,
    compile_extraction,
)


def element_value(element: Any, attr: str | None) -> Any:
    if attr:
        return element.attr(attr)
    return element.text()


def selected_value(rule, matches):
    values = [element_value(match, rule.attr) for match in matches]
    if rule.required and (not values or any(value is None for value in values)):
        raise ExtractionError(f"Required field has no value: {rule.css or rule.llm}")
    return values if rule.all else values[0] if values else None


def extract_field(scope, rule: FieldRule):
    if isinstance(rule, StructuredValue):
        return scope.llm_extract(rule.llm_extract, schema=rule._output)
    return selected_value(rule, rule.select(scope))


async def aextract_field(scope, rule: FieldRule):
    if isinstance(rule, StructuredValue):
        return await scope.allm_extract(rule.llm_extract, schema=rule._output)
    return selected_value(rule, await rule.aselect(scope))


def select_scopes(response: Any, spec: ItemSpec) -> list[Any]:
    return response.find_all(css=spec.item_css) if spec.item_css else [response]


def record_items(value, name, spec):
    values = value if isinstance(value, list) else [value]
    items = []
    for item in values:
        if isinstance(item, BaseModel):
            item = item.model_dump()
        if not isinstance(item, dict):
            raise ExtractionError(
                "Record extraction must return an object or an array of objects"
            )
        item = dict(item)
        item.setdefault("_type", spec.type or name)
        if spec.item_model is not None:
            item.setdefault("_item_model", spec.item_model)
        items.append(item)
    return items


def extract_spec_items(response: Any, name: str, spec: ItemSpec) -> list[Any]:
    items = []
    for scope in select_scopes(response, spec):
        if spec.llm_extract is not None:
            value = scope.llm_extract(spec.llm_extract, schema=spec._output)
        elif spec.fields:
            value = {
                key: extract_field(scope, rule) for key, rule in spec.fields.items()
            }
        else:
            continue
        items.extend(record_items(value, name, spec))
    return items


def extract_specs_for_response(
    response: Any, extract: ExtractionRules
) -> list[tuple[str, ItemSpec]]:
    request = getattr(response, "crawl_request", None)
    page_type = getattr(request, "page_type", None)
    page_type_key = str(page_type) if page_type else "default"
    selected = extract.root.get(page_type_key)
    if selected is None:
        selected = extract.root.get("*")
    if selected is None:
        return []

    return list(selected.items())


def extract_handles_page_type(extract: Any, page_type: str | None) -> bool:
    if not isinstance(extract, ExtractionRules):
        return False
    page_type_key = str(page_type) if page_type else "default"
    return page_type_key in extract.root or "*" in extract.root


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
        for scope in select_scopes(response, spec):
            if spec.llm_extract is not None:
                value = await scope.allm_extract(spec.llm_extract, schema=spec._output)
            elif spec.fields:
                value = {
                    key: await aextract_field(scope, rule)
                    for key, rule in spec.fields.items()
                }
            else:
                continue
            for item in record_items(value, name, spec):
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
