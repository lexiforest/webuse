import argparse
from pathlib import Path

from ..ui.server import serve_ui


def ui_command(args: argparse.Namespace) -> int:
    serve_ui(
        host=args.host,
        port=args.port,
        db_path=Path(args.db_path).expanduser() if args.db_path else None,
        work_dir=Path(args.work_dir).expanduser() if args.work_dir else None,
        static_dir=Path(args.static_dir).expanduser() if args.static_dir else None,
        open_browser=args.open,
    )
    return 0


def register(subparsers: argparse._SubParsersAction) -> None:
    ui = subparsers.add_parser("ui")
    ui.add_argument("--host", default="127.0.0.1")
    ui.add_argument("--port", type=int, default=8787)
    ui.add_argument("--db-path")
    ui.add_argument("--work-dir")
    ui.add_argument("--static-dir")
    ui.add_argument("--open", action="store_true")
    ui.set_defaults(func=ui_command)
