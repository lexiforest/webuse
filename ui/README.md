# webuse GUI

SolidStart 1.x control plane for webuse projects, built with Vinxi. Node owns the UI, SQLite database,
scheduler, run queue, and crawler subprocess lifecycle. Each run starts an
independent Python process using `python -m webuse.cli crawl`.

The home screen starts with a crawler prompt, then opens project files beside the
assistant. Runs, logs, records, schedules, and settings remain directly accessible
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

Data defaults to `~/.webuse/ui` (or `WEBUSE_UI_DATA_DIR`): `webuse-ui.sqlite`
stores metadata/settings, `workspaces/` stores working source, and `runs/`
stores run outputs. `WEBUSE_DB_PATH`, `WEBUSE_WORKSPACE_DIR`, and
`WEBUSE_WORK_DIR` override these paths. The workspace root defaults to a
`workspaces` directory beside the database. Crawlers use the launcher's active Python
interpreter unless `WEBUSE_PYTHON_COMMAND` is set.

## Develop from source

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

The orchestrator discovers `../.venv/bin/python` automatically. Override it and
the control-plane storage paths when needed:

```bash
WEBUSE_PYTHON_COMMAND=/path/to/python \
WEBUSE_DB_PATH=/data/webuse-ui.sqlite \
WEBUSE_WORK_DIR=/data/runs \
npm run dev
```

`WEBUSE_CONCURRENCY` controls the default number of simultaneous crawler
processes. Runtime settings saved through the UI override work directory and
concurrency. Cron schedules use UTC. The database path is fixed at process
startup.

Configure the Harness model, endpoint, and credentials in Settings. Automatic LM
Studio/Ollama discovery exists in the Python helpers; integrating that discovery
into UI Harness is planned. Explicit settings should take precedence.

## Pi assistant

Harness embeds `@earendil-works/pi-coding-agent`, with no separate Pi process or
account. The configured OpenAI-compatible endpoint must support streaming and
tool calls. Pi manages the tool loop, context compaction, retries, and cancellation.
Session entries and tool history are stored in the UI's SQLite database; ambient
Pi configuration, extensions, and credentials are not loaded.

Pi's native `read`, `write`, `edit`, `bash`, `grep`, `find`, and `ls` tools operate
in each project's persistent workspace. Webuse adds `workspace_info`,
`fetch_page`, `run_python`, `run_crawl`, and `inspect_run`. The bundled
[crawler skill](skills/webuse-crawlers/SKILL.md) is installed outside project
source and readable through `read`; its path is provided in the prompt and
discovery. Page fetching uses Python/curl_cffi. Python checks use the same
workspace, so generated files remain available to later calls and local editors.
Sample crawls enter the normal queue, and their logs and records appear in the
dashboard. No web-search provider or browser tool is configured.

### Working files and Git

The Files view displays the workspace path for opening it in an external editor.
Harness edits persist immediately. Save files writes editor buffers to disk; Save
project also saves project settings. Manual, scheduled, and sample jobs execute
those working files directly. Webuse does not publish, copy, or restore source
snapshots. Use Git yourself for code history and rollback. Changes made after
queueing are visible when a job starts; edits during a run can affect that run.
Git imports clone once into an editable workspace; remote updates are explicit.

The editor polls for disk changes, reloads clean buffers, and preserves dirty
buffers with a conflict notice. Saves and Harness submissions carry a content
revision; stale submissions return HTTP 409. Reload files discards editor buffers
after confirmation. API writes are blocked during a Harness turn.

Storage layout beneath `WEBUSE_WORKSPACE_DIR`:

```text
<project-id>/working/          # editable project files; runs execute here
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

The UI streams text/tool activity and offers Stop. A turn is limited to five
minutes and 30 tool calls; Python checks have a 30-second limit and bounded
output. Each turn can request three sample crawls, each limited to 10 requests
and 60 seconds including queue time. The browser editor previews at most 100 text
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
  the current runner only handles Webuse projects.
- Offer Run locally and Deploy to cloud using one project/deployment contract.
- Have the LLM monitor crawlers and provide evidence-based advice.
- Generate agentic crawlers whose execution schedules are dynamically controlled
  by an LLM; this is distinct from code generation and monitoring advice.
- Add a StatsD-like emitter/collector path and time-series database for dashboard
  metrics, streaming logs, failed-response diagnosis, and data sanity checks.
- Preserve portable code/providers and make all user data downloadable at any time.

The dashboard currently polls logs and shows stored run summaries. It does not
yet implement the full metrics store, streaming, monitoring advice, or cloud export.
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

Docker Compose also starts one service:

```bash
cd ..
docker compose -f ui/compose.yaml up --build
```

The Compose command above runs from the repository root after the preceding
commands in `ui/`. This image packages the control plane. A separate Docker image
for the isolated agent environment is required by the cloud plan and is not yet
provided by this deployment.
