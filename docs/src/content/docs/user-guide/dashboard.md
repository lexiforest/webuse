---
title: "Dashboard"
description: "Run a crawler, inspect its results, and set up a recurring schedule."
---

This tutorial takes you through running a saved crawler, checking its logs and
records, and scheduling its next executions. Start with a project you have created and
tested using the [Harness](../harness/).

## 1. Open Your Project

Start the local service:

```bash
webuse serve
```

The browser opens at `http://127.0.0.1:2951/`. If you need to install Webuse first,
follow [Run Locally](../harness/#run-locally).

Expand **Projects** in the sidebar and select **All projects** to find your crawler.
The individual sidebar entries reopen each project's Harness conversation. If you have just changed
its code, click **Edit**, review the files, and click **Save files** before
running it. Manual and scheduled executions use the current files on disk.

Projects have no Type setting: YAML and Python files can coexist in the same
workspace, and the crawl command determines how they run. **Create project**
offers YAML and Python starter files. Built-in Git import is currently hidden;
previously imported workspaces remain usable.

> **Screenshot placeholder:** Projects page with a sample crawler and the
> **Run**, **Executions**, and **Edit** buttons highlighted.

## 2. Run the Crawler

On the **Projects** page, click **Run** beside your crawler. Webuse opens the
**Executions** page, where the new execution appears. The list updates automatically.

Follow its **Status**:

| Status | What it means |
| --- | --- |
| `queued` | Waiting for an available execution slot. |
| `running` | The crawler is executing. |
| `succeeded` | The crawl finished successfully and its records are available. |
| `failed` | The execution failed; open its logs to investigate. |
| `cancelled` | The execution was cancelled or interrupted. |

To stop a queued or running job, click **Cancel** on its row. To see only this
project's execution history, return to **Projects** and click **Executions** beside it.

> **Screenshot placeholder:** Executions page showing a running job, its status, and
> the **Logs**, **Data**, and **Cancel** actions.

## 3. Check the Logs and Records

Click **Monitor** on an execution's row to open its monitoring dashboard. The header
always shows execution status, duration, trigger, and saved item count. Use **Panels**
to enable or disable built-in panels for this project, or **Restore defaults** to
reset the selection. Panel order is fixed.

The dashboard includes progress, throughput, HTTP health, extraction/pipeline outcomes,
data quality, and logs. Resources and insights are optional. Crawler LLM usage is
marked unavailable until that instrumentation exists; Harness usage is separate.

Use the shared time range and refresh controls, or drag a chart's time slider to
filter charts and logs. Data quality samples the first 100 saved items across the
execution. Blank charts explain when telemetry is missing rather than showing zeros.

Configure Prometheus in **Settings → Monitoring**. A saved URL overrides environment
and `.webuserc.yaml` defaults; clearing it restores fallback discovery. Logs and saved
records work without Prometheus. See [Monitoring Architecture](../../advanced/monitoring/)
for Compose setup, available metrics, and instrumentation limits.

Click **Logs** on the execution's row to read its output. For a failed execution, look for an
error message that explains what went wrong. You can take that message back to
Harness and ask for help fixing the crawler.

> **Screenshot placeholder:** Logs view with the selected execution and an example
> crawler message visible.

Click **Data** on the execution's row to inspect records as they are written. Partial
records remain available after failure or cancellation. **Export JSONL** downloads
the records collected so far. Check a few records against the source website: are the expected fields
present, and do their values look correct? A successful execution can still extract
incomplete or incorrect data.

> **Screenshot placeholder:** Data view showing a completed execution and an extracted
> record with fields such as title, price, and URL.

If you need to change the crawler, return to **Projects**, click **Edit**, and
make the change in Harness or the file editor. Save editor changes, test a sample,
and run it again. Edits can affect queued or running jobs; use Git for code history.

Samples requested in Harness also appear in the dashboard and use the same working files.

### Custom commands

In project **Settings**, set **Crawl command** to run existing Scrapy projects or
other code. Leave it empty for the default Webuse runner. For example, on POSIX:

```sh
scrapy crawl books -o "$WEBUSE_OUTPUT_PATH"
```

Commands run from the project workspace. Write JSONL to `WEBUSE_OUTPUT_PATH` for
dashboard records; dependencies must already be installed. Harness samples pass
`WEBUSE_MAX_REQUESTS`, which custom code must enforce, and have a 60-second deadline.

## 4. Set a Schedule

Once the results look right, set up a recurring execution:

1. Open **Projects** and click **Edit** beside the crawler.
2. Select the project's **Settings** tab.
3. Enter `0 * * * *` in **Cron schedule (UTC)** to run at the start of every hour.
4. Check the description below the field, then click **Save project**.
5. Return to **Projects** to confirm the **Schedule** column shows your schedule.

All schedule times use UTC. For example, `0 9 * * *` means every day at 09:00 UTC.
To remove the schedule, clear the field and click **Save project** again. This
stops future scheduled executions; use **Cancel** for jobs already queued or running.

> **Screenshot placeholder:** Project Settings tab with **Cron schedule (UTC)**
> set to `0 * * * *`, its readable description, and **Save project** visible.

## 5. Keep Scheduled Executions Active

Leave `webuse serve` running and keep the computer awake for scheduled crawls.
You can close the browser or Harness; the service continues running. Pressing
**Ctrl+C** in the service terminal stops it and interrupts active crawls.

Reopen the dashboard to check the latest executions, logs, and records. For deployment
on a machine that stays running, see [Deployment](../deployment/).
