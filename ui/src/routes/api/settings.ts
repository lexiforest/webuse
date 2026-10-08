import type { APIEvent } from "@solidjs/start/server";
import { body, json } from "~/lib/server/http";
import { ensureOrchestrator } from "~/lib/server/orchestrator";
import { normalizedSettings, settingsPayload } from "~/lib/server/settings";
import { store } from "~/lib/server/store";

export function GET() { ensureOrchestrator(); return json(settingsPayload()); }
export async function PUT(event: APIEvent) {
  ensureOrchestrator(); const value = await body(event);
  if (!value?.settings || typeof value.settings !== "object") return json({ error: "Settings body is required." }, 400);
  const settings = normalizedSettings(value.settings);
  const concurrency = Number(settings.runtime.concurrency || 1);
  if (!Number.isInteger(concurrency) || concurrency < 1) return json({ error: "Concurrency must be a positive integer." }, 400);
  store.saveSettings(settings); ensureOrchestrator(); return json(settingsPayload());
}
