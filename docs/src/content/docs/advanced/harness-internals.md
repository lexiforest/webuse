---
title: "Harness Internals"
description: "Source development and runtime configuration for the local UI and control plane."
---

This page covers development of the local UI and control plane. See
[Harness](../../user-guide/harness/) and [Dashboard](../../user-guide/dashboard/)
for the user workflows.

Pi's coding-agent SDK owns the agent loop, streaming, session context, retries,
and compaction. Webuse owns the UI, project tools, and orchestration.

## Model Context

`model-limits.ts` holds the reviewed model catalog, resolution precedence, and
Pi budgets. `webuse.model_metadata` probes serving limits through curl_cffi without
loading models or generating tokens. Credentials stay in subprocess stdin and
same-endpoint request headers; they are excluded from public status. Discovery
is cached briefly by configuration and interpreter.

The selected context capacity is passed to Pi without a universal 32K cap.
Automatic compaction reserves the response budget, Pi's 4,096-token safety
margin, and an additional allowance for tool output. The retained tail is at
most 20,000 tokens and one quarter of the remaining context. Summary requests
are at most 8,192 tokens and one sixteenth of the context. These are application
budgets, distinct from the model's documented output ceiling.

A small stream adapter sets those request budgets and rejects exhausted context
before Pi can clamp a request to one output token. Pi continues to own summary
generation, session projection, and compact-and-retry recovery. Webuse observes
the final assistant event and compaction errors even when Pi omits a failed
attempt from the projected history. This prevents early progress text or an empty
reply from being recorded as a completed answer.

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
needed. By default, when an execution is claimed, Node executes:

```bash
python -m webuse.cli crawl PROJECT -o RUN/items.jsonl
```

The default Python executable is discovered from the repository virtual
environment. Set `WEBUSE_PYTHON_COMMAND` to override it. Set
`WEBUSE_DB_PATH`, `WEBUSE_WORK_DIR`, and `WEBUSE_CONCURRENCY` to configure
the control plane. Five-field cron schedules are evaluated in UTC.

This is fixed scheduling. LLM-controlled agentic scheduling is planned and has
no current UI configuration or command to enable it.

## Framework and Documentation Discovery

Harness uses the configured crawler Python interpreter for framework discovery
in both `npm run dev` and `webuse serve`. `workspace_info.framework` reports its
Webuse version, interpreter, source directory, documentation root, page index,
and framework capabilities. Inspect the same information outside Harness with:

```bash
python -m webuse.resources
```

Editable installs resolve live Markdown from `docs/src/content/docs` relative to
the imported Python package, independently of the process working directory.
Wheels include those same pages under `webuse/_docs`. An installed package never
substitutes docs from a nearby checkout. Missing documentation is reported explicitly.
Discovery does not contact model providers or expose credentials.

The skill directs the agent to relevant docs first. Targeted framework source
reads are allowed for unanswered questions and debugging; framework resources
are read-only to the Harness, while project edits remain in its workspace.
These are agent instructions, not a filesystem sandbox.
New Harness workspaces start with an empty spider registry. The agent uses
`webuse gen` to create the documented Python/YAML spider layout instead of
defaulting to inline rules in the project configuration.

For installed-package parity, install a built wheel in a separate environment
and set `WEBUSE_PYTHON_COMMAND=/path/to/that/environment/bin/python` before
`npm run dev`. The development UI then uses that wheel's docs and framework.
The release smoke script supports this mode as well; see
[Verifying Release Artifacts](../package-release/#verifying-release-artifacts).

## Process Management

For a persistent local setup, install PM2 and run these commands from `ui/`
after completing the source setup:

```bash
npm run build
pm2 start ecosystem.config.cjs
```

The configuration starts `.output/server/index.mjs` with Node on loopback port
2951, uses `../.venv/bin/python` for crawlers, and allows ten seconds for shutdown.
PM2 manages the Node service; the orchestrator manages individual crawler executions.
On SIGINT or SIGTERM, the orchestrator stops scheduling, signals worker process
groups, and waits for cleanup. Remaining workers and descendants receive SIGKILL
after 1.5 seconds. Docker Compose uses an init process to reap orphaned children.

Released packages use `webuse serve` to launch the bundled server with the
launcher's Python interpreter. Runtime data defaults to `~/.webuse`, outside
the installed package. See [Deployment](../../user-guide/deployment/) for Docker
and Compose setup.

## Source Map

Paths below are relative to `ui/`.

| File | Responsibility |
| --- | --- |
| `src/lib/server/assistant.ts` | Pi sessions, configured model access, prompt, cancellation, and streamed events. |
| `src/lib/server/assistant-turns.ts` | Server-owned turn lifetime, reconnect progress, and detachable HTTP observers. |
| `src/lib/server/assistant-tools.ts` | Workspace discovery, HTTP inspection, Python checks, sample crawls, and execution inspection. |
| `src/lib/server/workspace.ts` | Working files, editor revisions, and workspace locking. |
| `src/lib/server/orchestrator.ts` | Job queue, fixed schedules, and Python crawler subprocesses. |
| `skills/webuse-crawlers/SKILL.md` | Stable crawler workflows supplied to the agent. |

## Context and Execution

An accepted Harness turn runs independently of its HTTP connection. Disconnecting
an observer removes its listener without cancelling Pi. The server keeps a progress
snapshot for `GET /api/assistant-project`; returning clients poll it while the turn
is active. **Stop** explicitly aborts the agent. A project retains its workspace
lock while the agent works, and a second turn for that project is rejected.

Final responses and completion outcomes are saved in SQLite, even with no connected
observer. A root UI provider polls `/api/assistant-completions` using a message-ID
cursor, shows in-app notices, and optionally sends browser notifications. Initial
visits establish a cursor without announcing historical completions. Cursor state
survives reloads in the same tab. Active turns and progress snapshots live in the
Node process; this does not provide execution recovery after a server restart or
push delivery after all browser tabs close.

<figure>
  <a href="../../diagrams/harness-execution.png">
    <img src="../../diagrams/harness-execution.png" width="1536" height="1024" loading="lazy" decoding="async" alt="Harness edits working files, then queues an execution. The orchestrator launches a crawler that reads those files, writes JSONL records during execution, and sends logs. The orchestrator imports records incrementally for the UI." />
  </a>
  <figcaption>Records are collected during execution and retained after success, failure, or cancellation. Stored logs can be viewed while the execution is active.</figcaption>
</figure>

The prompt identifies the project and directs the agent to the bundled skill.
The skill explains workflows; `workspace_info` reports current capabilities and
limits; runtime configuration supplies model endpoints and credentials. Keep
credentials out of skill text and generated source. Ambient Pi extensions,
skills, and credentials are not loaded.

Pi's native file and shell tools operate in the persistent project directory.
Harness edits persist immediately. Manual, scheduled, and sample executions use the
current workspace directly, without source snapshots. Users manage history with
Git. SQLite stores metadata and Pi session entries; source files stay on disk.

The default runner invokes `webuse crawl PROJECT_DIRECTORY`, the same entry point
used from a terminal. The root `webuse.yaml` registers the spiders to run;
sample jobs add a shared `--max-requests` budget. Create a project with
`webuse create DIRECTORY`, then add registered spiders with `webuse gen`.

Keep additions to the Pi integration small. New Webuse tools should operate on
the same project/execution model used by Code and Dashboard. Local shell and Python
tools run with the UI user's access; their time limits are not tenant isolation.



Project Settings can override the crawl command. Custom commands execute in the
workspace and receive `WEBUSE_OUTPUT_PATH` for JSONL output and
`WEBUSE_MAX_REQUESTS` for sample budgets. They must enforce the request budget;
the orchestrator enforces the sample deadline.
