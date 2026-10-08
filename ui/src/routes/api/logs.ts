import type { APIEvent } from "@solidjs/start/server";
import { json, queryInt } from "~/lib/server/http";
import { ensureOrchestrator } from "~/lib/server/orchestrator";
import { store } from "~/lib/server/store";
export function GET(event: APIEvent) {
  ensureOrchestrator(); const url = new URL(event.request.url); const runId = queryInt(event, "run_id");
  const limit = Number(url.searchParams.get("limit") || 100); const offset = Number(url.searchParams.get("offset") || 0);
  return json({ logs: store.listLogs(runId, limit, offset), total: store.countLogs(runId) });
}
