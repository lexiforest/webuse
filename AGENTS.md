# AGENTS.md

## Product direction

Webuse is a local-first crawler development toolkit with a planned managed cloud
environment for production execution. Our primary users are technical users who
write scraping code with coding agents such as Codex and Claude.

Read [HUMAN.md](HUMAN.md) first: it is the human-maintained source of truth for
product direction. Never edit HUMAN.md, including formatting or typo fixes. Align
other documentation with it; when a detail is unspecified, keep it open rather
than inventing a decision. HUMAN.md takes precedence over derived product docs.

Read [PLAN.md](PLAN.md) for product decisions, delivery sequence, and open questions.
Use [README.md](README.md) for the public introduction and working examples. Keep
implemented behavior distinct from roadmap commitments in documentation and UI.

The product must support:

- Bringing existing Scrapy projects and other crawler code with minimal changes
  and no mandatory migration to the Webuse Python framework.
- Generating new crawlers with the optional framework, CLI, examples, and skills.
- Generating agentic crawlers whose execution schedules are dynamically controlled
  by an LLM. This is a runtime capability, not merely AI-generated crawler code.
- A complete local experience with Chat, an orchestrator, project code, and a
  crawler dashboard, including LLM monitoring and advice.
- Automatic LM Studio and Ollama discovery for local Chat, with explicit provider
  settings taking precedence.
- A consistent workflow from local execution to optional cloud deployment.
- Cloud workspaces with scraping services made available to agents through
  preloaded skills and runtime configuration.
- A Defuddle-based HTML-to-Markdown extraction API as a planned service.
- An integrated cloud LLM API for agentic crawlers and analysis.
- No vendor lock-in: portable crawler projects and all user data downloadable at
  any time. Provider integrations must remain replaceable.

The hosted website creates and executes crawlers in cloud workspaces. Local use
must remain useful without a Webuse Cloud account. Users may supply their own
model credentials and infrastructure providers.

## Current implementation and repository map

The repository currently contains a Python scraping framework and a Node/SolidStart
local control plane. Managed cloud deployment, sandboxed tenant workspaces, hosted
browsers, CAPTCHA vendor integration, and the extraction API are planned work;
do not imply that they are already available.

The Python provider helpers already discover local LM Studio and Ollama servers.
Built-in Chat embeds Pi's coding-agent SDK with Webuse-specific draft file,
HTTP inspection, Python, sample crawl, and run inspection tools. Pi owns the agent
loop, streaming, session context, retries, and compaction; keep this integration
small instead of rebuilding those mechanisms. The UI and Node orchestrator remain
Webuse-owned. The bundled skill lives in `ui/skills/webuse-crawlers/SKILL.md`.
Model endpoints must support streaming OpenAI-compatible tool calls. Local Python
tools run as the UI user; their time limits are not a security sandbox. Pi session
entries persist in SQLite. Do not load ambient Pi extensions, skills, or credentials.
The UI Chat currently uses configured settings; automatic discovery there, LLM
monitoring/advice, a metrics time-series database, and full data export still need
implementation. Existing log views poll stored logs; streaming logs are a target.
Current scheduling uses fixed cron expressions. Agentic scheduling and the
integrated cloud LLM API are not implemented; existing model-provider helpers
and Chat calls are not those services.

- `src/webuse/__init__.py`: public Python exports.
- `src/webuse/client.py`: sync/async HTTP clients and top-level helpers.
- `src/webuse/response.py`: response wrapper and lazy parsing entry point.
- `src/webuse/parser.py`: document and element selectors.
- `src/webuse/smart/`: smart extraction, selector persistence, and resolution.
- `src/webuse/llm.py`: model configuration and client helpers.
- `src/webuse/crawl/`: function-based sync/async crawl engines and crawl state.
- `src/webuse/spider/`: sync/async Spider classes.
- `src/webuse/pipelines/`: pipeline interfaces and built-in item destinations.
- `src/webuse/cli/`: project creation, generation, fetch, crawl, WebSocket commands,
  and the `webuse ui` launcher for the packaged Node control plane.
- `setup.py`: release build hooks; compile the UI into generated `src/webuse/_ui/`.
- `src/webuse/websocket.py`: sync/async WebSocket wrappers.
- `src/webuse/config.py`, `models.py`, `exceptions.py`: configuration, shared models,
  and public exceptions.
- `src/webuse/signals.py`, `metrics.py`, `ustats/`: events and metrics integration.
- `ui/`: SolidStart UI and Node control plane; owns SQLite, APIs, scheduling,
  the run queue, and Python crawler subprocesses.
- `tests/`, `ui/tests/`: Python tests and control-plane smoke tests.
- `docs/`, `examples/`: detailed documentation and examples.

## Product and architecture rules

- Keep Chat, Code, and Dashboard connected to the same project and run model.
  Chat creates and operates crawlers; code defines their behavior; the dashboard
  exposes runs, records, failures, schedules, and usage without requiring a chat.
- Agent edits must produce inspectable project files and configuration. Ordinary
  crawlers must run without an agent or LLM present unless their extraction
  explicitly depends on one. Agentic crawlers explicitly require model access
  for dynamic scheduling; do not apply the model-free runtime assumption to them.
- Keep AI-assisted code generation, monitoring/advice, and agentic scheduling
  distinct. Agentic scheduling lets an LLM determine when a crawler executes; it
  does not imply autonomous code repair, deployment, or browser navigation.
- The orchestrator must validate and enact LLM scheduling decisions within the
  configured execution and spending limits. The scheduling contract, decision
  cadence, and model-failure behavior remain open design decisions.
- Keep crawler logic portable. Separate entry points, dependencies, inputs,
  secrets, outputs, and service configuration from the execution target.
- Do not require imported scripts to subclass a Webuse type. Advanced telemetry
  and record-level features may require an explicit adapter or reporting API.
- Treat existing Scrapy projects, external-agent code, and built-in Chat code as
  supported product entry points. Current Webuse CLI support is not proof that a
  Scrapy project can already run unchanged.
- Make Run locally and Deploy to cloud explicit choices in the local UI once
  implemented. Successful local execution does not guarantee cloud success;
  validate dependencies, network identity, sessions, and service configuration.
- LLM monitoring should provide evidence-based advice from metrics, logs, failed
  responses, and data checks. Do not turn advice into unrequested code deployment.
- Build a simple metrics emitter, a StatsD-like wire protocol, and a time-series
  database for the dashboard. Reuse the existing `webuse.ustats` emitter where
  appropriate; the database and dashboard ingestion are not implemented yet.
- Keep CLI/API discovery consistent. MCP is an optional integration proposal from
  earlier discussion, not a requirement in the current HUMAN.md; its inclusion,
  tool set, and delivery scope remain open.
- Keep the CLI as a client of the Python APIs; do not duplicate crawl logic there.
  Keep control-plane orchestration separate from the crawler runtime.
- Preserve the current Node/Python ownership boundary unless an approved task
  changes it. A local subprocess runner is not a tenant isolation boundary.
- Prefer a small, additive deployment contract over a deep framework. Its exact
  schema and arbitrary-script runner are still to be designed.
- Keep durable workspace state separate from active compute. Scheduled runs
  should use a saved project version independently of an interactive session.
- Do not introduce cloud-only code paths into otherwise portable crawler logic.
  Reveal environment differences before execution instead of silently changing
  crawler behavior.

## Crawling services and agent integration

The cloud direction is managed proxies, on-demand hosted browsers, a separate
CAPTCHA solver integration, HTML-to-Markdown extraction, and an integrated LLM API
for agentic crawlers and analysis. Bright Data must not
be a required default dependency of the base plan. Vendors and allowances remain
open decisions, except the worker sizes and Free runtime allowance specified below.

- Prefer standard proxy and browser interfaces where they preserve existing code.
  Keep provider integrations replaceable and support user-supplied credentials.
- Browser hosting is a cloud capability; do not build a new browser engine or make
  browser automation a mandatory dependency of the Python HTTP framework.
- Rendering and CAPTCHA handling are separate capabilities. Do not promise that
  a browser or solver works against every target.
- Keep HTTP the inexpensive path when sufficient. Browser use, solving, retries,
  and more expensive proxy routes must respect explicit configuration and budgets.
- Use Defuddle for HTML-to-Markdown extraction. Input modes, content policy, API
  contract, and the local equivalent remain design decisions; the engine choice
  is settled by HUMAN.md.
- Provide integrated monitoring, streaming logs, diagnosis from failed responses
  and logs, and data sanity checks as product requirements, not optional extras.
- Skills explain stable workflows and service APIs. Runtime discovery reports
  available services, supported options, and remaining allowances.
- Supply credentials through runtime configuration, never through skill text,
  prompts, committed files, or generated source.
- Reuse skills across local coding agents and cloud agents. Cloud preconfiguration
  should remove setup work, not invent a separate crawler programming model.
- Document LLM service capabilities through skills/discovery and supply provider
  access through runtime configuration. Preserve local/user-supplied model access;
  cloud API shape, supported models, and included inference allowances remain open.

## Cloud execution constraints

The business planning baseline is $99/month with a target margin of at least 50%.
HUMAN.md sets Pro and Free environments to 1 vCPU and 2 GiB RAM. Pro is monthly;
Free includes four hours of runtime. Pro runtime hours, whether Free hours renew,
the allocation scope, concurrency, and service allowances are not specified. Do
not interpret monthly as unlimited compute or four hours as a monthly reset.
The margin definition, vendor costs, and remaining allowances are still open.

- Treat customer code as untrusted, whether launched through Chat, SSH, or a job.
- Enforce resource limits and usage accounting outside user-controlled code.
- Bound CPU, memory, temporary disk, process growth, duration, concurrency, logs,
  results, network traffic, and paid service consumption.
- Isolate customer workspaces from other tenants, host administration, cluster
  credentials, internal services, and cloud instance credentials.
- SSH is a proposed workspace access method, not permission to bypass isolation
  or allowances. Its authentication and lifecycle are still open.
- Kubernetes is the starting orchestration platform. The sandbox runtime and
  tenant isolation design are not selected yet.
- Provide a Docker image for the isolated agent environment. The current UI image
  is a control-plane image, not that environment or a complete isolation boundary.
- Do not treat Kubernetes resource quotas as a monthly billing system. Cloud
  execution also needs a usage ledger and cutoff enforcement.

## Python and crawl conventions

- Use `curl_cffi` for all HTTP requests in this project, including research scripts.
  Do not use `httpx` or `requests` unless explicitly requested.
- Require Python 3.11+ for the package and development environment. Keep package
  metadata, the docs workspace, and CI aligned with this minimum.
- Prefer the standard library, minimal dependencies, and small focused helpers.
- Keep top-level helpers easy to use and advanced `curl_cffi` transport options
  accessible. Preserve lazy response parsing.
- Wire request options consistently across sync, async, and CLI surfaces where
  applicable.
- When a refactor is needed, ask whether backward compatibility is required unless
  the user has already specified the compatibility requirements for that work.
- Keep crawl logic function-based, with lightweight Spider and Pipeline idioms.
- Preserve one or many seeds, queue discovery, depth tracking, CSS/XPath/callback
  follow rules, URL normalization before dedupe, scope filtering, and aggregation
  of results, errors, and stats.
- Preserve config-driven and Python-spider crawling. Do not mistake persistent
  queue implementations for a complete checkpointing or pause/resume product.
- Plain selectors must work without an LLM. Keep deterministic selector matching
  before optional resolver/LLM fallback where applicable.
- Keep smart-selector storage configurable; the default is
  `.webuse/selectors.json`. Never commit generated selector state.
- Preserve machine-friendly CLI output, including JSONL workflows, and align
  config-file naming with Python API naming. Document command-specific formats
  accurately rather than claiming every command emits JSONL by default.

## Dependencies and verification

Use `uv` for Python dependency management; do not use `pip install` directly.

- Install: `uv sync --extra dev`.
- Add a runtime dependency: `uv add <package>`.
- Add a development dependency: `uv add --dev <package>`.
- Run Python: `uv run python3 <script.py>`.
- Compile: `uv run python3 -m compileall src tests`.
- Test: `uv run pytest -q`.

The UI uses npm and requires Node.js 24 or newer. Run commands from `ui/`:

- Install locked dependencies: `npm ci`.
- Develop: `npm run dev`.
- Check types: `npm run typecheck`.
- Test orchestration and the Pi tool loop: `npm test`.
- Build: `npm run build`.

Python releases include the compiled UI: run `uv build` from the repository root
with Node.js 24+ and npm available. The build installs locked npm dependencies
and packages the Node server and browser assets into both sdist and wheel.
Editable Python installs skip this build. Never edit or commit `src/webuse/_ui/`.
Use Node's built-in SQLite; do not introduce native Node addons into the portable
bundle. Legacy UI database/settings compatibility is not required for this change.

`webuse ui` opens the bundled UI on loopback port 2951 using Node.js 24+ without
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

- Never edit HUMAN.md. It is maintained exclusively by the user.
- Use `apply_patch` for file edits.
- Keep files ASCII unless the file already requires Unicode.
- Preserve unrelated user changes, including staged work.
- Do not add generated runtime data, credentials, or selector state to the repo.
- Update PLAN.md when a product decision is explicitly settled; proposals and
  implementation tasks must remain visibly separate from confirmed decisions.
- Do not treat this roadmap as authorization to implement every planned feature.
- DO NOT COMMIT for the user.
