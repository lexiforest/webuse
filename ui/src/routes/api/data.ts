import type { APIEvent } from "@solidjs/start/server";
import { json, queryInt } from "~/lib/server/http";
import { ensureOrchestrator } from "~/lib/server/orchestrator";
import { store } from "~/lib/server/store";
export function GET(event: APIEvent) { ensureOrchestrator(); return json({ dataItems: store.listDataItems(queryInt(event, "run_id")) }); }
