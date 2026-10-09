import { definePlugin } from "nitro";
import { ensureOrchestrator, stopOrchestrator } from "../../src/lib/server/orchestrator";
import { stopAssistants } from "../../src/lib/server/assistant";

export default definePlugin(nitro => {
  ensureOrchestrator();
  nitro.hooks.hook("close", () => { stopAssistants(); stopOrchestrator(); });
});
