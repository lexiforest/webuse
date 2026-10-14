import argparse
import csv
import json
import sys
from contextlib import ExitStack
from pathlib import Path
from typing import Any

from ..http import request
from ..exceptions import SmartSelectorError
from ..llm import openai_defaults
from ..extract import (
    LlmSmartResolver,
    SMART_EXTRACTION_SYSTEM_PROMPT,
    SMART_FIRST_EXTRACTION_SYSTEM_PROMPT,
)
from .utils import (
    _pair,
    _pairs,
    add_request_args,
    cli_request_options,
    json_arg,
    print_jsonl,
)


def _body_options(args: argparse.Namespace, stack: ExitStack) -> dict[str, Any]:
    body_kinds = [
        bool(getattr(args, "data", None)),
        bool(getattr(args, "json_body", None)),
        bool(getattr(args, "form", None)),
    ]
    if sum(body_kinds) > 1:
        raise SystemExit("Use only one of --data, --json, or --form")
    options: dict[str, Any] = {}
    if getattr(args, "json_body", None):
        options["json"] = json_arg(args.json_body, "--json")
    elif getattr(args, "form", None):
        options["data"] = _pairs(args.form)
    elif getattr(args, "data", None):
        options["data"] = args.data
    if getattr(args, "file", None):
        files: dict[str, Any] = {}
        for value in args.file:
            key, path = _pair(value, "--file")
            files[key] = stack.enter_context(Path(path).open("rb"))
        options["files"] = files
    return options


def _element_value(element: Any, attr: str | None) -> Any:
    if element is None:
        return None
    return element.attr(attr) if attr else element.text()


def _print_extraction(
    *,
    args: argparse.Namespace,
    response: Any,
    values: Any,
    selector: str,
    output_shape: str,
    field: str,
    first: bool,
) -> None:
    if args.csv:
        if output_shape == "item":
            rows = (
                [{field: value} for value in values]
                if not first and isinstance(values, list)
                else [{field: values}]
            )
        elif not first and isinstance(values, list):
            rows = [
                {"url": response.url, "match": value, "selector": selector}
                for value in values
            ]
        else:
            rows = [
                {
                    "url": response.url,
                    "match" if first else "matches": values,
                    "selector": selector,
                }
            ]
        _print_fetch_csv(rows)
        return
    if args.jsonl and not first and isinstance(values, list):
        if output_shape == "item":
            print_jsonl([{field: value} for value in values])
        else:
            print_jsonl(
                [
                    {"url": response.url, "match": value, "selector": selector}
                    for value in values
                ]
            )
        return
    key = "match" if first else "matches"
    if output_shape == "item":
        _print_fetch_json({field: values}, args=args)
    else:
        _print_fetch_json(
            {"url": response.url, key: values, "selector": selector},
            args=args,
        )


def _print_fetch_json(payload: Any, *, args: argparse.Namespace) -> None:
    if args.csv:
        _print_fetch_csv(payload if isinstance(payload, list) else [payload])
        return
    if args.jsonl:
        print_jsonl(payload if isinstance(payload, list) else [payload])
        return
    if hasattr(payload, "model_dump"):
        payload = payload.model_dump(mode="json")
    print(json.dumps(payload, ensure_ascii=True, default=str, indent=2))


def _csv_cell(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    if isinstance(value, dict | list | tuple):
        return json.dumps(value, ensure_ascii=True, default=str)
    return value


def _print_fetch_csv(rows: list[Any]) -> None:
    normalized = [
        (item.model_dump(mode="json") if hasattr(item, "model_dump") else item)
        for item in rows
    ]
    dict_rows = [row if isinstance(row, dict) else {"value": row} for row in normalized]
    fieldnames: list[str] = []
    for row in dict_rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    writer = csv.DictWriter(sys.stdout, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for row in dict_rows:
        writer.writerow({key: _csv_cell(value) for key, value in row.items()})


def _find_resolver(args: argparse.Namespace) -> LlmSmartResolver:
    settings = openai_defaults()
    return LlmSmartResolver(
        model=args.llm_model or settings.model or "gpt-4.1-mini",
        api_key=args.llm_api_key or settings.api_key,
        base_url=args.llm_base_url or settings.base_url,
    )


def fetch_command(args: argparse.Namespace) -> int:
    llm_prompt = args.llm_extract
    find_prompt = args.llm_find
    css_find = args.css_find
    css_selector = args.css
    with ExitStack() as stack:
        request_kwargs = cli_request_options(args, {})
        request_kwargs.update(_body_options(args, stack))
        response = request(
            args.method,
            args.url,
            **request_kwargs,
        )
    if args.json_output:
        payload = response.json()
        _print_fetch_json(payload, args=args)
        return 0
    if css_selector:
        matches = response.css(css_selector)
        first = args.first and not args.all_matches
        values = (
            _element_value(matches[0], args.attr)
            if first and matches
            else [_element_value(element, args.attr) for element in matches]
        )
        _print_extraction(
            args=args,
            response=response,
            values=values,
            selector=css_selector,
            output_shape=args.output_shape,
            field=args.field,
            first=first,
        )
        return 0
    first = args.first and not args.all_matches
    if llm_prompt:
        settings = openai_defaults()
        llm_kwargs = {
            key: value
            for key, value in {
                "model": args.llm_model or settings.model or "gpt-4.1-mini",
                "api_key": args.llm_api_key or settings.api_key,
                "base_url": args.llm_base_url or settings.base_url,
                "system_prompt": args.llm_system_prompt
                or (
                    SMART_FIRST_EXTRACTION_SYSTEM_PROMPT
                    if first
                    else SMART_EXTRACTION_SYSTEM_PROMPT
                ),
                "max_chars": args.llm_max_chars,
                "temperature": args.llm_temperature,
            }.items()
            if value is not None
        }
        extractor = response.llm_extract_first if first else response.llm_extract
        value = extractor(llm_prompt, **llm_kwargs)
        _print_extraction(
            args=args,
            response=response,
            values=value,
            selector=llm_prompt,
            output_shape=args.output_shape,
            field=args.field,
            first=first,
        )
        return 0
    if find_prompt or css_find:
        try:
            match = (
                response.css_find(css_find)
                if css_find
                else response.llm_find(
                    find_prompt, resolver=_find_resolver(args)
                )
            )
            if match is None:
                value = None if first else []
            else:
                value = _element_value(match, args.attr)
                if not first:
                    value = [value]
        except SmartSelectorError:
            failure = args.find_failure
            if failure == "empty":
                value = None if first else []
            else:
                raise
        _print_extraction(
            args=args,
            response=response,
            values=value,
            selector=css_find or find_prompt,
            output_shape=args.output_shape,
            field=args.field,
            first=first,
        )
        return 0
    if args.meta:
        _print_fetch_json(
            {
                "url": response.url,
                "status_code": response.status_code,
                "headers": response.headers,
            },
            args=args,
        )
        return 0
    sys.stdout.write(response.text)
    if not response.text.endswith("\n"):
        sys.stdout.write("\n")
    return 0


def register(subparsers: argparse._SubParsersAction) -> None:
    fetch = subparsers.add_parser("fetch")
    fetch.add_argument("url")
    fetch.add_argument("--method", default="GET")
    add_request_args(fetch)
    fetch.add_argument("--data")
    fetch.add_argument("--json", dest="json_body")
    fetch.add_argument("--form", action="append")
    fetch.add_argument("--file", action="append")
    fetch.add_argument("--attr")
    fetch.add_argument("--first", action="store_true")
    fetch.add_argument("--all", dest="all_matches", action="store_true")
    fetch.add_argument("--output-shape", choices=["matches", "item"], default="matches")
    fetch.add_argument("--field", default="value")
    fetch.add_argument("--llm-model")
    fetch.add_argument("--llm-api-key")
    fetch.add_argument("--llm-base-url")
    fetch.add_argument("--llm-system-prompt")
    fetch.add_argument("--llm-max-chars", type=int)
    fetch.add_argument("--llm-temperature", type=float)
    extraction = fetch.add_mutually_exclusive_group()
    extraction.add_argument("--css")
    extraction.add_argument("--css-find")
    extraction.add_argument("--llm-extract")
    extraction.add_argument("--llm-find")
    fetch.add_argument("--find-failure", choices=["error", "empty"], default="error")
    fetch.add_argument("--meta", action="store_true")
    fetch.add_argument("--json-output", action="store_true")
    output_format = fetch.add_mutually_exclusive_group()
    output_format.add_argument("--jsonl", action="store_true")
    output_format.add_argument("--csv", action="store_true")
    fetch.set_defaults(func=fetch_command)
