---
title: "Dashboard"
description: "Run a crawler, inspect its results, and set up a recurring schedule."
---

This tutorial takes you through running a saved crawler, checking its logs and
records, and scheduling its next runs. Start with a project you have created and
tested using the [Harness](../harness/).

## 1. Open Your Project

Start the local service:

```bash
webuse serve
```

The browser opens at `http://127.0.0.1:2951/`. If you need to install Webuse first,
follow [Run Locally](../harness/#run-locally).

Click **Projects** in the sidebar and find your crawler. If you have just changed
its code, click **Edit**, review the files, and click **Save files** before
running it. Manual and scheduled runs use the current files on disk.

> **Screenshot placeholder:** Projects page with a sample crawler and the
> **Run**, **Runs**, and **Edit** buttons highlighted.

## 2. Run the Crawler

On the **Projects** page, click **Run** beside your crawler. Webuse opens the
**Runs** page, where the new run appears. The list updates automatically.

Follow its **Status**:

| Status | What it means |
| --- | --- |
| `queued` | Waiting for an available run slot. |
| `running` | The crawler is executing. |
| `succeeded` | The crawl finished successfully and its records are available. |
| `failed` | The run failed; open its logs to investigate. |
| `cancelled` | The run was cancelled or interrupted. |

To stop a queued or running job, click **Cancel** on its row. To see only this
project's run history, return to **Projects** and click **Runs** beside it.

> **Screenshot placeholder:** Runs page showing a running job, its status, and
> the **Logs**, **Data**, and **Cancel** actions.

## 3. Check the Logs and Records

Click **Logs** on the run's row to read its output. For a failed run, look for an
error message that explains what went wrong. You can take that message back to
Harness and ask for help fixing the crawler.

> **Screenshot placeholder:** Logs view with the selected run and an example
> crawler message visible.

After the run succeeds, click **Data** on its row to inspect the extracted
records. Check a few records against the source website: are the expected fields
present, and do their values look correct? A successful run can still extract
incomplete or incorrect data.

> **Screenshot placeholder:** Data view showing a completed run and an extracted
> record with fields such as title, price, and URL.

If you need to change the crawler, return to **Projects**, click **Edit**, and
make the change in Harness or the file editor. Save editor changes, test a sample,
and run it again. Edits can affect queued or running jobs; use Git for code history.

Samples requested in Harness also appear in the dashboard and use the same working files.

## 4. Set a Schedule

Once the results look right, set up a recurring run:

1. Open **Projects** and click **Edit** beside the crawler.
2. Select the project's **Settings** tab.
3. Enter `0 * * * *` in **Cron schedule (UTC)** to run at the start of every hour.
4. Check the description below the field, then click **Save project**.
5. Return to **Projects** to confirm the **Schedule** column shows your schedule.

All schedule times use UTC. For example, `0 9 * * *` means every day at 09:00 UTC.
To remove the schedule, clear the field and click **Save project** again. This
stops future scheduled runs; use **Cancel** for jobs already queued or running.

> **Screenshot placeholder:** Project Settings tab with **Cron schedule (UTC)**
> set to `0 * * * *`, its readable description, and **Save project** visible.

## 5. Keep Scheduled Runs Active

Leave `webuse serve` running and keep the computer awake for scheduled crawls.
You can close the browser or Harness; the service continues running. Pressing
**Ctrl+C** in the service terminal stops it and interrupts active crawls.

Reopen the dashboard to check the latest runs, logs, and records. For deployment
on a machine that stays running, see [Deployment](../deployment/).
