from __future__ import annotations

import argparse
import asyncio
import json
import sys
from contextlib import ExitStack
from dataclasses import asdict, fields, is_dataclass
from pathlib import Path
from typing import Any

from .client import request
from .crawl import acrawl, crawl
from .exceptions import SmartSelectorError
from .models import FollowRule, RequestOptions
from .smart import LlmSmartResolver, SmartSelectorStore
from .websocket import aws_connect, ws_connect


_REQUEST_OPTION_NAMES = {
    field.name
    for field in fields(RequestOptions)
    if field.name != "extra_kwargs"
}


def _load_config(path: str | None) -> dict[str, Any]:
    if not path:
        return {}
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(path)
    if config_path.suffix == ".toml":
        import tomllib

        return tomllib.loads(config_path.read_text(encoding="utf-8"))
    if config_path.suffix in {".yaml", ".yml"}:
        import yaml

        return yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    raise ValueError(f"Unsupported config format: {config_path.suffix}")


def _pairs(values: list[str] | None) -> dict[str, str]:
    result: dict[str, str] = {}
    for value in values or []:
        key, item = _pair(value, "KEY=VALUE")
        result[key] = item
    return result


def _pair(value: str, label: str) -> tuple[str, str]:
    if "=" not in value:
        raise SystemExit(f"{label} argument must be KEY=VALUE: {value!r}")
    key, item = value.split("=", 1)
    key = key.strip()
    if not key:
        raise SystemExit(f"{label} argument has an empty key: {value!r}")
    return key, item


def _extract_rules(values: list[str] | None) -> dict[str, Any]:
    rules: dict[str, Any] = {}
    for value in values or []:
        key, selector = _pair(value, "--extract-css")
        rules[key] = selector
    return rules


def _structured_extract_rules(args: argparse.Namespace, config: dict[str, Any]) -> dict[str, Any]:
    rules = {**config.get("extract", {}), **_extract_rules(getattr(args, "extract_css", None))}
    for value in getattr(args, "extract_xpath", None) or []:
        key, selector = _pair(value, "--extract-xpath")
        rules[key] = {"xpath": selector}
    for value in getattr(args, "extract_smart", None) or []:
        key, prompt = _pair(value, "--extract-smart")
        rules[key] = {"smart": prompt}
    for value in getattr(args, "extract_attr", None) or []:
        key, attr = _pair(value, "--extract-attr")
        existing = rules.get(key)
        if isinstance(existing, str):
            existing = {"css": existing}
        elif not isinstance(existing, dict):
            existing = {}
        existing["attr"] = attr
        rules[key] = existing
    for key in getattr(args, "extract_all", None) or []:
        existing = rules.get(key)
        if isinstance(existing, str):
            existing = {"css": existing}
        elif not isinstance(existing, dict):
            existing = {}
        existing["all"] = True
        rules[key] = existing
    return rules


def _json_arg(value: str, label: str) -> Any:
    try:
        return json.loads(value)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"{label} must be valid JSON: {exc.msg}") from exc


def _auth(value: str, label: str) -> tuple[str, str]:
    if ":" not in value:
        raise SystemExit(f"{label} must be USER:PASS")
    username, password = value.split(":", 1)
    if not username:
        raise SystemExit(f"{label} has an empty username")
    return username, password


def _request_options_from_config(config: dict[str, Any]) -> dict[str, Any]:
    options = {
        key: config[key]
        for key in _REQUEST_OPTION_NAMES
        if key in config and config[key] is not None
    }
    options.update(config.get("extra_kwargs", {}) or {})
    return options


def _merge_pairs(config_values: Any, cli_values: list[str] | None) -> dict[str, Any] | None:
    merged = {**(config_values or {}), **_pairs(cli_values)}
    return merged or None


def _merge_json_pairs(config_values: Any, cli_values: list[str] | None, label: str) -> dict[str, Any] | None:
    merged = dict(config_values or {})
    for value in cli_values or []:
        key, item = _pair(value, label)
        merged[key] = _json_arg(item, label)
    return merged or None


def _cli_request_options(args: argparse.Namespace, config: dict[str, Any]) -> dict[str, Any]:
    request_kwargs = _request_options_from_config(config)
    request_kwargs.update(
        {
            "headers": _merge_pairs(config.get("headers"), getattr(args, "header", None)),
            "cookies": _merge_pairs(config.get("cookies"), getattr(args, "cookie", None)),
            "params": _merge_pairs(config.get("params"), getattr(args, "param", None)),
            "proxy": getattr(args, "proxy", None) or config.get("proxy"),
            "proxy_auth": (
                _auth(args.proxy_auth, "--proxy-auth")
                if getattr(args, "proxy_auth", None)
                else config.get("proxy_auth")
            ),
            "impersonate": getattr(args, "impersonate", None) or config.get("impersonate"),
            "timeout": getattr(args, "timeout", None) if getattr(args, "timeout", None) is not None else config.get("timeout"),
            "auth": _auth(args.auth, "--auth") if getattr(args, "auth", None) else config.get("auth"),
            "verify": getattr(args, "verify", None) if getattr(args, "verify", None) is not None else config.get("verify"),
            "follow_redirects": (
                getattr(args, "follow_redirects", None)
                if getattr(args, "follow_redirects", None) is not None
                else config.get("follow_redirects")
            ),
            "max_redirects": (
                getattr(args, "max_redirects", None)
                if getattr(args, "max_redirects", None) is not None
                else config.get("max_redirects")
            ),
            "ja3": getattr(args, "ja3", None) or config.get("ja3"),
            "akamai": getattr(args, "akamai", None) or config.get("akamai"),
            "extra_fp": _merge_json_pairs(config.get("extra_fp"), getattr(args, "extra_fp", None), "--extra-fp"),
            "default_headers": (
                getattr(args, "default_headers", None)
                if getattr(args, "default_headers", None) is not None
                else config.get("default_headers")
            ),
            "http_version": getattr(args, "http_version", None) or config.get("http_version"),
            "interface": getattr(args, "interface", None) or config.get("interface"),
            "cert": getattr(args, "cert", None) or config.get("cert"),
            "referer": getattr(args, "referer", None) or config.get("referer"),
        }
    )
    request_kwargs.pop("method", None)
    return {key: value for key, value in request_kwargs.items() if value is not None}


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
        options["json"] = _json_arg(args.json_body, "--json")
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


def _allowed_domains(value: Any) -> set[str] | None:
    if value is None:
        return None
    if isinstance(value, str):
        return {value}
    return set(value) or None


def _follow_rule_from_config(value: Any, *, same_domain: bool = False) -> FollowRule:
    if isinstance(value, str):
        return FollowRule(css=value, same_domain=same_domain)
    if not isinstance(value, dict):
        raise ValueError(f"Unsupported follow rule: {value!r}")
    return FollowRule(
        css=value.get("css"),
        xpath=value.get("xpath"),
        attr=value.get("attr", "href"),
        include=value.get("include"),
        exclude=value.get("exclude"),
        same_domain=value.get("same_domain", same_domain),
        allowed_domains=_allowed_domains(value.get("allowed_domains")),
        max_depth=value.get("max_depth"),
    )


def _print_jsonl(items: list[Any]) -> None:
    for item in items:
        if is_dataclass(item):
            item = asdict(item)
        print(json.dumps(item, ensure_ascii=True, default=str))


def _element_value(element: Any, attr: str | None) -> Any:
    if element is None:
        return None
    return element.attr(attr) if attr else element.text()


def _print_extraction(
    *,
    response: Any,
    values: Any,
    selector: str,
    output_shape: str,
    field: str,
    first: bool,
) -> None:
    key = "match" if first else "matches"
    if output_shape == "item":
        _print_jsonl([{field: values}])
    else:
        _print_jsonl([{"url": response.url, key: values, "selector": selector}])


def _smart_resolver(args: argparse.Namespace, config: dict[str, Any]) -> LlmSmartResolver | None:
    if not (getattr(args, "smart_use_llm", False) or config.get("smart_use_llm")):
        return None
    return LlmSmartResolver(
        model=getattr(args, "smart_model", None) or config.get("smart_model", "gpt-4.1-mini"),
        api_key=getattr(args, "smart_api_key", None) or config.get("smart_api_key"),
        base_url=getattr(args, "smart_base_url", None) or config.get("smart_base_url"),
    )


def _fetch_command(args: argparse.Namespace) -> int:
    config = _load_config(args.config).get("fetch", {})
    url = args.url or config.get("url")
    if not url:
        raise SystemExit("fetch requires a URL")
    with ExitStack() as stack:
        request_kwargs = _cli_request_options(args, config)
        request_kwargs.update(_body_options(args, stack))
        response = request(
            args.method or config.get("method", "GET"),
            url,
            **request_kwargs,
        )
    if args.json_output or config.get("json_output"):
        payload = response.json()
        if isinstance(payload, list):
            _print_jsonl(payload)
        else:
            _print_jsonl([payload])
        return 0
    if args.css:
        matches = response.css(args.css)
        first = False if args.all_matches else args.first or config.get("first", False)
        values = _element_value(matches[0], args.attr) if first and matches else [
            _element_value(element, args.attr) for element in matches
        ]
        _print_extraction(
            response=response,
            values=values,
            selector=args.css,
            output_shape=args.output_shape or config.get("output_shape", "matches"),
            field=args.field or config.get("field", "value"),
            first=first,
        )
        return 0
    if args.xpath:
        matches = response.xpath(args.xpath)
        first = False if args.all_matches else args.first or config.get("first", False)
        values = _element_value(matches[0], args.attr) if first and matches else [
            _element_value(element, args.attr) for element in matches
        ]
        _print_extraction(
            response=response,
            values=values,
            selector=args.xpath,
            output_shape=args.output_shape or config.get("output_shape", "matches"),
            field=args.field or config.get("field", "value"),
            first=first,
        )
        return 0
    if args.smart:
        smart_store = args.smart_store or config.get("smart_store")
        smart_key = args.smart_key or config.get("smart_key")
        store = SmartSelectorStore(smart_store) if smart_store else None
        resolver = _smart_resolver(args, config)
        try:
            match = response.smart(
                args.smart,
                key=smart_key,
                store=store,
                use_llm=resolver is not None,
                resolver=resolver,
            )
            value = _element_value(match, args.attr)
        except SmartSelectorError:
            if (args.smart_failure or config.get("smart_failure", "error")) == "empty":
                value = None
            else:
                raise
        _print_extraction(
            response=response,
            values=value,
            selector=args.smart,
            output_shape=args.output_shape or config.get("output_shape", "matches"),
            field=args.field or config.get("field", "value"),
            first=True,
        )
        return 0
    if args.meta:
        _print_jsonl(
            [
                {
                    "url": response.url,
                    "status_code": response.status_code,
                    "headers": response.headers,
                }
            ]
        )
        return 0
    sys.stdout.write(response.text)
    if not response.text.endswith("\n"):
        sys.stdout.write("\n")
    return 0


def _crawl_options(args: argparse.Namespace, config: dict[str, Any]) -> dict[str, Any]:
    follow_rules = []
    for rule in config.get("follow", []):
        follow_rules.append(_follow_rule_from_config(rule, same_domain=config.get("same_domain", False)))
    for selector in config.get("follow_css", []):
        follow_rules.append(FollowRule(css=selector, same_domain=config.get("same_domain", False)))
    for selector in args.follow_css or []:
        follow_rules.append(FollowRule(css=selector, same_domain=args.same_domain))
    for selector in config.get("follow_xpath", []):
        follow_rules.append(FollowRule(xpath=selector, same_domain=config.get("same_domain", False)))
    for selector in args.follow_xpath or []:
        follow_rules.append(FollowRule(xpath=selector, same_domain=args.same_domain))
    request_defaults = _cli_request_options(args, config.get("request_defaults", {}))
    return {
        "extract": _structured_extract_rules(args, config),
        "follow": follow_rules,
        "max_depth": args.max_depth if args.max_depth is not None else config.get("max_depth", 0),
        "max_requests": args.max_requests if args.max_requests is not None else config.get("max_requests"),
        "concurrency": args.concurrency if args.concurrency is not None else config.get("concurrency", 10),
        "allowed_domains": set(args.allowed_domain or config.get("allowed_domains", [])) or None,
        "request_defaults": request_defaults,
    }


def _crawl_command(args: argparse.Namespace) -> int:
    config = _load_config(args.config).get("crawl", {})
    seeds = args.urls or config.get("seeds")
    if not seeds:
        raise SystemExit("crawl requires at least one seed URL")
    options = _crawl_options(args, config)
    result = crawl(seeds, **options)
    if result.items:
        _print_jsonl(result.items)
    else:
        _print_jsonl(
            [
                {
                    "visited": sorted(result.visited),
                    "stats": asdict(result.stats),
                }
            ]
        )
    return 0 if not result.errors else 1


async def _acrawl_command(args: argparse.Namespace) -> int:
    config = _load_config(args.config).get("crawl", {})
    seeds = args.urls or config.get("seeds")
    if not seeds:
        raise SystemExit("crawl requires at least one seed URL")
    options = _crawl_options(args, config)
    result = await acrawl(seeds, **options)
    if result.items:
        _print_jsonl(result.items)
    else:
        _print_jsonl(
            [
                {
                    "visited": sorted(result.visited),
                    "stats": asdict(result.stats),
                }
            ]
        )
    return 0 if not result.errors else 1


def _websocket_payload(args: argparse.Namespace, config: dict[str, Any]) -> tuple[str | None, Any]:
    send_text = args.send if args.send is not None else config.get("send")
    send_json = args.send_json if args.send_json is not None else config.get("send_json")
    if send_text is not None and send_json is not None:
        raise SystemExit("Use only one of --send or --send-json")
    if send_json is not None:
        return "json", _json_arg(send_json, "--send-json") if isinstance(send_json, str) else send_json
    if send_text is not None:
        return "text", send_text
    return None, None


def _websocket_command(args: argparse.Namespace) -> int:
    config = _load_config(args.config).get("websocket", {})
    url = args.url or config.get("url")
    if not url:
        raise SystemExit("websocket requires a URL")
    options = _cli_request_options(args, config)
    payload_type, payload = _websocket_payload(args, config)
    recv_count = args.recv if args.recv is not None else config.get("recv", 1)
    with ws_connect(url, **options) as websocket:
        if payload_type == "json":
            websocket.send_json(payload)
        elif payload_type == "text":
            websocket.send_text(payload)
        messages = []
        for _ in range(max(0, recv_count)):
            message = websocket.recv()
            if isinstance(message, bytes):
                message = message.decode("utf-8", errors="replace")
            messages.append({"url": url, "message": message})
    _print_jsonl(messages)
    return 0


async def _awebsocket_command(args: argparse.Namespace) -> int:
    config = _load_config(args.config).get("websocket", {})
    url = args.url or config.get("url")
    if not url:
        raise SystemExit("websocket requires a URL")
    options = _cli_request_options(args, config)
    payload_type, payload = _websocket_payload(args, config)
    recv_count = args.recv if args.recv is not None else config.get("recv", 1)
    async with await aws_connect(url, **options) as websocket:
        if payload_type == "json":
            await websocket.send_json(payload)
        elif payload_type == "text":
            await websocket.send_text(payload)
        messages = []
        for _ in range(max(0, recv_count)):
            message = await websocket.recv()
            if isinstance(message, bytes):
                message = message.decode("utf-8", errors="replace")
            messages.append({"url": url, "message": message})
    _print_jsonl(messages)
    return 0


def _add_request_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--header", action="append")
    parser.add_argument("--cookie", action="append")
    parser.add_argument("--param", action="append")
    parser.add_argument("--auth")
    parser.add_argument("--proxy")
    parser.add_argument("--proxy-auth")
    parser.add_argument("--impersonate")
    parser.add_argument("--timeout", type=float)
    parser.add_argument("--verify", dest="verify", action="store_true", default=None)
    parser.add_argument("--no-verify", dest="verify", action="store_false")
    parser.add_argument("--follow-redirects", dest="follow_redirects", action="store_true", default=None)
    parser.add_argument("--no-follow-redirects", dest="follow_redirects", action="store_false")
    parser.add_argument("--max-redirects", type=int)
    parser.add_argument("--ja3")
    parser.add_argument("--akamai")
    parser.add_argument("--extra-fp", action="append")
    parser.add_argument("--default-headers", dest="default_headers", action="store_true", default=None)
    parser.add_argument("--no-default-headers", dest="default_headers", action="store_false")
    parser.add_argument("--http-version")
    parser.add_argument("--interface")
    parser.add_argument("--cert")
    parser.add_argument("--referer")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="webuse")
    subparsers = parser.add_subparsers(dest="command", required=True)

    fetch = subparsers.add_parser("fetch")
    fetch.add_argument("url", nargs="?")
    fetch.add_argument("--config")
    fetch.add_argument("--method")
    _add_request_args(fetch)
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
    fetch.add_argument("--smart")
    fetch.add_argument("--smart-store")
    fetch.add_argument("--smart-key")
    fetch.add_argument("--smart-use-llm", action="store_true")
    fetch.add_argument("--smart-model")
    fetch.add_argument("--smart-api-key")
    fetch.add_argument("--smart-base-url")
    fetch.add_argument("--smart-failure", choices=["error", "empty"])
    fetch.add_argument("--meta", action="store_true")
    fetch.add_argument("--json-output", action="store_true")
    fetch.set_defaults(func=_fetch_command)

    crawl_parser = subparsers.add_parser("crawl")
    crawl_parser.add_argument("urls", nargs="*")
    crawl_parser.add_argument("--config")
    _add_request_args(crawl_parser)
    crawl_parser.add_argument("--follow-css", action="append")
    crawl_parser.add_argument("--follow-xpath", action="append")
    crawl_parser.add_argument("--extract-css", action="append")
    crawl_parser.add_argument("--extract-xpath", action="append")
    crawl_parser.add_argument("--extract-smart", action="append")
    crawl_parser.add_argument("--extract-attr", action="append")
    crawl_parser.add_argument("--extract-all", action="append")
    crawl_parser.add_argument("--allowed-domain", action="append")
    crawl_parser.add_argument("--same-domain", action="store_true")
    crawl_parser.add_argument("--max-depth", type=int)
    crawl_parser.add_argument("--max-requests", type=int)
    crawl_parser.add_argument("--concurrency", type=int)
    crawl_parser.add_argument("--async", dest="use_async", action="store_true")
    crawl_parser.set_defaults(func=_crawl_command)

    websocket_parser = subparsers.add_parser("websocket")
    websocket_parser.add_argument("url", nargs="?")
    websocket_parser.add_argument("--config")
    _add_request_args(websocket_parser)
    websocket_parser.add_argument("--send")
    websocket_parser.add_argument("--send-json")
    websocket_parser.add_argument("--recv", type=int)
    websocket_parser.add_argument("--async", dest="use_async", action="store_true")
    websocket_parser.set_defaults(func=_websocket_command)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "crawl" and getattr(args, "use_async", False):
        return asyncio.run(_acrawl_command(args))
    if args.command == "websocket" and getattr(args, "use_async", False):
        return asyncio.run(_awebsocket_command(args))
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
