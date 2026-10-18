import type { APIEvent } from "@solidjs/start/server";
import { body, json, queryInt } from "~/lib/server/http";
import { store } from "~/lib/server/store";

export async function PUT(event: APIEvent) {
  const id = queryInt(event, "project_id");
  if (!id || !store.listProjects().some(project => project.id === id)) return json({ error: "Project not found." }, 404);
  try { return json({ enabledPanels: store.saveMonitoringPanels(id, (await body(event))?.enabledPanels) }); }
  catch (error) { return json({ error: (error as Error).message }, 400); }
}
