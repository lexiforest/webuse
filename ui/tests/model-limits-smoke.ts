import assert from "node:assert/strict";
import { contextBudgets, modelCatalog, resolveModelLimits } from "../src/lib/server/model-limits";
import { normalizedSettings } from "../src/lib/server/settings";
import { runAssistant } from "../src/lib/server/assistant";
import { store } from "../src/lib/server/store";

const selected = { model: "deepseek-flash", baseUrl: "https://api.deepseek.com/v1" };
const known = resolveModelLimits(selected);
assert.equal(known.contextWindow, 1_000_000);
assert.equal(known.maxOutputTokens, 384_000);
assert.equal(known.contextSource, "catalog");
assert.equal(resolveModelLimits({ ...selected, model: "deepseek-flash-custom" }).contextWindow, undefined);
assert.equal(resolveModelLimits({ ...selected, baseUrl: "http://localhost:1234/v1" }).contextWindow, undefined);
const live = { contextWindow: 32768, maxOutputTokens: 4096, source: "endpoint" };
assert.equal(resolveModelLimits(selected, live).contextWindow, 32768);
assert.equal(resolveModelLimits({ ...selected, contextWindow: "65536" }, live).contextWindow, 65536);
assert.equal(resolveModelLimits({ ...selected, maxOutputTokens: "2048" }, live).maxOutputTokens, 2048);
for (const value of [0, -1, true, "oops", 1.5, Infinity]) assert.throws(() => normalizedSettings({ llm: { contextWindow: value } }), /positive integer/);
assert.throws(() => contextBudgets(resolveModelLimits({ ...selected, model: "unknown" })), /unknown.*Settings/);
assert.throws(() => contextBudgets(resolveModelLimits(selected, { contextWindow: 4096 })), /too small/);
for (const contextWindow of [16384, 32768, 131072, 1_000_000]) {
  const budget = contextBudgets(resolveModelLimits({ ...selected, contextWindow: String(contextWindow) }));
  assert.ok(budget.compaction.keepRecentTokens + 2 * budget.summaryTokens + budget.responseTokens + 4096 < contextWindow);
}
assert.equal(new Set(modelCatalog.flatMap(entry => entry.ids)).size, modelCatalog.flatMap(entry => entry.ids).length);

const originalSettings = store.getSettings();
const originalFetch = globalThis.fetch;
const originalPython = process.env.WEBUSE_PYTHON_COMMAND;
let mode: "recover" | "threshold" | "failed-summary" | "empty" | "exhausted" = "recover";
let calls = 0;
let summaries = 0;
const stream = (delta: unknown, finish: string, usage?: object) => {
  const chunk = (delta: unknown, finish_reason: string | null, usage?: object) => `data: ${JSON.stringify({ id: "limits", choices: [{ index: 0, delta, finish_reason }], usage })}\n\n`;
  return new Response(chunk({ role: "assistant", ...delta as object }, null) + chunk({}, finish, usage) + "data: [DONE]\n\n", { headers: { "content-type": "text/event-stream" } });
};
const project = () => {
  const p = store.createProject({ name: "Context regression", target: "https://example.com", files: [{ path: "crawler.py", content: "# crawler documentation\n".repeat(1100) }] });
  return { projectId: p.id, sessionId: store.getOrCreateSession(p.id)!.id, message: "Inspect the crawler" };
};
try {
  process.env.WEBUSE_PYTHON_COMMAND = process.platform === "win32" ? "where" : "/usr/bin/false";
  store.saveSettings({ llm: { model: "limits-test", baseUrl: "http://limits.invalid/v1", contextWindow: "32768", maxOutputTokens: "8192" } });
  globalThis.fetch = async (_input, init) => {
    const request = JSON.parse(String(init?.body));
    assert.ok(request.max_tokens >= 1024, "Never send a one-token response budget");
    if (!request.tools?.length) {
      summaries++;
      assert.ok(request.max_tokens <= 2048, "Summary budget scales to a 32K context");
      return stream({ content: "The crawler was inspected. Finish the response." }, mode === "failed-summary" ? "length" : "stop");
    }
    calls++;
    if (mode === "exhausted") assert.fail("An oversized prompt must not reach the endpoint");
    if (mode === "empty") return stream({ reasoning_content: "Thinking only" }, "stop");
    if (calls === 1) return stream({ content: "I'll inspect it.", tool_calls: [{ index: 0, id: "read-context", type: "function", function: { name: "read", arguments: JSON.stringify({ path: "crawler.py" }) } }] }, "tool_calls", mode === "threshold" ? { prompt_tokens: 18000, completion_tokens: 80, total_tokens: 18080 } : undefined);
    if (calls === 2 && mode !== "threshold") return stream({ reasoning_content: "S" }, "length", { prompt_tokens: 12000, completion_tokens: 1, total_tokens: 12001 });
    return stream({ content: "Inspection finished successfully." }, "stop");
  };
  const recovery = project();
  const result = await runAssistant(recovery);
  assert.equal(result.error, undefined, result.content);
  assert.match(result.content, /Inspection finished successfully/);
  assert.ok(summaries > 0, "Pi must compact and retry a truncated response");
  assert.ok(store.getAssistantState(recovery.sessionId).some((entry: any) => entry.type === "compaction"));

  mode = "threshold"; calls = 0; summaries = 0;
  const threshold = await runAssistant(project());
  assert.equal(threshold.error, undefined, threshold.content);
  assert.ok(summaries > 0, "Pi must compact proactively between tool batches");
  assert.equal(calls, 2, "Threshold compaction must continue the same turn");

  mode = "failed-summary"; calls = 0; summaries = 0;
  const failed = await runAssistant(project());
  assert.ok(failed.error, failed.content);
  assert.match(failed.content, /Assistant error:/);
  assert.doesNotMatch(failed.content, /No response received from the model/);
  assert.ok(summaries > 0);

  mode = "empty"; calls = 0;
  const empty = await runAssistant(project());
  assert.match(empty.error || "", /without a final text response/);

  mode = "exhausted"; calls = 0;
  const exhausted = await runAssistant({ ...project(), message: "huge prompt ".repeat(20000) });
  assert.ok(exhausted.error, exhausted.content);
  assert.equal(calls, 0);
  store.saveSettings({ llm: { model: "unknown", baseUrl: "http://limits.invalid/v1" } });
  const unknown = await runAssistant(project());
  assert.match(unknown.error || "", /context window is unknown/);
  assert.equal(calls, 0);
} finally {
  globalThis.fetch = originalFetch;
  process.env.WEBUSE_PYTHON_COMMAND = originalPython;
  store.saveSettings(originalSettings);
}
console.log("Model limits passed: precedence, unknown models, budgets, Pi compaction recovery, failed summaries, empty replies, and exhausted contexts.");
