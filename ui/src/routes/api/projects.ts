import type { APIEvent } from "@solidjs/start/server";
import { body, json, projectInput, queryInt } from "~/lib/server/http";
import { ensureOrchestrator } from "~/lib/server/orchestrator";
import { store } from "~/lib/server/store";

export function GET(event: APIEvent) {
  ensureOrchestrator(); const id = queryInt(event, "id");
  if (!id) return json({ projects: store.listProjects() });
  const project = store.getProject(id); return project ? json({ project }) : json({ error: "Project not found." }, 404);
}
export async function POST(event: APIEvent) {
  ensureOrchestrator();
  if (!event.request.headers.get("content-type")?.includes("application/json")) return json({ project: store.createProject() }, 201);
  const result = projectInput(await body(event)); return result.input ? json({ project: store.createProject(result.input) }, 201) : json({ error: result.error }, 400);
}
export async function PUT(event: APIEvent) {
  ensureOrchestrator(); const id = queryInt(event, "id");
  if (!id) return json({ error: "A valid project id is required." }, 400);
  const result = projectInput(await body(event)); if (!result.input) return json({ error: result.error }, 400);
  const project = store.updateProject(id, result.input); return project ? json({ project }) : json({ error: "Project not found." }, 404);
}
export function DELETE(event: APIEvent) {
  ensureOrchestrator(); const id = queryInt(event, "id"); if (!id) return json({ error: "A valid project id is required." }, 400);
  try { store.deleteProject(id); return json({ ok: true }); } catch (error) { return json({ error: error instanceof Error ? error.message : String(error) }, 409); }
}
