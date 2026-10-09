import argparse
from typing import Any

from curl_cffi import AsyncSession
from curl_cffi.requests.websockets import WebSocket

from .common import (
    add_request_args,
    cli_request_options,
    json_arg,
    load_config,
    print_jsonl,
)


def _websocket_payload(
    args: argparse.Namespace, config: dict[str, Any]
) -> tuple[str | None, Any]:
    send_text = args.send if args.send is not None else config.get("send")
    send_json = (
        args.send_json if args.send_json is not None else config.get("send_json")
    )
    if send_text is not None and send_json is not None:
        raise SystemExit("Use only one of --send or --send-json")
    if send_json is not None:
        return "json", json_arg(send_json, "--send-json") if isinstance(
            send_json, str
        ) else send_json
    if send_text is not None:
        return "text", send_text
    return None, None


def websocket_command(args: argparse.Namespace) -> int:
    config = load_config(args.config).get("websocket", {})
    url = args.url or config.get("url")
    if not url:
        raise SystemExit("websocket requires a URL")
    options = cli_request_options(args, config)
    payload_type, payload = _websocket_payload(args, config)
    recv_count = args.recv if args.recv is not None else config.get("recv", 1)
    with WebSocket() as websocket:
        websocket.connect(url, **options)
        if payload_type == "json":
            websocket.send_json(payload)
        elif payload_type == "text":
            websocket.send_str(payload)
        messages = []
        for _ in range(max(0, recv_count)):
            message, _ = websocket.recv()
            if isinstance(message, bytes):
                message = message.decode("utf-8", errors="replace")
            messages.append({"url": url, "message": message})
    print_jsonl(messages)
    return 0


async def awebsocket_command(args: argparse.Namespace) -> int:
    config = load_config(args.config).get("websocket", {})
    url = args.url or config.get("url")
    if not url:
        raise SystemExit("websocket requires a URL")
    options = cli_request_options(args, config)
    payload_type, payload = _websocket_payload(args, config)
    recv_count = args.recv if args.recv is not None else config.get("recv", 1)
    async with AsyncSession() as session:
        async with session.ws_connect(url, **options) as websocket:
            if payload_type == "json":
                await websocket.send_json(payload)
            elif payload_type == "text":
                await websocket.send_str(payload)
            messages = []
            for _ in range(max(0, recv_count)):
                message, _ = await websocket.recv()
                if isinstance(message, bytes):
                    message = message.decode("utf-8", errors="replace")
                messages.append({"url": url, "message": message})
    print_jsonl(messages)
    return 0


def register(subparsers: argparse._SubParsersAction) -> None:
    websocket_parser = subparsers.add_parser("websocket")
    websocket_parser.add_argument("url", nargs="?")
    websocket_parser.add_argument("--config")
    add_request_args(websocket_parser)
    websocket_parser.add_argument("--send")
    websocket_parser.add_argument("--send-json")
    websocket_parser.add_argument("--recv", type=int)
    websocket_parser.add_argument("--async", dest="use_async", action="store_true")
    websocket_parser.set_defaults(func=websocket_command, async_func=awebsocket_command)
