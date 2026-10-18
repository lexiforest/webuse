# webuse GUI

SolidStart 1.x control plane for webuse projects, built with Vinxi. Node owns the UI, SQLite database,
scheduler, execution queue, and crawler subprocess lifecycle. Each execution starts an
independent process: `python -m webuse.cli crawl` by default, or the project's configured shell command.

The home screen starts with a crawler prompt, then opens project files beside the
assistant. Executions, logs, records, schedules, and settings remain directly accessible
through the dashboard. This is the implemented local control plane, not yet the
isolated cloud agent runtime.

[HUMAN.md](../HUMAN.md) defines the product direction and must never be edited by
agents. See [PLAN.md](../PLAN.md) for the derived implementation plan.

Use Node.js 22.19 or newer. Node.js 26 is supported.

## Run the packaged UI

Released Python packages include the compiled server and browser assets:

```bash
uv add webuse
uv run webuse serve
```

The launcher requires Node.js 22.19+ on PATH, opens `http://127.0.0.1:2951/`, and
stops with Ctrl+C. npm is not required. Use `--no-open`, `--port`, `--host`, and
`--data-dir` as needed. The default bind address is `127.0.0.1`.

Data defaults to `~/.webuse` (or `WEBUSE_UI_DATA_DIR`): `webuse.db`
stores metadata/settings, `workspaces/` stores working source, and `executions/`
stores execution outputs. `WEBUSE_DB_PATH`, `WEBUSE_WORKSPACE_DIR`, and
`WEBUSE_WORK_DIR` override these paths. The workspace root defaults to a
`workspaces` directory beside the database. Crawlers use the launcher's active Python
interpreter unless `WEBUSE_PYTHON_COMMAND` is set.

### Execution terminology

An execution is one attempt to run a project. The UI uses `/executions` for the
queue and history; **Run** remains the action that starts an execution.

- `/api/executions` lists `{ executions }`; creation and lookup by `id` return
  `{ execution }`. Delete by `id` cancels a queued or running execution.
- Logs, data, and their UI links filter with `execution_id`.
- Harness inspects stored results with `inspect_execution({ executionId })`.
- Custom crawler commands receive `WEBUSE_EXECUTION_ID`.

These names replace the previous run-based routes, fields, and environment
variable without compatibility aliases. New output defaults to `executions/`;
existing output folders are not moved, and explicit work-directory settings
continue to apply. Existing SQLite execution records remain available.

### Project conversations

The New page creates a project on the first message and opens `/projects/<id>`
in Harness. The project ID is the conversation's public identifier. The expandable
Projects navigation lists projects by recent activity; All projects opens the
management table. Files, Visual, and Settings remain tabs within the same project.

`POST /api/projects` accepts `{ prompt }` to create a crawler workspace and save
the initial user message before navigation. The Harness history endpoint returns
`pendingMessageId` until that message is started. A request with that ID consumes
the saved prompt once, so reloading before the first turn does not lose it or
append it twice. Later messages continue the project's existing Pi session.

## Develop from source

### UI components

Use [SolidUI](https://www.solid-ui.com/docs/introduction), the SolidJS port of
shadcn/ui, following HuGame's source-owned component setup. Components live in
`src/components/ui/` and use Kobalte primitives, Tailwind semantic colors from
`src/app.css`, `cn()` from `src/lib/utils.ts`, and class-variance-authority for
button variants. Edit these local sources; there is no React shadcn dependency.

Use `Button` with `variant="default"` for primary actions, `outline` for secondary
actions, and `destructive` for deletion or cancellation. Router links use
`<Button as={A} href="…">`. Controlled fields put `value`, `onChange`, `disabled`,
and `required` on `TextField`, with `TextFieldLabel` and `TextFieldInput` inside.
The model picker uses `Select`; project tabs and file folders use `Tabs` and
`Collapsible`. The code editor and chat composers keep their specialized controls.
See [third-party notices](public/THIRD_PARTY_NOTICES.md) for component attribution.

### Local development

Install the Python project and UI dependencies, then start one Node process:

```bash
uv sync --extra dev
cd ui
npm ci
npm run dev
```

Configuration lives in `app.config.ts`. Open the URL printed by Vinxi, by default
`http://localhost:2951/`.
Development, preview, and production start default to port 2951. Override the
development port with `npm run dev -- --port 4000`; use
`PORT=4000 npm run preview` or `PORT=4000 npm run start` for the built server.

Direct Node development also defaults to `~/.webuse/webuse.db`; workspaces live
beside it. Existing databases are not moved automatically; use `WEBUSE_DB_PATH`
to keep using a previous database.

The orchestrator discovers `../.venv/bin/python` automatically. Override it and
the control-plane storage paths when needed:

```bash
WEBUSE_PYTHON_COMMAND=/path/to/python \
WEBUSE_DB_PATH=/data/webuse.db \
WEBUSE_WORK_DIR=/data/executions \
npm run dev
```

The same interpreter discovers framework resources for Harness. `workspace_info`
includes `framework.version`, `framework.source`, and `framework.docs` (root and
page index). Editable installs use live Markdown in `docs/src/content/docs`;
installed wheels use their bundled `webuse/_docs`. The skill reads relevant docs
before inspecting framework source. Run `python -m webuse.resources` to inspect
the discovery result directly.

To verify parity with installed users, install the built wheel into a separate
environment and run its Python with `scripts/smoke_ui.py --dev-ui ui` from the
repository root. This tests the dev server with the wheel's Python, docs, and
source. No checkout paths are injected into the agent's framework discovery.

For a direct comparison of both launch modes, run:

```bash
/path/to/wheel-environment/bin/python scripts/smoke_ui.py --compare-dev ui
```

The package CI job runs this comparison after installing the freshly built wheel.
It checks packaged Markdown against the source docs, then captures actual model
requests from `webuse serve` and `npm run dev`. It compares the initial context
and the context after reading the discovered skill and Quick Start: prompts,
tool schemas, model settings, discovery results, skill contents, and documentation.
Only the temporary project workspace and installed skill paths are normalized.
Later crawl logs and execution timestamps are checked for success rather than
compared for equality. All servers, models, pages, and databases are local fixtures.

`WEBUSE_CONCURRENCY` controls the default number of simultaneous crawler
processes. Runtime settings saved through the UI override work directory and
concurrency. Cron schedules use UTC. The database path is fixed at process
startup.

The model indicator appears throughout the dashboard. It shows the selected model
or a disconnected state; click it to open model Settings. With no explicit model
settings, Harness discovers LM Studio, then Ollama, using the framework's Python
helpers. Settings lists discovered models and lets you select one or configure an
OpenAI-compatible endpoint. Saved model settings take precedence over framework
configuration. Without a saved model, Harness reads environment variables, the nearest
`.webuserc.yaml`, and `~/.config/webuse/config.yaml`, in that order of precedence;
local model discovery is the last fallback. Lookup starts in the launch directory
and walks up through home, or the filesystem root when outside home. Only the
nearest file is loaded; ancestor files are not merged. `webuse serve` preserves its launch directory
for this lookup even when `--data-dir` changes runtime storage. Direct Node/npm
launches use their working directory. `WEBUSE_CONFIG_DIR` overrides the lookup
directory. The model indicator and effective settings use this same resolution.
A saved provider's credentials are kept separate from environment credentials. Availability
checks use `/models`; the selected model must also support streaming tool calls.
Set `WEBUSE_LOCAL_MODEL_HOST` to change the discovery host (default `127.0.0.1`).

## Pi assistant

Harness embeds `@earendil-works/pi-coding-agent`, with no separate Pi process or
account. The configured OpenAI-compatible endpoint must support streaming and
tool calls. Pi manages the tool loop, context compaction, retries, and cancellation.
Session entries and tool history are stored in the UI's SQLite database; ambient
Pi configuration, extensions, and credentials are not loaded.

Pi's native `read`, `write`, `edit`, `bash`, `grep`, `find`, and `ls` tools operate
in each project's persistent workspace. Webuse adds `workspace_info`,
`fetch_page`, `run_python`, `run_crawl`, and `inspect_execution`. The bundled
[crawler skill](skills/webuse-crawlers/SKILL.md) is installed outside project
source and readable through `read`; its path is provided in the prompt and
discovery. Page fetching uses Python/curl_cffi. Python checks use the same
workspace, so generated files remain available to later calls and local editors.
Sample crawls enter the normal queue, and their logs and records appear in the
dashboard during execution. Partial records remain after failure or cancellation.
Use **Export JSONL** in Data to download the collected records. No web-search provider or browser tool is configured.

### Working files and Git

The Files view displays the workspace path for opening it in an external editor.
Harness edits persist immediately. Save files writes editor buffers to disk; Save
project also saves project settings. Manual, scheduled, and sample jobs execute
those working files directly. Webuse does not publish, copy, or restore source
snapshots. Use Git yourself for code history and rollback. Changes made after
queueing are visible when a job starts; edits during an execution can affect that execution.
Projects are workspaces of files with an optional crawl command, without a project
type setting. YAML and Python starters only choose the initial files. Built-in Git
import is currently unavailable; previously imported workspaces remain editable
and executable. You can still use Git directly for code history.

The editor polls for disk changes, reloads clean buffers, and preserves dirty
buffers with a conflict notice. Saves and Harness submissions carry a content
revision; stale submissions return HTTP 409. Reload files discards editor buffers
after confirmation. API writes are blocked during a Harness turn.

Storage layout beneath `WEBUSE_WORKSPACE_DIR`:

```text
<project-id>/working/          # editable project files; executions execute here
skills/webuse-crawlers/        # bundled skill
```

The editor scans up to 100 MB and 10,000 files and excludes `.git`, `.venv`,
`venv`, `node_modules`, Python/tool caches, `.DS_Store`, `.env`, `.env.*`
(except `.env.example`), and `.webuse/selectors.json`. These exclusions apply to
editor access, not execution. Large and binary files are preserved by editor saves;
symlinks and special files are not supported in the editor. Supply credentials
through runtime configuration. Back up SQLite and your code. Deleting a project
removes its database records but retains source directories for recovery.

### Worker shutdown

The manager stops accepting work on SIGINT or SIGTERM, forwards the signal to
active crawler process groups, and waits for their exit and final job status.
Workers that do not stop within 1.5 seconds receive SIGKILL, including descendants
left behind after the crawler exits. Pending jobs remain queued for the next start.
The Compose service runs Node directly with `init: true` to reap orphaned children
and allows 15 seconds for shutdown. Forced manager termination (SIGKILL) cannot
run cleanup hooks.

The UI streams text/tool activity and offers Stop. Turns have no tool-count or
elapsed-time limit by default. Settings → Harness optionally sets maximum tool
calls and a turn time limit in seconds; blank or 0 means unlimited. These settings
are stored in SQLite as `harness.maxToolCalls` and `harness.turnTimeoutSeconds`
and apply to the next turn. With either limit enabled, tools execute sequentially
and a reached limit lets the current tool finish before stopping. The assistant
saves a continuation note with the last tool's status; send “continue” to resume
with a fresh budget. Stop still cancels immediately. Python checks retain their
30-second limit and bounded output. Each turn can request three sample crawls,
each limited to 60 seconds including queue time. The default Webuse command
also enforces a 10-request maximum; custom commands must honor the supplied
request budget themselves. The browser editor previews at most 100 text
files, 256 KB per file and 2 MB total; native tools can access larger files on disk.
The editor is read-only during a Harness turn. Shell and Python execute with the UI
user's access and are not sandboxed. Cloud isolation,
resource accounting, and managed crawling services remain separate work.

Run `npm test` for workspace/version behavior, orchestration, and mocked Pi native
tool-loop checks. The installed
wheel test in `scripts/smoke_ui.py` exercises Pi with a local mock model and real
HTTP/Python/crawl tools; no external model calls are needed.

## Python release packaging

Run `uv build` from the repository root with Node.js 22.19+ and npm installed. The
setuptools build runs `npm ci` and `npm run build` with the Node server preset,
then packages `.output/server` and `.output/public` under `webuse/_ui`. This
generated directory is ignored by Git. Editable Python installs skip this build;
use the development server above, or run `uv build` to populate the local bundle.

Both the wheel and source distribution carry the compiled UI. Building a wheel
from the published source distribution requires no Node/npm build tools. Node is
still required to run the UI. SQLite uses Node's built-in `node:sqlite`, so the
bundle has no platform-specific SQLite addon.

## Local and cloud roadmap

- Accept existing Scrapy projects, external-agent code, and built-in Harness output;
  custom commands support Scrapy and arbitrary scripts with the output contract below.
- Offer Run locally and Deploy to cloud using one project/deployment contract.
- Have the LLM monitor crawlers and provide evidence-based advice.
- Generate agentic crawlers whose execution schedules are dynamically controlled
  by an LLM; this is distinct from code generation and monitoring advice.
- Connect the Compose metrics store to dashboard charts, and add streaming logs,
  failed-response diagnosis, and data sanity checks.
- Preserve portable code/providers and make all user data downloadable at any time.

The dashboard currently polls logs and shows stored execution summaries. It does not
yet query Prometheus or implement push-based crawler log streaming, monitoring
advice, or cloud export.
Managed proxies, CAPTCHA solving, browser rendering, Defuddle extraction, and an
integrated LLM API for agentic crawlers and analysis will be configured in cloud
environments and described through preloaded skills.

The current scheduler uses fixed cron expressions. Agentic scheduling remains to
be implemented: the model determines execution timing and the orchestrator enacts
it within configured limits, independently of an open Harness session. Local mode
uses configured model access; the cloud LLM service provides managed access.
Scheduling policy, decision cadence, and model-failure behavior remain open.

## Run the control plane on a server

```bash
npm run build
npm run start
```

PM2 runs the same single Node service:

```bash
pm2 start ecosystem.config.cjs
```

Docker Compose starts the control plane, StatsD exporter, and Prometheus:

```bash
cd ..
docker compose -f ui/compose.yaml up --build
```

The Compose command above runs from the repository root after the preceding
commands in `ui/`. This image packages the control plane. A separate Docker image
for the isolated agent environment is required by the cloud plan and is not yet
provided by this deployment.

## Custom crawl commands

Open a project's **Settings → Crawl command**. Leave it empty for the default
Webuse runner, or enter a shell command, for example:

```sh
scrapy crawl books -o "$WEBUSE_OUTPUT_PATH"
```

The command runs from the persistent project directory through `/bin/sh` (or
`cmd.exe` on Windows; use `%WEBUSE_OUTPUT_PATH%` there). Dependencies must already
be installed. The configured Python's directory is added to PATH.
Manual, scheduled, and Harness sample executions all use this setting.

- `WEBUSE_OUTPUT_PATH`: absolute per-execution JSONL output path. Write one object per line
  and flush output to make records visible during the execution.
- `WEBUSE_PYTHON_COMMAND`: configured Python interpreter.
- `WEBUSE_PROJECT_ID`, `WEBUSE_EXECUTION_ID`: identifiers for logs/metrics.
- `WEBUSE_MAX_REQUESTS`: sample request budget; empty for normal executions. Custom code
  must apply it. The orchestrator still enforces the sample's 60-second deadline.

Exit code zero means success; other codes mean failure. Cancellation is tracked
separately. Logs and emitted records remain inspectable in all cases.

## Compose monitoring

The monitoring services are adapted from `ustats/deploy`, with valid mapping names,
the current exporter configuration flag, and the corrected Prometheus scrape target.
Prometheus is at `http://127.0.0.1:9090`; exporter metrics are at
`http://127.0.0.1:9102/metrics`. Prometheus data has its own named volume.

Send StatsD metrics to `statsd-exporter:8125` from a container, or
`127.0.0.1:8125` from the host. Crawler code must initialize `webuse.metrics` and
attach the metrics adapter to its signal bus; installing this stack does not
instrument arbitrary commands or add time-series charts to Stats automatically.
See the [signals guide](../docs/src/content/docs/references/signals.md).

Compose discovers local models through `host.docker.internal`. The host model
server must listen on an address reachable from Docker; alternatively configure
its reachable endpoint explicitly in Settings.
