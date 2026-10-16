---
title: "Harness"
description: "Create, edit, and test crawlers with the built-in coding assistant."
---

The Webuse UI includes a coding-agent harness based on [Pi](https://pi.dev).
Use Chat and the file editor to create, inspect, and test crawler projects. The
[Dashboard](../dashboard/) manages their runs, logs, records, and schedules.

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
and `--data-dir` to change the default `~/.webuse/ui` data directory.
`WEBUSE_UI_DATA_DIR` also sets that default. Spiders use the launcher's Python
interpreter. `WEBUSE_PYTHON_COMMAND` can override it.

## Connect a Model

Open **Settings** and fill in the **LLM** fields:

- **Base URL**: your provider's OpenAI-compatible API endpoint.
- **Model**: the model name supplied by that provider.
- **API key**: your provider's key, if required.

Click **Save & Apply**. Choose a model and endpoint that support streaming and
tool calls so the assistant can inspect pages, edit files, and test your crawler.
For a local model served by LM Studio or Ollama, enter its endpoint and model
here too; Chat does not discover local servers automatically.

## Describe Your Crawler

On the **What do you want to crawl?** screen, enter the website URL and the data
you want. Include which pages to follow and any limits. For example:

> Build a crawler for https://books.toscrape.com/. Extract each book's title,
> price, availability, and detail-page URL. Follow the next-page links, but stay
> on this site. Test it on two pages first.

Press **Enter** or click the arrow to create the project. Webuse opens the
project files and Chat with your request. Continue in Chat to refine the crawler:

> Also extract the UPC from each book's detail page.

The assistant's replies and tool activity appear as it works. Click **Stop** to
interrupt it. Changes already made to the files remain saved.

## Test and Refine

Ask the assistant to run a small sample before starting a full crawl:

> Run a sample crawl and show me the extracted records. Check whether any titles
> or prices are missing.

Review the sample's records and logs in the [Dashboard](../dashboard/). If the
results are wrong, describe a specific example in Chat:

> The price includes the currency symbol. Change it to a numeric value and test
> the same page again.

Sample, manual, and scheduled crawls all use your current working files.

## Review and Run

Inspect the generated files in the editor. You can edit them directly or ask
Chat to make changes.

| Action | When to use it |
| --- | --- |
| **Save files** | Save changes you made in the editor. Chat's file changes are saved automatically. |
| **Reload files** | Load changes made by an external editor into the UI. |
| **Save project** | Save the files and project settings, including the schedule. |

Once the sample results look right, save any editor changes, then use the
[Dashboard](../dashboard/#2-run-the-crawler) to run the crawler or set a schedule.
Use Git to track and restore your code. Webuse runs files directly; edits can
affect queued jobs and runs already in progress.
