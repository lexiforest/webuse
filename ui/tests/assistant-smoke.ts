import assert from "node:assert/strict";
import { assistantRunning, cancelAssistant, runAssistant, type AssistantEvent } from "../src/lib/server/assistant";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { createWebuseTools, skillPath } from "../src/lib/server/assistant-tools";
import { versionDirectory } from "../src/lib/server/workspace";
import { stopOrchestrator } from "../src/lib/server/orchestrator";
import { store } from "../src/lib/server/store";

const initial = [{ path: "crawler.py", content: "print('before')\n" }, { path: "keep.txt", content: "unchanged" }];
const project = store.createProject({ name: "Pi smoke", type: "python", target: "https://example.com", files: initial });
const session = store.getOrCreateSession(project.id)!;
store.saveSettings({ llm: { apiKey: "literal-test-key", baseUrl: "http://model.invalid/v1", model: "test-model" } });
const events: AssistantEvent[] = [];
const requests: Record<string, any>[] = [];
const originalFetch = globalThis.fetch;
let mode: "edit" | "resume" | "abort" | "failure" = "edit";
let turn = 0;
globalThis.fetch = async (input, init) => {
  assert.match(String(input), /^http:\/\/model.invalid\/v1\/chat\/completions$/);
  assert.equal(new Headers(init?.headers).get("authorization"), "Bearer literal-test-key");
  const request = JSON.parse(String(init?.body));
  requests.push(request);
  assert.equal(request.stream, true);
  assert.equal(request.model, "test-model");
  if (mode === "failure") return new Response(JSON.stringify({ error: { message: "Invalid test model" } }), { status: 400, headers: { "content-type": "application/json" } });
  if (mode === "abort") return new Promise((_resolve, reject) => {
    const stop = () => reject(new DOMException("Aborted", "AbortError"));
    init?.signal?.addEventListener("abort", stop, { once: true });
    if (init?.signal?.aborted) stop();
  });
  const tools = request.tools.map((tool: any) => tool.function.name);
  assert.ok(tools.includes("run_crawl"));
  for (const name of ["read", "write", "edit", "bash", "grep", "find", "ls"]) assert.ok(tools.includes(name), name);
  assert.ok(!tools.includes("read_file"));
  let delta: Record<string, unknown>;
  if (mode === "resume") {
    assert.ok(request.messages.some((message: any) => message.role === "tool"), "Pi must restore tool history");
    delta = { content: "I remember the verified edit." };
  } else if (turn++ === 0) {
    delta = { tool_calls: [{ index: 0, id: "read-1", type: "function", function: { name: "read", arguments: JSON.stringify({ path: "crawler.py" }) } }] };
  } else if (turn === 2) {
    assert.ok(request.messages.some((message: any) => message.role === "tool" && message.content.includes("before")));
    delta = { tool_calls: [{ index: 0, id: "edit-1", type: "function", function: { name: "edit", arguments: JSON.stringify({ path: "crawler.py", oldText: "before", newText: "after" }) } }] };
  } else if (turn === 3) {
    delta = { tool_calls: [{ index: 0, id: "shell-1", type: "function", function: { name: "bash", arguments: JSON.stringify({ command: "printf 'native shell' > generated.txt", timeout: 5 }) } }] };
  } else {
    delta = { content: "Updated the crawler draft." };
  }
  const chunk = (value: unknown) => `data: ${JSON.stringify(value)}\n\n`;
  return new Response(chunk({ id: "chat-test", object: "chat.completion.chunk", choices: [{ index: 0, delta: { role: "assistant", ...delta }, finish_reason: null }] }) + chunk({ id: "chat-test", object: "chat.completion.chunk", choices: [{ index: 0, delta: {}, finish_reason: delta.tool_calls ? "tool_calls" : "stop" }] }) + "data: [DONE]\n\n", { headers: { "content-type": "text/event-stream" } });
};

try {
  store.appendMessage(session.id, "user", "Edit the crawler.");
  const first = await runAssistant({ projectId: project.id, sessionId: session.id, message: "Edit the crawler.", onEvent: event => events.push(event) });
  assert.equal(first.error, undefined, first.content);
  assert.match(first.content, /Updated/);
  assert.equal(requests.length, 4);
  assert.deepEqual(first.changedFiles, ["crawler.py", "generated.txt"]);
  assert.equal(first.files.find(file => file.path === "crawler.py")?.content, "print('after')\n");
  assert.equal(readFileSync(join(project.workspacePath, "generated.txt"), "utf8"), "native shell");
  assert.equal(readFileSync(join(project.workspacePath, "crawler.py"), "utf8"), "print('after')\n");
  assert.equal(store.getProject(project.id)!.savedVersion, project.savedVersion, "Agent edits must not publish the project");
  assert.equal(readFileSync(join(versionDirectory(project.id, project.savedVersion!), "crawler.py"), "utf8"), "print('before')\n");
  assert.ok(events.some(event => event.type === "text"));
  assert.equal(events.filter(event => event.type === "tool").length, 6);
  assert.ok(store.getAssistantState(session.id).length > 3);
  mode = "resume";
  const resumed = await runAssistant({ projectId: project.id, sessionId: session.id, message: "What changed?" });
  assert.equal(resumed.error, undefined, resumed.content);
  assert.match(resumed.content, /remember/);
  assert.deepEqual(resumed.changedFiles, []);

  mode = "abort";
  const cancelled = runAssistant({ projectId: project.id, sessionId: session.id, message: "Wait." });
  assert.equal(assistantRunning(project.id), true);
  await assert.rejects(runAssistant({ projectId: project.id, sessionId: session.id, message: "Conflicting turn" }), /active assistant/);
  assert.throws(() => store.saveWorkspace(project.id, first.files, first.revision), /busy/);
  setTimeout(() => cancelAssistant(project.id), 30);
  const stopped = await cancelled;
  assert.equal(stopped.stopped, true);
  assert.equal(assistantRunning(project.id), false);
  mode = "failure";
  const failed = await runAssistant({ projectId: project.id, sessionId: session.id, message: "Fail." });
  assert.ok(failed.error, failed.content);
  assert.deepEqual(failed.files, first.files);

  assert.match(readFileSync(skillPath, "utf8"), /Webuse crawler development/);
  const tools = createWebuseTools(project.id, project.workspacePath);
  const invoke = (name: string, params: unknown, signal?: AbortSignal) => tools.find(tool => tool.name === name)!.execute("test", params as never, signal, undefined, {} as never);
  const other = store.createProject({ name: "Other", type: "yaml", target: "https://example.com", files: initial });
  const otherRun = store.createJob(other.id)!;
  await assert.rejects(invoke("inspect_run", { runId: otherRun.id }), /not found/);
  store.cancelQueuedJob(otherRun.id);
  const sample = await invoke("run_crawl", { maxRequests: 2 });
  const sampleValue = JSON.parse((sample.content[0] as { text: string }).text);
  assert.equal(sampleValue.status, "failed");
  assert.match(store.getJob(sampleValue.id)?.command ?? "", /--max-requests 2/);
  assert.equal(store.getProject(project.id)!.savedVersion, project.savedVersion);
  assert.notEqual(sampleValue.sourceVersion, project.savedVersion);
  const expired = store.createJob(project.id, { assistantSample: { maxRequests: 1, deadline: Date.now() - 1 } })!;
  const expiredTools = createWebuseTools(project.id, project.workspacePath);
  // Running another sample also wakes the queue containing the expired job.
  await expiredTools.find(tool => tool.name === "run_crawl")!.execute("expired", {}, undefined, undefined, {} as never);
  assert.equal(store.getJob(expired.id)?.status, "cancelled");
  const python = process.env.WEBUSE_PYTHON_COMMAND;
  process.env.WEBUSE_PYTHON_COMMAND = process.platform === "win32" ? "python" : "python3";
  try {
    const check = await invoke("run_python", { code: "from pathlib import Path; print(Path('keep.txt').read_text())" });
    const checked = JSON.parse((check.content[0] as { text: string }).text);
    assert.equal(checked.exitCode, 0, checked.output);
    assert.match(checked.output, /unchanged/);
    await invoke("run_python", { code: "from pathlib import Path; Path('fixture.txt').write_text('persistent')" });
    const persisted = await invoke("run_python", { code: "from pathlib import Path; print(Path('fixture.txt').read_text())" });
    assert.match((persisted.content[0] as { text: string }).text, /persistent/);
    await assert.rejects(invoke("run_python", { code: "raise ValueError('test failure')" }), /test failure/);
    const abort = new AbortController();
    const pending = invoke("run_python", { code: "import time; time.sleep(60)" }, abort.signal);
    setTimeout(() => abort.abort(), 50);
    await assert.rejects(pending, /stopped|failed/);
  } finally { process.env.WEBUSE_PYTHON_COMMAND = python; }
  console.log("Pi assistant passed: native file/shell tools, persistent Python files, version isolation, streaming, cancellation, errors, and workspace locks.");
} finally { globalThis.fetch = originalFetch; stopOrchestrator(); }
