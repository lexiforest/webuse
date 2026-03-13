# AGENTS.md

## Project Summary

`getkit` is a small scraping toolkit built around `curl_cffi`.

Current v1 scope:
- sync and async HTTP helpers
- explicit sync and async clients
- sync and async websocket wrappers
- a light HTML parsing layer
- prompt-based smart selectors with local persistence
- queue-driven crawling via `getkit.crawl` / `getkit.acrawl`
- a CLI with `fetch` and `crawl`

Out of scope for now:
- browser automation
- full spider framework
- middleware/checkpointing/pause-resume
- mandatory LLM integration

## Repo Layout

- `src/getkit/__init__.py`: public exports
- `src/getkit/client.py`: sync/async HTTP clients and top-level helpers
- `src/getkit/response.py`: response wrapper and lazy parsing entrypoint
- `src/getkit/parser.py`: lightweight document/element selector layer
- `src/getkit/smart.py`: smart selector persistence and resolution
- `src/getkit/websocket.py`: sync/async websocket wrappers
- `src/getkit/crawl.py`: queue-based crawl engine
- `src/getkit/cli.py`: CLI entrypoint
- `src/getkit/models.py`: shared dataclasses and public models
- `tests/`: unit tests

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

`getkit.crawl` and `getkit.acrawl` should continue to support:
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
- `.getkit/selectors.json`

Agents should:
- keep this path configurable in code
- avoid committing generated selector state
- preserve deterministic matching before optional resolver/LLM fallback

## CLI Expectations

The CLI should remain usable for no-code workflows:
- `getkit fetch ...`
- `getkit crawl ...`

Defaults:
- machine-friendly output
- JSONL to stdout
- config-file support should stay aligned with Python API naming

## Testing and Verification

Preferred checks:
- `python3 -m compileall src tests`
- `python3 -m pytest -q`

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
