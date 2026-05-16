# AGENTS.md

## Project Summary

`webuse` is a small scraping toolkit built around `curl_cffi`.

Current v1 scope:
- sync and async HTTP helpers
- explicit sync and async clients
- sync and async websocket wrappers
- a light HTML parsing layer
- prompt-based smart selectors with local persistence
- queue-driven crawling via `webuse.crawl` / `webuse.acrawl`
- a CLI with `fetch` and `crawl`

Out of scope for now:
- browser automation
- full spider framework
- middleware/checkpointing/pause-resume
- mandatory LLM integration

## Repo Layout

- `src/webuse/__init__.py`: public exports
- `src/webuse/client.py`: sync/async HTTP clients and top-level helpers
- `src/webuse/response.py`: response wrapper and lazy parsing entrypoint
- `src/webuse/parser.py`: lightweight document/element selector layer
- `src/webuse/smart.py`: smart selector persistence and resolution
- `src/webuse/websocket.py`: sync/async websocket wrappers
- `src/webuse/crawl.py`: queue-based crawl engine
- `src/webuse/cli.py`: CLI entrypoint
- `src/webuse/models.py`: shared dataclasses and public models
- `tests/`: unit tests

## HTTP Client

Use `curl_cffi` for all HTTP requests in this project, including research scripts. Do not use `httpx` or `requests` unless explicitly requested.

## Design Rules

- Keep the first-look API simple. Prefer top-level helpers and small examples.
- Keep advanced transport power available. Do not hide `curl_cffi` features behind an overly narrow wrapper.
- Prefer additive abstractions over deep frameworks.
- Crawl logic should stay function-based unless there is a strong reason to introduce class-based spiders.
- Smart selectors must work without an LLM. LLM use is optional and explicit.
- Avoid coupling unrelated layers. The CLI should call the Python APIs, not duplicate their logic.

## Coding Guidelines

- Target Python 3.11+.
- Prefer standard library first.
- Keep dependencies minimal.
- Preserve lazy behavior where it matters, especially response parsing.
- Prefer small focused helpers over inheritance-heavy designs.
- Keep public names stable and unsurprising.
- When adding new request options, wire them consistently across sync, async, and CLI surfaces where applicable.

## Crawl Expectations

`webuse.crawl` and `webuse.acrawl` should continue to support:
- one or many seed URLs
- queue-based discovery of new URLs
- depth tracking
- follow rules via CSS/XPath or callbacks
- URL normalization before dedupe
- domain/scope filtering
- result/error/stats aggregation

Do not turn crawl into a full spider framework unless explicitly requested.

## Smart Selector Expectations

Default smart selector storage is local:
- `.webuse/selectors.json`

Agents should:
- keep this path configurable in code
- avoid committing generated selector state
- preserve deterministic matching before optional resolver/LLM fallback

## CLI Expectations

The CLI should remain usable for no-code workflows:
- `webuse fetch ...`
- `webuse crawl ...`

Defaults:
- machine-friendly output
- JSONL to stdout
- config-file support should stay aligned with Python API naming

## Dependency Management

Use `uv` for all dependency management. Do not use `pip install` directly.

- Install project deps: `uv sync`
- Add a dependency: `uv add <package>`
- Add a dev dependency: `uv add --dev <package>`
- Run a script: `uv run python3 <script.py>`
- Run a tool: `uv run pytest`

## Testing and Verification

Preferred checks:
- `uv run python3 -m compileall src tests`
- `uv run pytest -q`

Some tests depend on optional runtime packages such as:
- `pytest`
- `curl_cffi`
- `lxml`
- `cssselect`
- `PyYAML`

If these are unavailable, at minimum run compile/import smoke checks and state the limitation clearly.

## Editing Notes

- Use `apply_patch` for file edits.
- Keep files ASCII unless a file already requires Unicode.
- Do not add generated runtime data to the repo.
- Do not add network-dependent tests unless necessary.
- Prefer fake clients/responses in tests over live HTTP calls.
