---
title: "CLI Internals"
description: "File responsibilities and command dispatch in src/webuse/cli."
---

`src/webuse/cli/` translates command-line arguments into Python API calls,
project files, or a UI server process. Crawl execution stays in the spiders
and engines.

## Source

| File | Responsibility |
| --- | --- |
| `__init__.py` | Export `build_parser()` and `main()`. |
| `__main__.py` | Run the CLI through `python -m webuse.cli` and return its exit status. |
| `app.py` | Register commands, parse arguments, initialize logging/model defaults, and dispatch sync or async handlers. |
| `utils.py` | Shared argument parsing, configuration loading, HTTP option merging, and JSONL output helpers. |
| `project.py` | Locate root project configuration, require a project directory, and validate `ProjectConfig`. |
| `create.py` | Scaffold a project with YAML settings, README, package markers, and directories. |
| `gen.py` | Generate and register a spider with its model and pipeline classes; default to YAML plus a Python module. |
| `fetch.py` | Fetch one URL, apply CSS or model-backed extraction, and format the requested output. |
| `crawl.py` | Load registered spiders, apply overrides and a shared request budget, and stream processed records to the output file during execution. |
| `websocket.py` | Send and receive WebSocket messages through curl_cffi, with sync and async handlers. |
| `serve.py` | Check the bundled UI and Node runtime, launch the server, wait for readiness, open a browser, and stop the process on exit. |

## Command flow

Each command module exposes `register(subparsers)`, which defines arguments and
attaches a `func` handler. Commands supporting `--async` also attach
`async_func`; `app.main()` runs that handler through `asyncio.run()`.
The crawl command also detects Python `AsyncSpider` subclasses independently
of the flag.

Add commands to `app.py`'s `_COMMAND_MODULES`. Keep shared CLI helpers in
`utils.py`, project discovery in `project.py`, and reusable runtime behavior
in the Python APIs. CLI tests live in `tests/cli/`.

See the [Command Line guide](../../references/cli/) for usage and
[Engine Internals](../engine/) for crawl execution.
