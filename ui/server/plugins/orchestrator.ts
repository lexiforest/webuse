import type { NitroApp } from "nitropack/types";
import { ensureOrchestrator, stopOrchestrator } from "../../src/lib/server/orchestrator";
import { stopAssistants } from "../../src/lib/server/assistant";

export default function orchestratorPlugin(nitro: NitroApp) {
  ensureOrchestrator();
  const stop = (signal: NodeJS.Signals) => { stopAssistants(); void stopOrchestrator(signal); };
  const interrupt = () => stop("SIGINT");
  const terminate = () => stop("SIGTERM");
  process.on("SIGINT", interrupt);
  process.on("SIGTERM", terminate);
  nitro.hooks.hook("close", async () => {
    stopAssistants();
    await stopOrchestrator();
    process.off("SIGINT", interrupt);
    process.off("SIGTERM", terminate);
  });
}
