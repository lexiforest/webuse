---
title: "Harness"
description: "Create, edit, and test crawlers with the built-in coding assistant."
---

The Webuse UI includes a coding-agent harness based on [Pi](https://pi.dev).
Use Harness and the file editor to create, inspect, and test crawler projects. The
[Dashboard](../dashboard/) manages their executions, logs, records, and schedules.

## Run Locally

Install and start the local service, which includes the harness, dashboard, and
crawler process management:

```sh
pip install webuse
webuse serve
```

or:

```sh
uv add webuse
uv run webuse serve
```

`webuse` requires Python 3.11+ and Node.js 22.19+.

The launcher opens `http://127.0.0.1:2951/`. Use
`--no-open` to skip the browser, `--port` or `--host` to change the listener,
and `--data-dir` to change the default `~/.webuse` data directory. The default
database is `~/.webuse/webuse.db`.
`WEBUSE_UI_DATA_DIR` also sets that default. Spiders use the launcher's Python
interpreter. `WEBUSE_PYTHON_COMMAND` can override it.

## Connect a Model

Click the model indicator to open **Settings**. LM Studio and Ollama are discovered
automatically when no provider is configured. Select a discovered model, or fill
in the **Model** fields:

- **Base URL**: your provider's OpenAI-compatible API endpoint.
- **Model**: the model name supplied by that provider.
- **API key**: your provider's key, if required.

Click **Save & Apply**. Choose a model and endpoint that support streaming and
tool calls so the assistant can inspect pages, edit files, and test your crawler.
Saved model settings in SQLite override framework configuration. Otherwise Harness
loads environment variables over the nearest `.webuserc.yaml`, over
`~/.config/webuse/config.yaml`. Lookup starts in the launch directory and walks
up through home, or the filesystem root when outside home. Only the nearest
file is loaded. With no configured model, discovery tries LM Studio,
then Ollama. Set `WEBUSE_CONFIG_DIR` to override the config lookup directory.
The indicator shows **Disconnected** if no model is available. Availability checks
list models without generating a response.

### Context and output limits

Harness resolves limits for the selected endpoint and model in this order:

1. Explicit **Context window** and **Maximum output tokens** in Model settings
   (or `llm.context_window` and `llm.max_output_tokens` in fallback configuration).
2. Serving metadata from the endpoint. Ollama and LM Studio report their loaded
   context allocation, which can be smaller than the model's trained maximum.
3. The embedded catalog of documented model limits, matched by exact model ID.

Settings shows each active limit and its source. Unknown context windows must be
configured before Harness can send a request. Unloaded local models need a loaded
allocation or an explicit override; their advertised native maximum is not used
as an allocation. Changing the endpoint or model in Settings clears manual limits.
Custom aliases do not inherit limits through name-prefix matching.

For an endpoint that does not report limits, fallback configuration can include:

```yaml
llm:
  base_url: http://localhost:1234/v1
  model: my-local-model
  context_window: 65536
  max_output_tokens: 8192
```

Use the actual server allocation. SQLite model settings take precedence over this
file as a group. Blank limit fields select automatic detection.

The output ceiling is separate from context capacity. Normal response requests
default to at most 32,768 tokens (8,192 when the output ceiling is unknown), and
at most one quarter of the context window. An explicit output setting replaces
the default request ceiling, still bounded by that quarter-window allowance.
Settings shows the resulting response budget. This leaves space for instructions,
tools, and conversation history; it does not cap the model's context at 32K.

Pi compacts older conversation history automatically, retaining a recent tail
and a summary. Full session entries remain in SQLite. Summary and retention
budgets scale with context capacity. Pi can compact and retry once after context
overflow or premature truncation. Failed recovery, truncated output, and missing
final text are reported explicitly; completed file edits remain on disk.

The catalog records official source URLs and a review date in
`ui/src/lib/server/model-limits.ts`. It includes OpenAI, DeepSeek, Claude, Gemini,
and native Qwen metadata. A catalog entry describes limits, not endpoint support:
Harness still requires streaming OpenAI-compatible **Chat Completions tool calls**.
For example, a provider requiring Responses or Anthropic Messages needs a
compatible gateway. Gemini's separate input allowance is used conservatively as
Pi's combined context budget, reserving output inside that allowance.

## Describe Your Crawler

On the **What do you want to crawl?** screen, enter the website URL and the data
you want. Include which pages to follow and any limits. For example:

> Build a crawler for https://books.toscrape.com/. Extract each book's title,
> price, availability, and detail-page URL. Follow the next-page links, but stay
> on this site. Test it on two pages first.

Press **Enter** or click the arrow to send your first message. Webuse creates the
project, saves your message, and opens its Harness conversation at `/projects/<id>`.
The project ID identifies this conversation; no separate session URL is needed.
After the first completed turn, Harness summarizes the opening request into a
short project title. If naming fails, it keeps the provisional title, shows a
notice, and retries after the next completed turn. Manually chosen names are kept.
Expand **Projects** in the sidebar to reopen a conversation. Recent activity moves
it to the top of the list. **New** starts another conversation when you send a message.
Use the project's **Files**, **Visual**, and **Settings** tabs to inspect and
configure the same crawler. Continue in Harness to refine it:

> Also extract the UPC from each book's detail page.

The assistant's replies and tool activity appear as it works. Click **Stop** to
interrupt it. Changes already made to the files remain saved.

Harness continues working when you navigate away, reload, or close the browser
tab. Reopen the project to see its current response and tool activity. The Webuse
server must stay running; active turns do not resume automatically after a server
restart. Completed replies and file edits remain saved.

Webuse displays a completion notice with a link back to the project. Enable
**Settings → Harness notifications** to also receive browser notifications when
you are elsewhere. Your browser asks for permission when you click **Enable
notifications**. Keep at least one Webuse tab open to receive these notices;
delivery may be delayed when the browser suspends background tabs. If browser
notifications are blocked or unsupported, in-app notices still work.

Harness reads the documentation supplied with your Webuse installation before
looking up framework implementation details. It can also read relevant framework
source for debugging. New crawlers follow the Quick Start layout: project defaults
and registrations in `webuse.yaml`, with individual spider settings and code in
`spiders/`. Existing inline configurations remain supported.
Custom parsers and hooks use that same YAML/Python split. Harness should choose
Python-only configuration only when you explicitly request it, and should
preserve the organization of an existing project.

Turns have no tool-count or time limit by default. In the global **Settings →
Harness** section, optionally set a maximum number of tool calls or a turn time
limit in seconds. Blank or 0 means unlimited; changes apply to the next turn.
A configured limit lets the current tool finish before stopping and saves a
continuation note. Send **continue** to resume with a fresh budget. **Stop** still
cancels immediately, and individual tool timeouts remain in effect.

## Test and Refine

Ask the assistant to run a small sample before starting a full crawl:

> Run a sample crawl and show me the extracted records. Check whether any titles
> or prices are missing.

Review the sample's records and logs in the [Dashboard](../dashboard/). If the
results are wrong, describe a specific example in Harness:

> The price includes the currency symbol. Change it to a numeric value and test
> the same page again.

Sample, manual, and scheduled crawls all use your current working files.

## Review and Run

Open **Files** to inspect the generated code. You can edit it directly or ask
Harness to make changes.

| Action | When to use it |
| --- | --- |
| **Save files** | Save changes you made in the editor. Harness's file changes are saved automatically. |
| **Reload files** | Load changes made by an external editor into the UI. |
| **Save project** | Save the files and project settings, including the schedule. |

Once the sample results look right, save any editor changes, then use the
[Dashboard](../dashboard/#2-run-the-crawler) to run the crawler or set a schedule.
Use Git to track and restore your code. Webuse runs files directly; edits can
affect queued jobs and executions already in progress.
