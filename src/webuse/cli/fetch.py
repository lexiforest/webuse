import argparse
import csv
import json
import sys
from contextlib import ExitStack
from pathlib import Path
from typing import Any

from ..client import request as _default_request
from ..exceptions import SmartSelectorError
from ..llm import openai_settings_from_config
from ..smart import LlmSmartResolver as _DefaultLlmSmartResolver
from ..smart import SMART_EXTRACTION_SYSTEM_PROMPT, SmartSelectorStore
from .common import (
    add_request_args,
    cli_request_options,
    json_arg,
    load_config,
    print_jsonl,
)


def _cli_attr(name: str, default: Any) -> Any:
    package = sys.modules.get("webuse.cli")
    return getattr(package, name, default) if package else default


def _pair(value: str, label: str) -> tuple[str, str]:
    if "=" not in value:
        raise SystemExit(f"{label} argument must be KEY=VALUE: {value!r}")
    key, item = value.split("=", 1)
    key = key.strip()
    if not key:
        raise SystemExit(f"{label} argument has an empty key: {value!r}")
    return key, item


def _pairs(values: list[str] | None) -> dict[str, str]:
    result: dict[str, str] = {}
    for value in values or []:
        key, item = _pair(value, "KEY=VALUE")
        result[key] = item
    return result


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
    config: dict[str, Any],
    response: Any,
    values: Any,
    selector: str,
    output_shape: str,
    field: str,
    first: bool,
) -> None:
    if _fetch_csv_enabled(args, config):
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
    if _fetch_jsonl_enabled(args, config) and not first and isinstance(values, list):
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
        _print_fetch_json({field: values}, args=args, config=config)
    else:
        _print_fetch_json(
            {"url": response.url, key: values, "selector": selector},
            args=args,
            config=config,
        )


def _print_fetch_json(
    payload: Any, *, args: argparse.Namespace, config: dict[str, Any]
) -> None:
    if _fetch_csv_enabled(args, config):
        _print_fetch_csv(payload if isinstance(payload, list) else [payload])
        return
    if _fetch_jsonl_enabled(args, config):
        print_jsonl(payload if isinstance(payload, list) else [payload])
        return
    if hasattr(payload, "model_dump"):
        payload = payload.model_dump(mode="json")
    print(json.dumps(payload, ensure_ascii=True, default=str, indent=2))


def _fetch_jsonl_enabled(args: argparse.Namespace, config: dict[str, Any]) -> bool:
    return bool(getattr(args, "jsonl", False) or config.get("jsonl"))


def _fetch_csv_enabled(args: argparse.Namespace, config: dict[str, Any]) -> bool:
    return bool(getattr(args, "csv", False) or config.get("csv"))


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


def _smart_resolver(
    args: argparse.Namespace, config: dict[str, Any], llm_config: dict[str, Any]
) -> Any:
    if not (getattr(args, "smart_use_llm", False) or config.get("smart_use_llm")):
        return None
    resolver_class = _cli_attr("LlmSmartResolver", _DefaultLlmSmartResolver)
    settings = openai_settings_from_config(llm_config)
    return resolver_class(
        model=settings.model or "gpt-4.1-mini",
        api_key=settings.api_key,
        base_url=settings.base_url,
    )


def _llm_value(args: argparse.Namespace, config: dict[str, Any], name: str) -> Any:
    value = getattr(args, name, None)
    if value is not None:
        return value
    return config.get(name)


def fetch_command(args: argparse.Namespace) -> int:
    root_config = load_config(args.config)
    config = root_config.get("fetch", {})
    llm_config = root_config.get("llm", {})
    url = args.url or config.get("url")
    if not url:
        raise SystemExit("fetch requires a URL")
    with ExitStack() as stack:
        request_kwargs = cli_request_options(args, config)
        request_kwargs.update(_body_options(args, stack))
        response = _cli_attr("request", _default_request)(
            args.method or config.get("method", "GET"),
            url,
            **request_kwargs,
        )
    if args.json_output or config.get("json_output"):
        payload = response.json()
        _print_fetch_json(payload, args=args, config=config)
        return 0
    css_selector = args.css or config.get("css")
    if css_selector:
        matches = response.css(css_selector)
        first = False if args.all_matches else args.first or config.get("first", False)
        values = (
            _element_value(matches[0], args.attr)
            if first and matches
            else [_element_value(element, args.attr) for element in matches]
        )
        _print_extraction(
            args=args,
            config=config,
            response=response,
            values=values,
            selector=css_selector,
            output_shape=args.output_shape or config.get("output_shape", "matches"),
            field=args.field or config.get("field", "value"),
            first=first,
        )
        return 0
    xpath_selector = args.xpath or config.get("xpath")
    if xpath_selector:
        matches = response.xpath(xpath_selector)
        first = False if args.all_matches else args.first or config.get("first", False)
        values = (
            _element_value(matches[0], args.attr)
            if first and matches
            else [_element_value(element, args.attr) for element in matches]
        )
        _print_extraction(
            args=args,
            config=config,
            response=response,
            values=values,
            selector=xpath_selector,
            output_shape=args.output_shape or config.get("output_shape", "matches"),
            field=args.field or config.get("field", "value"),
            first=first,
        )
        return 0
    smart_prompt = args.smart or config.get("smart")
    first = False if args.all_matches else args.first or config.get("first", False)
    if smart_prompt and not (
        getattr(args, "translate_xpath", False) or config.get("translate_xpath")
    ):
        settings = openai_settings_from_config(llm_config)
        llm_kwargs = {
            key: value
            for key, value in {
                "model": _llm_value(args, config, "llm_model")
                or settings.model
                or "gpt-4.1-mini",
                "api_key": _llm_value(args, config, "llm_api_key") or settings.api_key,
                "base_url": _llm_value(args, config, "llm_base_url")
                or settings.base_url,
                "system_prompt": _llm_value(args, config, "llm_system_prompt")
                or SMART_EXTRACTION_SYSTEM_PROMPT,
                "max_chars": _llm_value(args, config, "llm_max_chars"),
                "temperature": _llm_value(args, config, "llm_temperature"),
            }.items()
            if value is not None
        }
        extractor = response.smart_first if first else response.smart
        value = extractor(smart_prompt, translate_xpath=False, **llm_kwargs)
        _print_extraction(
            args=args,
            config=config,
            response=response,
            values=value,
            selector=smart_prompt,
            output_shape=args.output_shape or config.get("output_shape", "matches"),
            field=args.field or config.get("field", "value"),
            first=first,
        )
        return 0
    if smart_prompt:
        smart_store = args.smart_store or config.get("smart_store")
        smart_key = args.smart_key or config.get("smart_key")
        store = SmartSelectorStore(smart_store) if smart_store else None
        resolver = _smart_resolver(args, config, llm_config)
        try:
            extractor = response.smart_first if first else response.smart
            match = extractor(
                smart_prompt,
                translate_xpath=True,
                key=smart_key,
                store=store,
                use_llm=resolver is not None,
                resolver=resolver,
            )
            value = (
                _element_value(match, args.attr)
                if first
                else [_element_value(element, args.attr) for element in match]
            )
        except SmartSelectorError:
            failure = args.smart_failure or config.get("smart_failure", "error")
            if failure == "empty":
                value = None if first else []
            else:
                raise
        _print_extraction(
            args=args,
            config=config,
            response=response,
            values=value,
            selector=smart_prompt,
            output_shape=args.output_shape or config.get("output_shape", "matches"),
            field=args.field or config.get("field", "value"),
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
            config=config,
        )
        return 0
    sys.stdout.write(response.text)
    if not response.text.endswith("\n"):
        sys.stdout.write("\n")
    return 0


def register(subparsers: argparse._SubParsersAction) -> None:
    fetch = subparsers.add_parser("fetch")
    fetch.add_argument("url", nargs="?")
    fetch.add_argument("--config")
    fetch.add_argument("--method")
    add_request_args(fetch)
    fetch.add_argument("--data")
    fetch.add_argument("--json", dest="json_body")
    fetch.add_argument("--form", action="append")
    fetch.add_argument("--file", action="append")
    fetch.add_argument("--css")
    fetch.add_argument("--xpath")
    fetch.add_argument("--attr")
    fetch.add_argument("--first", action="store_true")
    fetch.add_argument("--all", dest="all_matches", action="store_true")
    fetch.add_argument("--output-shape", choices=["matches", "item"])
    fetch.add_argument("--field")
    fetch.add_argument("--llm-model")
    fetch.add_argument("--llm-api-key")
    fetch.add_argument("--llm-base-url")
    fetch.add_argument("--llm-system-prompt")
    fetch.add_argument("--llm-max-chars", type=int)
    fetch.add_argument("--llm-temperature", type=float)
    fetch.add_argument("--smart")
    fetch.add_argument("--translate-xpath", action="store_true")
    fetch.add_argument("--smart-store")
    fetch.add_argument("--smart-key")
    fetch.add_argument("--smart-use-llm", action="store_true")
    fetch.add_argument("--smart-failure", choices=["error", "empty"])
    fetch.add_argument("--meta", action="store_true")
    fetch.add_argument("--json-output", action="store_true")
    output_format = fetch.add_mutually_exclusive_group()
    output_format.add_argument("--jsonl", action="store_true")
    output_format.add_argument("--csv", action="store_true")
    fetch.set_defaults(func=fetch_command)
