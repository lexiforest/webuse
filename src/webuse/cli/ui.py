"""Launch the compiled Node control plane shipped in the Python package."""

import argparse
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path


DEFAULT_PORT = 2951


def _bundle_entrypoint() -> Path:
    root = Path(__file__).resolve().parents[1] / "_ui"
    entrypoint = root / "server" / "index.mjs"
    if not entrypoint.is_file() or not (root / "public").is_dir():
        raise SystemExit(
            "The compiled UI is missing. Install a released webuse package, or "
            "run `uv build` from a source checkout with Node.js 24+ and npm. "
            "For UI development, run `npm run dev` in ui/."
        )
    return entrypoint


def _node_command() -> str:
    command = shutil.which("node")
    if not command:
        raise SystemExit("webuse ui requires Node.js 24+ on PATH. npm is not required to run the packaged UI.")
    try:
        result = subprocess.run(
            [command, "--version"], capture_output=True, text=True, check=True
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise SystemExit(f"Could not run Node.js: {error}") from error
    version = re.match(r"v?(\d+)\.", result.stdout.strip())
    if version is None or int(version.group(1)) < 24:
        raise SystemExit(f"webuse ui requires Node.js 24+; found {result.stdout.strip()!r}.")
    return command


def _port(value: str) -> int:
    try:
        port = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("port must be an integer") from error
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be between 1 and 65535")
    return port


def _url(host: str, port: int) -> tuple[str, str]:
    connect_host = {"0.0.0.0": "127.0.0.1", "::": "::1"}.get(host, host)
    url_host = f"[{connect_host}]" if ":" in connect_host else connect_host
    return connect_host, f"http://{url_host}:{port}/"


def _ensure_port_available(host: str, port: int) -> None:
    try:
        addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        for family, kind, protocol, _, address in addresses:
            with socket.socket(family, kind, protocol) as probe:
                probe.bind(address)
    except OSError as error:
        raise SystemExit(f"Cannot listen on {host}:{port}: {error}. Choose another --port or --host.") from error


def _wait_ready(process: subprocess.Popen, host: str, port: int) -> None:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise SystemExit(f"The UI server exited during startup (status {process.returncode}).")
        try:
            with socket.create_connection((host, port), timeout=0.2):
                return
        except OSError:
            time.sleep(0.1)
    raise SystemExit("The UI server did not start within 30 seconds. See the server output above.")


def _stop(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    # The server and crawler children share a separate process group on POSIX.
    # Stop that group so a forced shutdown cannot leave crawlers running.
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGTERM)
        else:
            process.terminate()
        process.wait(timeout=5)
    except ProcessLookupError:
        pass
    except subprocess.TimeoutExpired:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
        process.wait()


def ui_command(args: argparse.Namespace) -> int:
    entrypoint = _bundle_entrypoint()
    node = _node_command()
    host = args.host
    port = args.port
    _ensure_port_available(host, port)
    directory = Path(args.data_dir).expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env.update(HOST=host, PORT=str(port), NITRO_HOST=host, NITRO_PORT=str(port))
    env.setdefault("WEBUSE_PYTHON_COMMAND", sys.executable)
    for name, default in (
        ("WEBUSE_DB_PATH", directory / "webuse-ui.sqlite"),
        ("WEBUSE_WORK_DIR", directory / "runs"),
    ):
        env[name] = str(Path(env.get(name) or default).expanduser().resolve())
    connect_host, url = _url(host, port)
    try:
        process = subprocess.Popen(
            [node, str(entrypoint)], cwd=directory, env=env,
            start_new_session=os.name == "posix",
        )
    except OSError as error:
        raise SystemExit(f"Could not start the UI server: {error}") from error

    def terminate(signum, _frame):
        raise SystemExit(128 + signum)

    previous_term = signal.signal(signal.SIGTERM, terminate)
    try:
        _wait_ready(process, connect_host, port)
        print(f"Webuse UI: {url}\nData directory: {directory}\nPress Ctrl+C to stop.", flush=True)
        if not args.no_open:
            try:
                webbrowser.open(url)
            except webbrowser.Error:
                print(f"Could not open a browser. Open {url} manually.", file=sys.stderr)
        return process.wait()
    except KeyboardInterrupt:
        return 0
    finally:
        try:
            _stop(process)
        finally:
            signal.signal(signal.SIGTERM, previous_term)


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("ui", help="Start the bundled UI and open it in a browser")
    parser.add_argument("--host", default="127.0.0.1", help="Bind address (default: 127.0.0.1)")
    parser.add_argument("--port", type=_port, default=DEFAULT_PORT, help="Listen port (default: 2951)")
    parser.add_argument("--no-open", action="store_true", help="Do not open a browser")
    parser.add_argument(
        "--data-dir", default=os.environ.get("WEBUSE_UI_DATA_DIR") or str(Path.home() / ".webuse" / "ui"),
        help="Writable data directory (default: ~/.webuse/ui, or WEBUSE_UI_DATA_DIR)",
    )
    parser.set_defaults(func=ui_command)
