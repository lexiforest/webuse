import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import type { APIEvent } from "@solidjs/start/server";
import { runAssistant, cancelAssistant } from "../src/lib/server/assistant";
import { createWebuseTools } from "../src/lib/server/assistant-tools";
import { normalizedSettings } from "../src/lib/server/settings";
import { store } from "../src/lib/server/store";
import { stopOrchestrator } from "../src/lib/server/orchestrator";
import { PUT as saveSettings } from "../src/routes/api/settings";

const originalFetch = globalThis.fetch;
const originalSettings = store.getSettings();
const originalPython = process.env.WEBUSE_PYTHON_COMMAND;
let mode: "many" | "batch" | "slow" | "idle" | "resume" = "many";
let requests = 0;
const settings = (harness = {}) => ({ llm: { model: "budget-test", contextWindow: "131072", maxOutputTokens: "8192", baseUrl: "http://budget.invalid/v1", apiKey: "test" }, harness });
const project = () => {
  const value = store.createHarnessProject("Test assistant turn budgets");
  return { projectId: value.id, sessionId: store.getOrCreateSession(value.id)!.id, message: "Work on the crawler" };
};
const tool = (id: string, name: string, args: unknown, index = 0) => ({ index, id, type: "function", function: { name, arguments: JSON.stringify(args) } });
globalThis.fetch = async (input, init) => {
  assert.equal(String(input), "http://budget.invalid/v1/chat/completions");
  const request = JSON.parse(String(init?.body));
  let delta: Record<string, unknown> = { content: "Finished." };
  if (request.tools?.length) {
    requests++;
    if (mode === "idle") return new Promise((_resolve, reject) => {
      const stop = () => reject(new DOMException("Aborted", "AbortError"));
      init?.signal?.addEventListener("abort", stop, { once: true });
      if (init?.signal?.aborted) stop();
    });
    if (mode === "many" && requests <= 31) delta = { tool_calls: [tool(`info-${requests}`, "workspace_info", {})] };
    if (mode === "batch" && requests === 1) delta = { tool_calls: [
      tool("first", "run_python", { code: "from pathlib import Path; Path('first.txt').write_text('complete')" }),
      tool("second", "run_python", { code: "from pathlib import Path; Path('second.txt').write_text('unexpected')" }, 1),
    ] };
    if (mode === "slow" && requests === 1) delta = { tool_calls: [tool("slow", "run_python", { code: "import time; from pathlib import Path; time.sleep(1.3); Path('finished.txt').write_text('complete')" })] };
    if (mode === "resume") {
      assert.ok(request.messages.some((message: any) => message.role === "tool" && JSON.stringify(message.content).includes("exitCode")), "Completed tool result must survive a budget stop");
      assert.ok(JSON.stringify(request.messages).includes("fresh turn budget"), "Continuation note must reach the model");
    }
  }
  const chunk = (delta: unknown, finish_reason: string | null) => `data: ${JSON.stringify({ id: "budget", choices: [{ index: 0, delta, finish_reason }] })}\n\n`;
  return new Response(chunk({ role: "assistant", ...delta }, null) + chunk({}, delta.tool_calls ? "tool_calls" : "stop") + "data: [DONE]\n\n", { headers: { "content-type": "text/event-stream" } });
};

try {
  process.env.WEBUSE_PYTHON_COMMAND = process.platform === "win32" ? "python" : "python3";
  assert.deepEqual(normalizedSettings({}).harness, { maxToolCalls: "", turnTimeoutSeconds: "" });
  assert.deepEqual(normalizedSettings({ harness: { maxToolCalls: 0, turnTimeoutSeconds: "0" } }).harness, { maxToolCalls: "", turnTimeoutSeconds: "" });
  for (const harness of [{ maxToolCalls: -1 }, { maxToolCalls: 1.5 }, { maxToolCalls: true }, { turnTimeoutSeconds: "oops" }, { turnTimeoutSeconds: 2147484 }]) {
    const response = await saveSettings({ request: new Request("http://localhost/api/settings", { method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify({ settings: settings(harness) }) }) } as APIEvent);
    assert.equal(response.status, 400);
  }
  const saved = await saveSettings({ request: new Request("http://localhost/api/settings", { method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify({ settings: settings({ maxToolCalls: "2", turnTimeoutSeconds: "60" }) }) }) } as APIEvent);
  assert.equal(saved.status, 200);
  assert.deepEqual((await saved.json()).effectiveSettings.harness, { maxToolCalls: "2", turnTimeoutSeconds: "60" });

  store.saveSettings(settings());
  const unlimited = project();
  const many = await runAssistant(unlimited);
  assert.equal(many.error, undefined, many.content);
  assert.equal(many.stopped, false);
  assert.equal(many.toolResults.length, 31, "Default turns must exceed the former 30-tool limit");
  const info = createWebuseTools(unlimited.projectId, store.getProject(unlimited.projectId)!.workspacePath).find(tool => tool.name === "workspace_info")!;
  const discovery = await info.execute("info", {}, undefined, undefined, {} as never);
  assert.equal(JSON.parse((discovery.content[0] as { text: string }).text).limits.turnSeconds, null);

  store.saveSettings(settings({ maxToolCalls: 1 }));
  mode = "batch"; requests = 0;
  const bounded = project();
  const limited = await runAssistant(bounded);
  assert.equal(limited.error, undefined, limited.content);
  assert.equal(limited.stopped, true);
  assert.equal(limited.toolResults.length, 1, "Do not start another tool in the same model response");
  assert.equal(limited.toolResults[0].status, "succeeded");
  const directory = store.getProject(bounded.projectId)!.workspacePath;
  assert.equal(readFileSync(join(directory, "first.txt"), "utf8"), "complete");
  assert.equal(existsSync(join(directory, "second.txt")), false);
  assert.match(limited.content, /1-tool limit.*Last tool: run_python \(succeeded\).*continue/s);
  mode = "resume"; requests = 0;
  const continued = await runAssistant({ ...bounded, message: "continue" });
  assert.equal(continued.error, undefined, continued.content);
  assert.equal(continued.stopped, false);
  assert.match(continued.content, /Finished/);

  store.saveSettings(settings({ turnTimeoutSeconds: 1 }));
  mode = "slow"; requests = 0;
  const timed = project();
  const timedResult = await runAssistant(timed);
  assert.equal(timedResult.stopped, true);
  assert.equal(timedResult.toolResults[0].status, "succeeded", "Deadline must let the active tool finish");
  assert.equal(readFileSync(join(store.getProject(timed.projectId)!.workspacePath, "finished.txt"), "utf8"), "complete");
  assert.equal(requests, 1, "Do not request another model response after the deadline");
  assert.match(timedResult.content, /1-second turn limit/);

  mode = "idle"; requests = 0;
  const waiting = await runAssistant(project());
  assert.equal(waiting.stopped, true, "Time limit must cancel a model request when no tool is active");
  assert.match(waiting.content, /continue/);

  mode = "slow"; requests = 0;
  const cancelled = project();
  const pending = runAssistant({ ...cancelled, onEvent: event => {
    if (event.type === "status" && event.text.includes("Waiting for the current tool")) setTimeout(() => cancelAssistant(cancelled.projectId), 10);
  } });
  const stopped = await pending;
  assert.equal(stopped.stopped, true);
  assert.match(stopped.content, /Assistant stopped/);
  assert.equal(existsSync(join(store.getProject(cancelled.projectId)!.workspacePath, "finished.txt")), false, "Stop must cancel even while a configured deadline waits for a tool");
  console.log("Assistant budgets passed: unlimited defaults, settings validation, operation boundaries, deadline grace, saved continuation, and immediate Stop.");
} finally {
  globalThis.fetch = originalFetch;
  process.env.WEBUSE_PYTHON_COMMAND = originalPython;
  store.saveSettings(originalSettings);
  await stopOrchestrator();
}
