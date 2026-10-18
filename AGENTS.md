# AGENTS.md

## Product direction

Webuse is a local-first crawler development toolkit with a managed cloud
environment for production execution. Our primary users are technical users who
write scraping code with coding agents such as Codex and Claude. These users
want inspectable code, freedom to use their own tools, and less work operating
crawlers against changing websites.

Read [HUMAN.md](HUMAN.md) first: it is the human-maintained source of truth for
product direction. Never edit HUMAN.md, including formatting or typo fixes. Align
other documentation with it; when a detail is unspecified, keep it open rather
than inventing a decision. HUMAN.md takes precedence over derived product docs.

Read README.md for the general picture.

Read `docs` directory for detailed documentation when necessary.

The product will support:

- Generating new crawlers with the framework, CLI, examples, and skills.
- A complete local experience with Harness, an orchestrator, project code, and a
  crawler dashboard, including LLM monitoring and advice.
- A consistent workflow from local execution to optional cloud deployment.
- Cloud workspaces with scraping services made available to agents through
  preloaded skills and runtime configuration.
- No vendor lock-in: portable crawler projects and all user data downloadable at
  any time. Provider integrations must remain replaceable.

The hosted website creates and executes crawlers in cloud workspaces. Local use
must remain useful without a Webuse Cloud account. Users may supply their own
model credentials and infrastructure providers.

The product promise is: bring a crawler or generate one, validate it locally,
and deploy it to a prepared environment with the scraping services it needs.

Support three sources of crawler code:

1. **Existing Scrapy projects and other code:** declare how to run them and make
   minimal integration changes.
   Adopting the Webuse framework must not be a prerequisite for cloud execution.
2. **External coding agents:** use Codex, Claude, or another agent with the Python
   framework, examples, and skills when helpful.
3. **Built-in Harness:** describe a crawler and generate inspectable project files
   in Webuse's local or cloud environment.

## Coding & Chatting

- Ask the user whether backwards compatibility should be maintained, do NOT make
  assumption by yourself.
- Prefer concise, minimal, consistent implementation.
- All the responses to the user MUST be concise, unless explicitly requested.
- If the README.md needs to be updated, ask the user.

## Repository map

The repository currently contains a Python scraping framework and a Node/SolidStart
local control plane.

Managed cloud deployment, sandboxed tenant workspaces, hosted browsers, CAPTCHA
vendor integration, and the extraction API are in other private repository;
Their API is still not public yet. (CHANGE THIS WHEN ITS EXPLICTLY PROVIDED)

### Harness

Built-in Harness embeds Pi's coding-agent SDK with native filesystem and shell tools
in persistent project directories, plus Webuse HTTP inspection, Python, sample
crawl, and execution inspection tools. Working source is stored on disk; SQLite owns
metadata and execution records.

Pi owns the agent loop, streaming, session context, retries, and compaction; keep this integration
small instead of rebuilding those mechanisms.

The scheduler manual, scheduled, and sample jobs execute the spider project directly,
without source snapshots or publication.
Users will track and restore their code with Git. Harness edits persist immediately.

The UI and Node orchestrator remain Webuse-owned.
The bundled skill lives in `ui/skills/webuse-crawlers/SKILL.md`.
Model endpoints must support streaming OpenAI-compatible tool calls. Local shell/Python
tools run as the UI user; their time limits are not a security sandbox. Pi session
entries persist in SQLite.

### Files

- `src/webuse/__init__.py`: public Python exports.
- `src/webuse/http/client.py`: thin curl_cffi session subclasses and top-level helpers.
- `src/webuse/http/response.py`: HTTP-to-document bridge, follow-up requests, and crawl metadata.
- `src/webuse/extract/parser.py`: lazy selectolax/Lexbor parsing, CSS selectors, and
  Document's LLM extraction convenience methods.
- `src/webuse/extract/`: HTML parsing, declarative extraction, response-handler result adapters,
  LLM value extraction, and element resolution.
- `src/webuse/llm.py`: model configuration and client helpers.
- `src/webuse/engine/`: function-based sync/async crawl engines and crawl state.
- `src/webuse/spider/`: shared configuration, per-execution state, and sync/async Spider classes.
- `src/webuse/pipelines/`: ItemPipeline, internal execution helpers, and built-in item destinations.
- `src/webuse/cli/`: project creation, generation, fetch, crawl, WebSocket commands,
  and the `webuse serve` launcher for the packaged Node control plane.
- `setup.py`: release build hooks; compile the UI into generated `src/webuse/_ui/`.
- `src/webuse/config.py`, `models.py`, `exceptions.py`: configuration, shared models,
  and public exceptions.
- `src/webuse/signals.py`, `metrics/`: events, metrics integration, and StatsD-style emission.
- `ui/`: SolidStart UI and Node control plane; owns SQLite, APIs, scheduling,
  the execution queue, and Python crawler subprocesses.
- `tests/`, `ui/tests/`: Python tests and control-plane smoke tests.
- `docs/`: Astro/Starlight documentation site with Markdown pages in
  `docs/src/content/docs/`: The docs raw content
- `examples/`: crawler examples.
- Keep Harness, Code, and Dashboard connected to the same project and execution model.
  Harness creates and operates crawlers; code defines their behavior; the dashboard
  exposes executions, records, failures, schedules, and usage without requiring a Harness session.
- Keep the CLI as a client of the Python APIs; do not duplicate crawl logic there.
  Keep control-plane orchestration separate from the crawler runtime.
- Preserve the current Node/Python ownership boundary unless an approved task
  changes it. A local subprocess runner is not a tenant isolation boundary.
- Prefer a small, additive deployment contract over a deep framework. Its exact
  schema and arbitrary-script runner are still to be designed.

### Rust implementation

We have a prototype of the rust implementation in the `crates` directory. In rust,
all the logic are defined as yaml files.

## Cloud offering

Webuse Cloud is implemented in another private repo. Here are the things we need to
prepare for the cloud execution.

- Treat customer code as untrusted, whether launched through Harness, SSH, or a job.
- The local UI is smiliar to the cloud one, but without permissions and quotas.
- SSH is a proposed workspace access method, not permission to bypass isolation
  or allowances. Its authentication and lifecycle are still open.
- Kubernetes is the starting orchestration platform. The sandbox runtime and
  tenant isolation design are not selected yet.
- Provide a Docker image for the isolated agent environment. The current UI image
  is a control-plane image, not that environment or a complete isolation boundary.
- Prefer standard proxy and browser interfaces where they preserve existing code.
  Keep provider integrations replaceable and support user-supplied credentials.
- Keep HTTP the inexpensive path when sufficient. Browser use, solving, retries,
  and more expensive proxy routes must respect explicit configuration and budgets.
- Skills explain stable workflows and service APIs. Runtime discovery reports
  available services, supported options, and remaining allowances.
- Supply credentials through runtime configuration, never through skill text,
  prompts, committed files, or generated source.
- Reuse skills across local coding agents and cloud agents. Cloud preconfiguration
  should remove setup work, not invent a separate crawler programming model.

## Python and crawl conventions

- Use `curl_cffi` for all HTTP requests in this project, including research scripts.
  Do not use `httpx` or `requests` unless explicitly requested.
- Require Python 3.11+ for the package and development environment. Keep package
  metadata, Python examples in the docs, and CI aligned with this minimum.
- Prefer the standard library, minimal dependencies, and small focused helpers.
- Keep top-level helpers easy to use and advanced `curl_cffi` transport options
  accessible. Preserve lazy response parsing.
- Delegate HTTP/WebSocket transport, response decoding, cookies, retries, and
  streaming to curl_cffi. Keep HTML parsing, extraction, and crawl policy in
  Webuse. Extend responses through `response_class`; do not copy transport fields
  into a second response object. Use `response.crawl_request` for crawl metadata
  and preserve the native HTTP request in `response.request`.
- Use curl_cffi directly for WebSockets. Keep the WebSocket CLI, but do not add
  a separate Webuse Python WebSocket API or re-export curl_cffi socket types.
- Wire request options consistently across sync, async, and CLI surfaces where
  applicable.
- Keep crawl logic function-based in `engine/`, with lightweight Spider and
  ItemPipeline idioms. Spider compiles configuration, the engine owns crawl
  policy, and spiders run pipelines using internal helpers in `pipelines/utils.py`.
- Keep `pipelines` in spider configuration, including inline spider entries,
  rather than project defaults. Shared implementations may live in `pipelines.py`;
  configured pipeline paths resolve relative to the project root.
- Project creation does not generate root `items.py` or `pipelines.py`. Spider
  generation defines its starter model and pipeline classes in `spiders/<name>.py`.
- Preserve one or many seeds, queue discovery, depth tracking, CSS/callback
  follow rules, URL normalization before dedupe, scope filtering, and aggregation
  of results, errors, and stats.
- Preserve config-driven and Python-spider crawling. Do not mistake persistent
  queue implementations for a complete checkpointing or pause/resume product.
- Keep one CLI/harness execution workflow: `webuse crawl` runs a project
  directory and registered spider names; `webuse gen` requires an existing
  project. Keep creation and generation focused on project scaffolding.
  Direct Python library APIs
  remain usable without a project; Scrapy/arbitrary-script adapters are planned.
- Use YAML for Webuse configuration in documentation, examples, and new project
  scaffolds. TOML loading and explicit generation remain supported, but not mentioned.
- In documentation examples, enter the project with `cd PROJECT` and run
  generation and crawl commands from there using their current-directory defaults.
- Plain selectors must work without an LLM. `find(css=...)` and
  `find_all(css=...)` select existing nodes; explicit `llm=...` selects nodes
  through a model. Both preserve document order and share missing-match behavior.
- Declarative extraction uses page type -> named item -> `fields`, or
  `llm_extract` plus an output `schema`, with optional `item_css`.
  Validate before crawling; keep selector-string field shorthand and
  Python callbacks, without inferring alternative dictionary shapes.
- Use selectolax's Lexbor backend for HTML parsing. Support CSS selectors and
  regex extraction, not XPath. `llm_extract(prompt, schema=...)` transforms content
  into validated data; selection returns existing elements without caching.
  Use `afind`, `afind_all`, and `allm_extract` for async model calls. Fields and
  follow rules share `css`/`llm` selectors and `all`; retain the distinction
  between selection, value reading, structured interpretation, and crawl policy.
- Preserve machine-friendly CLI output, including JSONL workflows, and align
  config-file naming with Python API naming. Document command-specific formats
  accurately rather than claiming every command emits JSONL by default. However, when
  printing to an interactive shell, make the output indented for JSON output.


## Development

Use `uv` for Python dependency management; do not use `pip install` directly.

- Install: `uv sync --extra dev`.
- Add a runtime dependency: `uv add <package>`.
- Add a development dependency: `uv add --dev <package>`.
- Run Python: `uv run python3 <script.py>`.
- Compile: `uv run python3 -m compileall src tests`.
- Test: `uv run pytest -q`.

The UI uses npm and requires Node.js 22.19 or newer. Run commands from `ui/`:

- Install locked dependencies: `npm ci`.
- Develop: `npm run dev`.
- Check types: `npm run typecheck`.
- Test orchestration and the Pi tool loop: `npm test`.
- Build: `npm run build`.

Python releases include the compiled UI: run `uv build` from the repository root
with Node.js 22.19+ and npm available. The build installs locked npm dependencies
and packages the Node server and browser assets into both sdist and wheel.
Editable Python installs skip this build. Never edit or commit `src/webuse/_ui/`.
Use Node's built-in SQLite; do not introduce native Node addons into the portable
bundle.

`webuse serve` opens the bundled UI on loopback port 2951 using Node.js 22.19+ without
npm. Store runtime data outside the installed package (default `~/.webuse/ui`)
and run crawlers with the launcher's Python interpreter unless explicitly
overridden. Verify release artifacts in a fresh Python environment with
`python scripts/smoke_ui.py`; it tests local HTTP only.

Run checks appropriate to the changed behavior. Documentation-only changes need
link, example, and consistency checks rather than an unrelated full test run.
Prefer fake clients and responses; avoid network-dependent tests unless needed.
If optional packages or services prevent verification, run available compile or
import checks and state the limitation. Do not add dependencies solely to check
prose.

## Editing rules

- Use `ruff` to format the code.
- Never edit HUMAN.md. It is managed exclusively by the maintainer.
- Preserve unrelated user changes, including staged work.
- Do not add generated runtime data, credentials, or selector state to the repo.
- DO NOT COMMIT for the user.
