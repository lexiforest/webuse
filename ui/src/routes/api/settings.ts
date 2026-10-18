import type { APIEvent } from "@solidjs/start/server";
import { body, json } from "~/lib/server/http";
import { ensureOrchestrator } from "~/lib/server/orchestrator";
import { normalizedSettings } from "~/lib/server/settings";
import { store } from "~/lib/server/store";
import { clearModelCache, settingsPayload } from "~/lib/server/models";
import { clearMonitoringCache } from "~/lib/server/monitoring";

async function settingsResponse() {
  try { return json(await settingsPayload()); }
  catch (error) { return json({ error: (error as Error).message }, 400); }
}
export async function GET() {
  ensureOrchestrator();
  return settingsResponse();
}
export async function PUT(event: APIEvent) {
  ensureOrchestrator(); const value = await body(event);
  if (!value?.settings || typeof value.settings !== "object") return json({ error: "Settings body is required." }, 400);
  let settings;
  try { settings = normalizedSettings(value.settings); }
  catch (error) { return json({ error: (error as Error).message }, 400); }
  settings.llm.baseUrl = settings.llm.baseUrl.trim().replace(/\/$/, "");
  settings.llm.model = settings.llm.model.trim();
  if (settings.llm.baseUrl) {
    try {
      const url = new URL(settings.llm.baseUrl);
      if (!["http:", "https:"].includes(url.protocol) || url.username || url.password) throw new Error();
    } catch { return json({ error: "Model base URL must be an HTTP(S) URL without embedded credentials." }, 400); }
  }
  const concurrency = Number(settings.runtime.concurrency || 1);
  if (!Number.isInteger(concurrency) || concurrency < 1) return json({ error: "Concurrency must be a positive integer." }, 400);
  store.saveSettings(settings); clearModelCache(); clearMonitoringCache(); ensureOrchestrator(); return settingsResponse();
}
