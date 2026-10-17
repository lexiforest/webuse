---
title: "Harness Internals"
description: "Source development and runtime configuration for the local UI and control plane."
---

This page covers development of the local UI and control plane. See
[Harness](../../user-guide/harness/) and [Dashboard](../../user-guide/dashboard/)
for the user workflows.

Pi's coding-agent SDK owns the agent loop, streaming, session context, retries,
and compaction. Webuse owns the UI, project tools, and orchestration.

## Source Development

Editable installs skip the frontend build. Start Vite for UI development:

```bash
uv sync --extra dev
cd ui
npm ci
npm run dev
```

Open the Vite URL printed by the dev server, by default
`http://127.0.0.1:2951/`. Only one long-running process is
needed. When a run is claimed, Node executes:

```bash
python -m webuse.cli crawl PROJECT -o RUN/items.jsonl
```

The default Python executable is discovered from the repository virtual
environment. Set `WEBUSE_PYTHON_COMMAND` to override it. Set
`WEBUSE_DB_PATH`, `WEBUSE_WORK_DIR`, and `WEBUSE_CONCURRENCY` to configure
the control plane. Five-field cron schedules are evaluated in UTC.

This is fixed scheduling. LLM-controlled agentic scheduling is planned and has
no current UI configuration or command to enable it.

## Process Management

For a persistent local setup, install PM2 and run these commands from `ui/`
after completing the source setup:

```bash
npm run build
pm2 start ecosystem.config.cjs
```

The configuration starts `.output/server/index.mjs` with Node on loopback port
2951, uses `../.venv/bin/python` for crawlers, and allows ten seconds for shutdown.
PM2 manages the Node service; the orchestrator manages individual crawler runs.
On SIGINT or SIGTERM, the orchestrator stops scheduling, signals worker process
groups, and waits for cleanup. Remaining workers and descendants receive SIGKILL
after 1.5 seconds. Docker Compose uses an init process to reap orphaned children.

Released packages use `webuse serve` to launch the bundled server with the
launcher's Python interpreter. Runtime data defaults to `~/.webuse/ui`, outside
the installed package. See [Deployment](../../user-guide/deployment/) for Docker
and Compose setup.

## Source Map

Paths below are relative to `ui/`.

| File | Responsibility |
| --- | --- |
| `src/lib/server/assistant.ts` | Pi sessions, configured model access, prompt, cancellation, and streamed events. |
| `src/lib/server/assistant-tools.ts` | Workspace discovery, HTTP inspection, Python checks, sample crawls, and run inspection. |
| `src/lib/server/workspace.ts` | Working files, editor revisions, and workspace locking. |
| `src/lib/server/orchestrator.ts` | Job queue, fixed schedules, and Python crawler subprocesses. |
| `skills/webuse-crawlers/SKILL.md` | Stable crawler workflows supplied to the agent. |

## Context and Execution

<figure>
  <a href="../../diagrams/harness-execution.png">
    <img src="../../diagrams/harness-execution.png" width="1536" height="1024" loading="lazy" decoding="async" alt="Harness edits working files, then queues a run. The orchestrator launches a crawler that reads those files, writes JSONL records during execution, and sends logs. After a successful exit, the orchestrator imports the records for the UI." />
  </a>
  <figcaption>Records are written during execution and imported into the UI after success. Stored logs can be viewed while the run is active.</figcaption>
</figure>

The prompt identifies the project and directs the agent to the bundled skill.
The skill explains workflows; `workspace_info` reports current capabilities and
limits; runtime configuration supplies model endpoints and credentials. Keep
credentials out of skill text and generated source. Ambient Pi extensions,
skills, and credentials are not loaded.

Pi's native file and shell tools operate in the persistent project directory.
Harness edits persist immediately. Manual, scheduled, and sample runs execute the
current workspace directly, without source snapshots. Users manage history with
Git. SQLite stores metadata and Pi session entries; source files stay on disk.

The orchestrator invokes `webuse crawl PROJECT_DIRECTORY`, the same entry point
used from a terminal. The root `webuse.yaml` registers the spiders to run;
sample jobs add a shared `--max-requests` budget. Create a project with
`webuse create DIRECTORY`, then add registered spiders with `webuse gen`.

Keep additions to the Pi integration small. New Webuse tools should operate on
the same project/run model used by Code and Dashboard. Local shell and Python
tools run with the UI user's access; their time limits are not tenant isolation.


