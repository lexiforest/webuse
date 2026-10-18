import type { APIEvent } from "@solidjs/start/server";
import { json, queryInt } from "~/lib/server/http";
import { ensureOrchestrator } from "~/lib/server/orchestrator";
import { store } from "~/lib/server/store";
export function GET(event: APIEvent) {
  ensureOrchestrator();
  const executionId = queryInt(event, "execution_id");
  if (new URL(event.request.url).searchParams.get("format") === "jsonl") {
    if (!executionId || !store.getJob(executionId)) return json({ error: "Execution not found." }, 404);
    const items = store.listDataItems(executionId);
    return new Response(items.map(row => JSON.stringify(row.item) + "\n").join(""), {
      headers: {
        "content-type": "application/x-ndjson; charset=utf-8",
        "content-disposition": `attachment; filename="execution-${executionId}.jsonl"`,
        "cache-control": "no-store",
      },
    });
  }
  return json({ dataItems: store.listDataItems(executionId) });
}
