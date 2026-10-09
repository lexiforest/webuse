# webuse GUI

SolidStart control plane for webuse projects. Node owns the UI, SQLite database,
scheduler, run queue, and crawler subprocess lifecycle. Each run starts an
independent Python process using `python -m webuse.cli crawl`.

The home screen starts with a crawler prompt, then opens project files beside the
assistant. Runs, logs, records, schedules, and settings remain directly accessible
through the dashboard. This is the implemented local control plane, not yet the
isolated cloud agent runtime.

[HUMAN.md](../HUMAN.md) defines the product direction and must never be edited by
agents. See [PLAN.md](../PLAN.md) for the derived implementation plan.

Use Node.js 24 or newer. Node.js 26 is supported.

## Run the packaged UI

Released Python packages include the compiled server and browser assets:

```bash
uv add webuse
uv run webuse ui
```

The launcher requires Node.js 24+ on PATH, opens `http://127.0.0.1:2951/`, and
stops with Ctrl+C. npm is not required. Use `--no-open`, `--port`, `--host`, and
`--data-dir` as needed. The default bind address is `127.0.0.1`.

Data defaults to `~/.webuse/ui` (or `WEBUSE_UI_DATA_DIR`): `webuse-ui.sqlite`
stores projects/settings and `runs/` stores run files. `WEBUSE_DB_PATH` and
`WEBUSE_WORK_DIR` override these paths. Crawlers use the launcher's active Python
interpreter unless `WEBUSE_PYTHON_COMMAND` is set.

## Develop from source

Install the Python project and UI dependencies, then start one Node process:

```bash
uv sync --extra dev
cd ui
npm ci
npm run dev
```

Open the URL printed by Vite, by default `http://127.0.0.1:2951/`.
Development, preview, and production start default to port 2951. Override the
Vite port with `npm run dev -- --port 4000` or `npm run preview -- --port 4000`;
override the production port with `PORT=4000 npm run start`.

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

Configure the Chat model, endpoint, and credentials in Settings. Automatic LM
Studio/Ollama discovery exists in the Python helpers; integrating that discovery
into UI Chat is planned. Explicit settings should take precedence.

## Pi assistant

Chat embeds `@earendil-works/pi-coding-agent`, with no separate Pi process or
account. The configured OpenAI-compatible endpoint must support streaming and
tool calls. Pi manages the tool loop, context compaction, retries, and cancellation.
Session entries and tool history are stored in the UI's SQLite database; ambient
Pi configuration, extensions, and credentials are not loaded.

Webuse provides `workspace_info`, `read_file`, `write_file`, `edit_file`,
`delete_file`, `fetch_page`, `run_python`, `run_crawl`, and `inspect_run`.
The bundled [crawler skill](skills/webuse-crawlers/SKILL.md) is readable through
`read_file`. Page fetching uses Python/curl_cffi. Python checks run against
temporary draft snapshots; source changes must use the file tools to persist.
Sample crawls enter the normal queue, and their logs and records appear in the
dashboard. Neither edits nor samples change the saved project until the user
clicks Save. The editor is read-only during a turn to prevent conflicting edits.

The UI streams text/tool activity and offers Stop. A turn is limited to five
minutes and 30 tool calls; Python checks have a 30-second limit and bounded
output. Each turn can request three sample crawls, each limited to 10 requests
and 60 seconds including queue time. Chat accepts at most 100 text files, 256 KB
per file and 2 MB total. These limits bound routine local agent work; Python
executes with the UI user's access and is not sandboxed. Cloud isolation,
resource accounting, and managed crawling services remain separate work.

Run `npm test` for orchestration and mocked Pi tool-loop checks. The installed
wheel test in `scripts/smoke_ui.py` exercises Pi with a local mock model and real
HTTP/Python/crawl tools; no external model calls are needed.

## Python release packaging

Run `uv build` from the repository root with Node.js 24+ and npm installed. The
setuptools build runs `npm ci` and `npm run build` with the Node server preset,
then packages `.output/server` and `.output/public` under `webuse/_ui`. This
generated directory is ignored by Git. Editable Python installs skip this build;
use the development server above, or run `uv build` to populate the local bundle.

Both the wheel and source distribution carry the compiled UI. Building a wheel
from the published source distribution requires no Node/npm build tools. Node is
still required to run the UI. SQLite uses Node's built-in `node:sqlite`, so the
bundle has no platform-specific SQLite addon. No legacy UI database/settings
migration is provided.

## Local and cloud roadmap

- Accept existing Scrapy projects, external-agent code, and built-in Chat output;
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
it within configured limits, independently of an open Chat session. Local mode
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
