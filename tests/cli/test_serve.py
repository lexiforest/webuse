import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from webuse.cli.app import build_parser, main
from webuse.cli import serve


def test_missing_bundle_has_source_build_instructions(monkeypatch, tmp_path):
    monkeypatch.setattr(
        serve, "__file__", str(tmp_path / "webuse" / "cli" / "serve.py")
    )
    with pytest.raises(SystemExit, match="uv build"):
        serve._bundle_entrypoint()


@pytest.mark.parametrize(
    "version",
    ["v18.20.0", "v22.15.0", "v22.18.0", "v22.19", "v22.19.0-rc.1", "unexpected"],
)
def test_reject_unsupported_node(monkeypatch, version):
    monkeypatch.setattr(serve.shutil, "which", lambda _: "/bin/node")
    monkeypatch.setattr(
        serve.subprocess, "run", lambda *a, **kw: SimpleNamespace(stdout=version)
    )
    with pytest.raises(SystemExit, match=r"Node.js 22\.19\+"):
        serve._node_command()


@pytest.mark.parametrize("version", ["v22.19.0", "v22.20.0", "v24.0.0", "v26.0.0"])
def test_accept_supported_node(monkeypatch, version):
    monkeypatch.setattr(serve.shutil, "which", lambda _: "/bin/node")
    monkeypatch.setattr(
        serve.subprocess, "run", lambda *a, **kw: SimpleNamespace(stdout=version)
    )
    assert serve._node_command() == "/bin/node"


def test_missing_node_is_actionable(monkeypatch):
    monkeypatch.setattr(serve.shutil, "which", lambda _: None)
    with pytest.raises(SystemExit, match="npm is not required"):
        serve._node_command()


@pytest.mark.parametrize("port", ["0", "65536", "abc"])
def test_invalid_port(port):
    with pytest.raises(SystemExit):
        build_parser().parse_args(["serve", "--port", port])


def test_serve_does_not_probe_model_providers(monkeypatch):
    def unexpected():
        pytest.fail("UI startup should not discover Python model providers")

    monkeypatch.setattr("webuse.cli.app.configure_openai_defaults", unexpected)
    monkeypatch.setattr(serve, "serve_command", lambda args: 0)
    assert main(["serve", "--no-open"]) == 0


@pytest.fixture
def fake_server(monkeypatch, tmp_path):
    captured = {}

    class Process:
        returncode = None
        pid = 12345

        def wait(self):
            return 7

    process = Process()

    def popen(command, **kwargs):
        captured.update(command=command, **kwargs)
        return process

    monkeypatch.chdir(tmp_path)
    for key in (
        "WEBUSE_PYTHON_COMMAND",
        "WEBUSE_DB_PATH",
        "WEBUSE_WORK_DIR",
        "WEBUSE_UI_DATA_DIR",
        "WEBUSE_CONFIG_DIR",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("NITRO_PORT", "9999")
    monkeypatch.setenv("NITRO_HOST", "0.0.0.0")
    monkeypatch.setattr(
        serve,
        "_bundle_entrypoint",
        lambda: tmp_path / "installed" / "server" / "index.mjs",
    )
    monkeypatch.setattr(serve, "_node_command", lambda: "/bin/node")
    monkeypatch.setattr(serve, "_ensure_port_available", lambda *a: None)
    monkeypatch.setattr(serve.subprocess, "Popen", popen)
    monkeypatch.setattr(serve, "_wait_ready", lambda *a: captured.update(ready=True))
    monkeypatch.setattr(
        serve,
        "_stop",
        lambda p, sig: captured.update(stopped=p is process, stop_signal=sig),
    )

    def open_browser(url):
        assert captured.get("ready"), "Only open the browser after startup"
        captured["url"] = url

    monkeypatch.setattr(serve.webbrowser, "open", open_browser)
    return captured


def test_launch_uses_installed_python_and_writable_data(fake_server, tmp_path):
    args = build_parser().parse_args(["serve", "--data-dir", "user data"])
    assert serve.serve_command(args) == 7
    env = fake_server["env"]
    assert env["WEBUSE_PYTHON_COMMAND"] == sys.executable
    assert env["PORT"] == env["NITRO_PORT"] == "2951"
    assert env["HOST"] == env["NITRO_HOST"] == "127.0.0.1"
    assert Path(env["WEBUSE_DB_PATH"]) == tmp_path / "user data" / "webuse.db"
    assert Path(env["WEBUSE_CONFIG_DIR"]) == tmp_path
    assert Path(env["WEBUSE_WORK_DIR"]) == tmp_path / "user data" / "executions"
    assert fake_server["cwd"] == tmp_path / "user data"
    assert fake_server["url"] == "http://127.0.0.1:2951/"
    assert fake_server["stopped"]


def test_default_database_is_in_webuse_home(fake_server, monkeypatch, tmp_path):
    monkeypatch.setattr(serve.Path, "home", lambda: tmp_path / "home")
    args = build_parser().parse_args(["serve", "--no-open"])
    serve.serve_command(args)
    assert fake_server["env"]["WEBUSE_DB_PATH"] == str(
        tmp_path / "home" / ".webuse" / "webuse.db"
    )


def test_config_directory_override_is_preserved(fake_server, monkeypatch, tmp_path):
    monkeypatch.setenv("WEBUSE_CONFIG_DIR", "config")
    args = build_parser().parse_args(["serve", "--data-dir", "state", "--no-open"])
    serve.serve_command(args)
    assert fake_server["env"]["WEBUSE_CONFIG_DIR"] == str(tmp_path / "config")


def test_custom_paths_and_no_browser(fake_server, monkeypatch, tmp_path):
    monkeypatch.setenv("WEBUSE_DB_PATH", "custom/db.sqlite")
    monkeypatch.setenv("WEBUSE_WORK_DIR", "custom/executions")
    monkeypatch.setenv("WEBUSE_PYTHON_COMMAND", "/custom/python")
    args = build_parser().parse_args(
        [
            "serve",
            "--data-dir",
            "state",
            "--host",
            "0.0.0.0",
            "--port",
            "4010",
            "--no-open",
        ]
    )
    serve.serve_command(args)
    assert "url" not in fake_server
    assert fake_server["env"]["WEBUSE_DB_PATH"] == str(
        tmp_path / "custom" / "db.sqlite"
    )
    assert fake_server["env"]["WEBUSE_WORK_DIR"] == str(
        tmp_path / "custom" / "executions"
    )
    assert fake_server["env"]["WEBUSE_PYTHON_COMMAND"] == "/custom/python"
    assert fake_server["env"]["PORT"] == "4010"


def test_startup_failure_cleans_up_and_never_opens_browser(fake_server, monkeypatch):
    def fail(*args):
        raise SystemExit("startup failed")

    monkeypatch.setattr(serve, "_wait_ready", fail)
    args = build_parser().parse_args(["serve", "--data-dir", "state"])
    with pytest.raises(SystemExit, match="startup failed"):
        serve.serve_command(args)
    assert fake_server["stopped"]
    assert "url" not in fake_server


def test_keyboard_interrupt_stops_server(fake_server, monkeypatch):
    def interrupt(*args):
        raise KeyboardInterrupt

    monkeypatch.setattr(serve, "_wait_ready", interrupt)
    args = build_parser().parse_args(["serve", "--data-dir", "state"])
    assert serve.serve_command(args) == 0
    assert fake_server["stopped"]
    assert fake_server["stop_signal"] == serve.signal.SIGINT


def test_dead_server_does_not_wait_for_timeout():
    process = SimpleNamespace(poll=lambda: 9, returncode=9)
    with pytest.raises(SystemExit, match="status 9"):
        serve._wait_ready(process, "127.0.0.1", 2951)


def test_forced_shutdown_kills_process_group(monkeypatch):
    calls = []
    waits = iter([subprocess.TimeoutExpired("node", 5), 0])

    def wait(**kwargs):
        result = next(waits)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(serve.os, "name", "posix")
    monkeypatch.setattr(serve.os, "killpg", lambda pid, sig: calls.append((pid, sig)))
    process = SimpleNamespace(pid=12345, poll=lambda: None, wait=wait)
    serve._stop(process)
    assert calls == [(12345, serve.signal.SIGTERM), (12345, serve.signal.SIGKILL)]
