---
title: "Command Line"
---

The webuse CLI is the main entrypoint for creating spiders and manage them.

## Create Project and Spider

Creating a webuse project:

```bash
webuse create books_project
```

`webuse create` writes `webuse.yaml`, `README.md`, `.gitignore`, package markers,
`spiders/`, and a local `.webuse/` runtime directory.

Generating a spider inside the project:

```shell
cd books_project
webuse gen books https://books.toscrape.com/
```

`webuse gen` puts a Pydantic `Item` model and `CleanPipeline` in the
generated spider module, alongside the spider class. The starter extracts page
titles and follows same-domain links from the supplied URL; generation does not
inspect the target site. Customize the model and extraction rules for your data.
The pipeline runs before the built-in JSONL
writer through the spider's `pipelines`, or its Python `pipelines`
attribute. YAML/TOML configs reference it as `spiders.<name>.CleanPipeline`.

Run commands from the project directory, which must contain a root
`webuse.yaml`, `webuse.yml`, or `webuse.toml`. Generation sanitizes the name
and refuses to overwrite files or an existing registration unless `--force`
is passed.

YAML is the default. Generation writes `spiders/<name>.yaml` plus a Python
wrapper with a project-relative config path, then registers the Python file in
the root `spiders` section. Use `--toml` for TOML instead, or `--python-only`
for a Python-only spider. Generated Python files define spider classes without
a separate `main()` entry point.

Add `--async` to generate an `AsyncSpider` instead of `Spider`. It works with
the default YAML output, `--toml`, and `--python-only`:

```bash
webuse gen async_books https://books.toscrape.com/ --async
webuse gen book_details https://books.toscrape.com/ --async --python-only
```

Run the generated async spider with the ordinary `webuse crawl` command; the
CLI detects `AsyncSpider` and awaits it automatically.

## Run Project

```bash
webuse crawl --spider books -o books.jsonl
webuse crawl --max-requests 3
```

The positional argument is a project directory and defaults to `.`.
`--spider` selects a registered name from its root config; omitting it runs
all entries. Root config files, individual spider files, import paths, and URLs
are not crawl targets. The local harness uses this same directory entry point.

`-o` writes records during the crawl through a built-in item pipeline selected
by extension: `.jsonl`, `.csv`, `.sqlite`, `.sqlite3`, or `.db`.
Configured spider pipelines run first, so dropped records are excluded and
transformed records are saved. JSONL and CSV flush each record; SQLite commits
each record. One output file covers all selected spiders, and records already
written remain available if a crawl stops early. The file is replaced at the
start of each command.

Use repeated `--attribute KEY=VALUE` or `-a KEY=VALUE` to set extra spider
attributes before execution. Values are strings. Use `--async` for async
execution of declarative spiders; Python spiders keep their class's sync or
async behavior.

Use `--max-requests N` for a small sample. The request budget is shared across
spiders; later spiders are skipped when it is exhausted, including with
`--async`. It counts crawl requests, not every HTTP exchange (such as redirects
or robots.txt fetches), and is not a sandbox for arbitrary Python code.

Use `--state redis://localhost:6379/0` for Redis queue and seen-hash state in
sync or async crawls. Async spiders use async Redis clients, which the CLI closes
after the run. This persists scheduler state, not a full process checkpoint.

Set extraction/follow rules in spider config and request options in
`request_defaults`. Use `fetch` for one-page inspection.

## Local Service

Start the UI, Harness, scheduler, and crawler process management together. Released
packages include the compiled UI and control plane:

```bash
webuse serve
webuse serve --no-open --port 2951 --data-dir ~/.webuse/ui
```

Node.js 22.19+ must be on PATH; npm is not needed. The command opens a browser at
`http://127.0.0.1:2951/` and stays running until Ctrl+C. `--no-open` skips the
browser, `--host` changes the bind address (default `127.0.0.1`), and
`--port` changes the port. Data defaults to `~/.webuse/ui`; override it with
`--data-dir` or `WEBUSE_UI_DATA_DIR`.

Crawlers use the same Python interpreter as the launcher unless
`WEBUSE_PYTHON_COMMAND` is set. `WEBUSE_DB_PATH` and `WEBUSE_WORK_DIR`
override the database and run paths. This command does not probe Python model
providers; configure Harness in the UI Settings. See [Harness](../../user-guide/harness/)
for Harness, [Dashboard](../../user-guide/dashboard/) for runs and schedules, and
[Harness Internals](../../advanced/harness-internals/#source-development) for
source development.


## Single Page Debugging

### Fetch a Single Request

`webuse fetch URL` takes request and extraction options as CLI arguments.
It supports request bodies and common `curl_cffi` request options:

```bash
webuse fetch https://example.com/api \
  --method POST \
  --json '{"query":"alpha"}' \
  --header 'User-Agent=webuse' \
  --cookie 'session=abc' \
  --auth 'user:pass' \
  --timeout 10 \
  --allow-redirects \
  --max-redirects 3 \
  --ja3 '...' \
  --akamai '...'
```

Body flags:

* `--data TEXT`
* `--json JSON`
* `--form KEY=VALUE`
* `--file FIELD=PATH`

Transport flags include `--proxy`, `--proxy-auth`, `--verify`,
`--no-verify`, `--http-version`, `--extra-fp KEY=JSON`,
`--default-headers`, `--no-default-headers`, `--interface`, `--cert`,
and `--referer`.
Requests impersonate Chrome by default. Use `--impersonate` to choose a
different `curl_cffi` impersonation profile.

### Extraction Output

Fetch selects existing elements with CSS or an explicit model description:

```bash
webuse fetch https://example.com --css 'a.product' --attr href --first
webuse fetch https://example.com --css 'h1' --output-shape item --field title
webuse fetch https://example.com --llm 'next page link' --attr href --first
```

Both selectors read text by default, or an attribute with `--attr`.
They return all matches in document order; `--first` returns one match.
No match produces an empty list or null. Model and malformed-output errors raise.

For structured interpretation, supply `--llm-extract` and a JSON Schema:

```bash
webuse fetch https://example.com --llm-extract 'Product names' \
  --schema '{"type":"array","items":{"type":"string"}}'
```

The schema determines the output shape. The CLI prints the validated value
directly; prose and invalid JSON are errors. `--first`, `--all`, and `--attr`
apply only to selection. `--css`, `--llm`, and `--llm-extract` are mutually exclusive.

Output is pretty-printed JSON by default. `--jsonl` emits compact JSON Lines;
`--csv` emits CSV. These flags are mutually exclusive. Arrays produce one entry
per line or row; selection output retains URL/selector metadata unless
`--output-shape item` is set. Structured extraction emits the validated records
or values directly.

LLM extraction options include `--llm-model`, `--llm-api-key`,
`--llm-base-url`, `--llm-system-prompt`, `--llm-max-chars`, and
`--llm-temperature`.

For crawler and extraction commands, webuse checks whether OpenAI-compatible credentials are already
configured through `OPENAI_API_KEY`, `OPENAI_BASE_URL`, or
`OPENAI_MODEL`. If none are configured, it probes local OpenAI-compatible
services and uses the first available model:

* LM Studio at `http://127.0.0.1:1234/v1`
* Ollama at `http://127.0.0.1:11434/v1`

Explicit CLI options or config values still take precedence.

LLM element lookup uses the same provider settings as structured
extraction:
environment variables, local LM Studio/Ollama detection, or the top-level
`llm` section in `webuse.yaml`.

### WebSockets

```bash
webuse websocket wss://example.com/socket --send 'ping' --recv 1
webuse websocket wss://example.com/socket --send-json '{"ping":true}' --recv 2
webuse websocket wss://example.com/socket --async --send 'ping'
```

WebSocket commands accept the same request option flags as fetch for headers,
cookies, proxy, TLS, and fingerprint settings.

The CLI uses curl_cffi directly and displays decoded payloads without frame
flags. In Python, use curl_cffi's WebSocket APIs directly; Webuse does not expose
separate socket types or connection helpers:

```python
from curl_cffi import AsyncSession
from curl_cffi.requests.websockets import WebSocket

with WebSocket() as ws:
    ws.connect("wss://example.com/socket")
    ws.send_json({"ping": True})
    print(ws.recv_json())


async def read_socket():
    async with AsyncSession() as session:
        async with session.ws_connect("wss://example.com/socket") as ws:
            await ws.send_str("ping")
            return await ws.recv_str()
```

Malformed `KEY=VALUE` arguments produce explicit errors before a request is
sent.
