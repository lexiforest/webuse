import { definePlugin } from "nitro";
import { ensureOrchestrator, stopOrchestrator } from "../../src/lib/server/orchestrator";

export default definePlugin(nitro => {
  ensureOrchestrator();
  nitro.hooks.hook("close", () => stopOrchestrator());
});
