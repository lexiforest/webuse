import type { NitroApp } from "nitropack/types";
import { ensureOrchestrator, stopOrchestrator } from "../../src/lib/server/orchestrator";
import { stopAssistants } from "../../src/lib/server/assistant";

export default function orchestratorPlugin(nitro: NitroApp) {
  ensureOrchestrator();
  nitro.hooks.hook("close", () => { stopAssistants(); stopOrchestrator(); });
}
