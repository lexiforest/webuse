import type { APIEvent } from "@solidjs/start/server";
import { json, queryInt } from "~/lib/server/http";
import { store } from "~/lib/server/store";
import { executionPanel, executionRange, monitoringConnection, testMonitoringConnection } from "~/lib/server/monitoring";
import { panels, type PanelId } from "~/lib/monitoring";

export async function GET(event: APIEvent) {
  try {
    const url = new URL(event.request.url);
    if (url.searchParams.get("connection") === "1") return json(await testMonitoringConnection(event.request.signal));
    const id = queryInt(event, "execution_id");
    if (!id) return json({ error: "A valid execution_id is required." }, 400);
    const execution = store.getJob(id);
    if (!execution) return json({ error: "Execution not found." }, 404);
    const panel = url.searchParams.get("panel");
    if (!panel) return json({ execution, enabledPanels: store.monitoringPanels(execution.projectId), connection: await monitoringConnection() });
    if (!panels.some(item => item.id === panel)) return json({ error: "Unknown panel." }, 400);
    if (!store.monitoringPanels(execution.projectId).includes(panel as PanelId)) return json({ error: "Panel is disabled for this project." }, 409);
    const range = executionRange(execution, url.searchParams.has("start") ? Number(url.searchParams.get("start")) : undefined, url.searchParams.has("end") ? Number(url.searchParams.get("end")) : undefined, Number(url.searchParams.get("points") || 600));
    return json(await executionPanel(execution, panel as PanelId, range, event.request.signal));
  } catch (error) { return json({ error: (error as Error).message }, 400); }
}
