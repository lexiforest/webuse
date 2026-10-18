import type { APIEvent } from "@solidjs/start/server";
import { body, json, queryInt } from "~/lib/server/http";
import { cancelExecution, ensureOrchestrator } from "~/lib/server/orchestrator";
import { store } from "~/lib/server/store";

export function GET(event: APIEvent) {
  ensureOrchestrator(); const id = queryInt(event, "id");
  if (id) { const execution = store.getJob(id); return execution ? json({ execution }) : json({ error: "Execution not found." }, 404); }
  return json({ executions: store.listJobs(queryInt(event, "project_id")) });
}
export async function POST(event: APIEvent) {
  ensureOrchestrator(); const value = await body(event); const projectId = Number(value?.projectId);
  if (!Number.isInteger(projectId) || projectId < 1) return json({ error: "A valid projectId is required." }, 400);
  try {
    const execution = store.createJob(projectId); if (!execution) return json({ error: "Project not found." }, 404);
    ensureOrchestrator(); return json({ execution }, 201);
  } catch (error) { return json({ error: error instanceof Error ? error.message : String(error) }, 409); }
}
export function DELETE(event: APIEvent) {
  ensureOrchestrator(); const id = queryInt(event, "id"); if (!id) return json({ error: "A valid execution id is required." }, 400);
  return cancelExecution(id) ? json({ ok: true }) : json({ error: "Execution is not queued or running." }, 409);
}
