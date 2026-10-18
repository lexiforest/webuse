import assert from "node:assert/strict";
import { assistantRunning, cancelAssistant, runAssistant, toolPreview, type AssistantEvent } from "../src/lib/server/assistant";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { createWebuseTools, skillPath } from "../src/lib/server/assistant-tools";
import { stopOrchestrator } from "../src/lib/server/orchestrator";
import { store } from "../src/lib/server/store";
import { sqlite } from "../src/lib/server/db";
import { POST as createProject } from "../src/routes/api/projects";
import { GET as getConversation, POST as sendMessage, DELETE as stopConversation } from "../src/routes/api/assistant-project";
import { GET as getCompletions } from "../src/routes/api/assistant-completions";
import { runtime } from "../src/lib/server/runtime";
import type { APIEvent } from "@solidjs/start/server";

const initial = [{ path: "crawler.py", content: "print('before')\n" }, { path: "keep.txt", content: "unchanged" }];
const project = store.createProject({ name: "Pi smoke", target: "https://example.com", files: initial });
const session = store.getOrCreateSession(project.id)!;
store.saveSettings({ llm: { apiKey: "literal-test-key", baseUrl: "http://model.invalid/v1", model: "test-model", contextWindow: "131072", maxOutputTokens: "8192" } });
const events: AssistantEvent[] = [];
const requests: Record<string, any>[] = [];
const originalFetch = globalThis.fetch;
let mode: "edit" | "resume" | "abort" | "failure" | "chat" | "background" = "edit";
let finishBackground: (() => void) | undefined;
let turn = 0;
let titleRequests = 0;
let failTitle = false;
let truncateTitle = false;
let lastTitlePrompt = "";
globalThis.fetch = async (input, init) => {
  assert.match(String(input), /^http:\/\/model.invalid\/v1\/chat\/completions$/);
  assert.equal(new Headers(init?.headers).get("authorization"), "Bearer literal-test-key");
  const request = JSON.parse(String(init?.body));
  if (request.tools?.length) requests.push(request);
  assert.equal(request.stream, true);
  assert.equal(request.model, "test-model");
  if (mode === "failure") return new Response(JSON.stringify({ error: { message: "Invalid test model" } }), { status: 400, headers: { "content-type": "application/json" } });
  if (mode === "abort") return new Promise((_resolve, reject) => {
    const stop = () => reject(new DOMException("Aborted", "AbortError"));
    init?.signal?.addEventListener("abort", stop, { once: true });
    if (init?.signal?.aborted) stop();
  });
  if (mode === "background" && request.tools?.length) {
    const chunk = (delta: unknown, finish_reason: string | null) => new TextEncoder().encode(`data: ${JSON.stringify({ id: "background", choices: [{ index: 0, delta, finish_reason }] })}\n\n`);
    return new Response(new ReadableStream({ start(output) {
      output.enqueue(chunk({ role: "assistant", content: "Working in the background." }, null));
      finishBackground = () => {
        output.enqueue(chunk({ content: " Finished." }, null));
        output.enqueue(chunk({}, "stop"));
        output.enqueue(new TextEncoder().encode("data: [DONE]\n\n"));
        output.close();
      };
    } }), { headers: { "content-type": "text/event-stream" } });
  }
  if (!request.tools?.length) {
    titleRequests++;
    assert.equal(request.max_tokens, 2048);
    const titleContent = request.messages.at(-1).content;
    lastTitlePrompt = JSON.parse(Array.isArray(titleContent) ? titleContent.map((part: any) => part.text || "").join("") : titleContent).request;
    assert.equal(request.messages.length, 2, "Title request must not contain tool history");
    if (failTitle) return new Response(JSON.stringify({ error: { message: "Title unavailable" } }), { status: 400 });
    const titleChunk = (delta: unknown, finish_reason: string | null) => `data: ${JSON.stringify({ id: "title", choices: [{ index: 0, delta, finish_reason }] })}\n\n`;
    const reasoning = titleChunk({ role: "assistant", reasoning_content: "Consider the crawler's purpose. ".repeat(80) }, null);
    return new Response(reasoning + (truncateTitle ? "" : titleChunk({ content: '"Book Price Crawler"' }, null)) + titleChunk({}, truncateTitle ? "length" : "stop") + "data: [DONE]\n\n", { headers: { "content-type": "text/event-stream" } });
  }
  const tools = request.tools.map((tool: any) => tool.function.name);
  assert.ok(tools.includes("run_crawl"));
  for (const name of ["read", "write", "edit", "bash", "grep", "find", "ls"]) assert.ok(tools.includes(name), name);
  assert.ok(!tools.includes("read_file"));
  let delta: Record<string, unknown>;
  if (mode === "chat") {
    delta = { content: "Let's build this crawler." };
  } else if (mode === "resume") {
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
  assert.equal(titleRequests, 1);
  assert.equal(store.getProject(project.id)?.name, "Book Price Crawler");
  assert.equal(store.getOrCreateSession(project.id)?.title, "Book Price Crawler");
  assert.deepEqual(first.toolResults.map(tool => tool.preview), ["crawler.py", "crawler.py", "printf 'native shell' > generated.txt"]);
  assert.ok(events.filter(event => event.type === "tool").every(event => event.type === "tool" && event.tool.preview));
  assert.equal(toolPreview("workspace_info", {}), "workspace_info()");
  assert.equal(toolPreview("bash", { command: "x".repeat(200) }), "x".repeat(160) + "…");
  assert.equal(toolPreview("run_python", { code: "print(1)\nprint(2)" }), "print(1) print(2)");
  assert.deepEqual(first.changedFiles, ["crawler.py", "generated.txt"]);
  assert.equal(first.files.find(file => file.path === "crawler.py")?.content, "print('after')\n");
  assert.equal(readFileSync(join(project.workspacePath, "generated.txt"), "utf8"), "native shell");
  assert.equal(readFileSync(join(project.workspacePath, "crawler.py"), "utf8"), "print('after')\n");
  assert.ok(events.some(event => event.type === "text"));
  assert.equal(events.filter(event => event.type === "tool").length, 6);
  assert.ok(store.getAssistantState(session.id).length > 3);
  mode = "resume";
  const resumed = await runAssistant({ projectId: project.id, sessionId: session.id, message: "What changed?" });
  assert.equal(resumed.error, undefined, resumed.content);
  assert.match(resumed.content, /remember/);
  assert.equal(titleRequests, 1, "Follow-ups must keep the first title");
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
  const discovery = await invoke("workspace_info", {});
  const discoveryValue = JSON.parse((discovery.content[0] as { text: string }).text);
  assert.match(discoveryValue.framework.error, /configured Webuse installation/);
  assert.equal(discoveryValue.directory, project.workspacePath, "Workspace remains discoverable when the configured Python fails");
  const other = store.createProject({ name: "Other", target: "https://example.com", files: initial });
  const otherExecution = store.createJob(other.id)!;
  await assert.rejects(invoke("inspect_execution", { executionId: otherExecution.id }), /not found/);
  store.cancelQueuedJob(otherExecution.id);
  const sample = await invoke("run_crawl", { maxRequests: 2 });
  const sampleValue = JSON.parse((sample.content[0] as { text: string }).text);
  assert.equal(sampleValue.status, "failed");
  assert.match(store.getJob(sampleValue.id)?.command ?? "", /--max-requests 2/);
  assert.equal(sampleValue.workspacePath, project.workspacePath);
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
  mode = "chat";
  const event = (path: string, value?: unknown) => ({ request: new Request(`http://localhost/api/${path}`, value === undefined ? {} : {
    method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(value),
  }) }) as APIEvent;
  const beforeCreate = store.listProjects().length;
  assert.equal((await createProject({ request: new Request("http://localhost/api/projects", { method: "POST" }) } as APIEvent)).status, 400);
  assert.equal((await createProject(event("projects", { prompt: "  " }))).status, 400);
  assert.equal((await createProject(event("projects", { prompt: "x".repeat(32_001) }))).status, 400);
  assert.equal(store.listProjects().length, beforeCreate);
  const prompt = "Collect book prices from https://example.com/books.\nFollow the next page.";
  const created = await createProject(event("projects", { prompt }));
  assert.equal(created.status, 201);
  const conversationProject = (await created.json()).project;
  assert.equal(conversationProject.name, "Collect book prices from");
  assert.equal(conversationProject.target, "https://example.com/books");
  assert.match(conversationProject.files.find((file: { path: string }) => file.path === "webuse.yaml").content, /spiders: \{\}/);
  const historyPath = `assistant-project?project_id=${conversationProject.id}`;
  const history = await getConversation(event(historyPath)).json();
  assert.equal(history.session.projectId, conversationProject.id);
  assert.equal(history.messages.length, 1);
  assert.equal(history.messages[0].content, prompt);
  assert.equal(history.pendingMessageId, history.messages[0].id);
  assert.deepEqual(await getConversation(event(historyPath)).json(), history, "Reloading before the first turn preserves the stored prompt");
  assert.equal(store.listProjects().length, beforeCreate + 1);
  const request = {
    projectId: conversationProject.id, pendingMessageId: history.pendingMessageId,
    files: conversationProject.files, revision: conversationProject.revision,
  };
  const response = await sendMessage(event("assistant-project", request));
  assert.equal(response.status, 200);
  const streamed = (await response.text()).trim().split("\n").map(line => JSON.parse(line));
  assert.equal(streamed.at(-1).type, "result");
  assert.equal(streamed.at(-1).session.title, "Book Price Crawler");
  assert.equal(store.listProjects().find(item => item.id === conversationProject.id)?.name, "Book Price Crawler");
  const reopened = await getConversation(event(historyPath)).json();
  assert.equal(reopened.pendingMessageId, undefined);
  assert.equal(reopened.session.title, "Book Price Crawler");
  assert.deepEqual(reopened.messages.map((message: { role: string }) => message.role), ["user", "assistant"]);
  assert.equal(reopened.messages[0].content, prompt);
  assert.equal(reopened.messages[1].content, "Let's build this crawler.");
  assert.equal((await sendMessage(event("assistant-project", request))).status, 409, "A repeated initial request must not send the prompt twice");
  const refreshed = store.getProject(conversationProject.id)!;
  const followup = await sendMessage(event("assistant-project", {
    projectId: refreshed.id, message: "Also collect titles", files: refreshed.files, revision: refreshed.revision,
  }));
  await followup.text();
  assert.equal((await getConversation(event(historyPath)).json()).messages.length, 4);
  assert.equal(store.listProjects()[0].id, conversationProject.id, "Recent conversation activity moves the project to the top");
  assert.equal(titleRequests, 2);
  failTitle = true;
  const untitled = store.createHarnessProject("Keep this provisional title");
  const untitledSession = store.getOrCreateSession(untitled.id)!;
  const fallback = await runAssistant({ projectId: untitled.id, sessionId: untitledSession.id, message: "Keep this provisional title" });
  assert.equal(fallback.error, undefined, "Title failures must not fail the assistant turn");
  assert.equal(fallback.content, "Let's build this crawler.");
  assert.match(fallback.titleError ?? "", /retry/);
  assert.equal(store.getProject(untitled.id)?.name, "Keep this provisional title");
  store.renameSession(untitledSession.id, "Unexpected overwrite", "Outdated name");
  assert.equal(store.getProject(untitled.id)?.name, "Keep this provisional title");
  failTitle = false;
  truncateTitle = true;
  const truncated = await runAssistant({ projectId: untitled.id, sessionId: untitledSession.id, message: "continue" });
  assert.equal(truncated.error, undefined);
  assert.match(truncated.titleError ?? "", /retry/);
  assert.equal(lastTitlePrompt, "Keep this provisional title", "Retries must summarize the opening request, not 'continue'");
  truncateTitle = false;
  // Simulate a conversation created before title-pending metadata existed.
  sqlite.prepare("UPDATE assistant_messages SET metadata = json_remove(metadata, '$.titlePending') WHERE session_id = ?").run(untitledSession.id);
  const recovered = await runAssistant({ projectId: untitled.id, sessionId: untitledSession.id, message: "continue" });
  assert.equal(recovered.sessionTitle, "Book Price Crawler", "A prior failed title must retry even with existing Pi state");
  assert.equal(recovered.titleError, undefined);
  assert.equal(store.sessionTitlePrompt(untitledSession.id, "Book Price Crawler"), undefined);
  const afterRecovery = titleRequests;
  await runAssistant({ projectId: untitled.id, sessionId: untitledSession.id, message: "one more change" });
  assert.equal(titleRequests, afterRecovery, "Successful titles are generated only once");

  const manuallyNamed = store.createHarnessProject("Original project name");
  const manuallyNamedSession = store.getOrCreateSession(manuallyNamed.id)!;
  store.updateProject(manuallyNamed.id, { ...manuallyNamed, name: "My chosen title" });
  await runAssistant({ projectId: manuallyNamed.id, sessionId: manuallyNamedSession.id, message: "Build it" });
  assert.equal(store.getProject(manuallyNamed.id)?.name, "My chosen title");
  assert.equal(store.getOrCreateSession(manuallyNamed.id)?.title, "My chosen title");
  assert.equal(titleRequests, afterRecovery, "Manual titles must not be overwritten");

  const interrupted = store.createHarnessProject("Initially interrupted");
  const interruptedSession = store.getOrCreateSession(interrupted.id)!;
  mode = "abort";
  const interruptedTurn = runAssistant({ projectId: interrupted.id, sessionId: interruptedSession.id, message: "Initially interrupted" });
  setTimeout(() => cancelAssistant(interrupted.id), 30);
  assert.equal((await interruptedTurn).stopped, true);
  mode = "chat";
  const afterInterrupt = await runAssistant({ projectId: interrupted.id, sessionId: interruptedSession.id, message: "continue" });
  assert.equal(afterInterrupt.sessionTitle, "Book Price Crawler");
  assert.equal(lastTitlePrompt, "Initially interrupted");

  const waitFor = async (check: () => boolean) => {
    const deadline = Date.now() + 5000;
    while (!check()) {
      assert.ok(Date.now() < deadline, "Background turn did not reach the expected state");
      await new Promise(resolve => setTimeout(resolve, 10));
    }
  };
  const baseline = await getCompletions(event("assistant-completions")).json();
  assert.deepEqual(baseline.completions, [], "Initial notification fetch must not announce historical turns");
  assert.equal(getCompletions(event("assistant-completions?after=-1")).status, 400);
  const backgroundProject = store.getProject(project.id)!;
  const backgroundRequest = { projectId: project.id, message: "Keep working while I leave", files: backgroundProject.files, revision: backgroundProject.revision };
  mode = "background";
  const connection = new AbortController();
  const backgroundEvent = event("assistant-project", backgroundRequest);
  backgroundEvent.request = new Request(backgroundEvent.request, { signal: connection.signal });
  const backgroundResponse = await sendMessage(backgroundEvent);
  const reader = backgroundResponse.body!.getReader();
  assert.match(new TextDecoder().decode((await reader.read()).value), /Working in the background/);
  await reader.cancel();
  connection.abort();
  assert.equal(assistantRunning(project.id), true, "Closing the response stream must not cancel Pi");
  assert.equal(runtime.assistantTurns.get(project.id)?.listeners.size, 0, "Disconnected observers must be detached");
  assert.throws(() => store.deleteProject(project.id), /busy/, "Background work keeps its workspace lock");
  assert.equal((await sendMessage(event("assistant-project", backgroundRequest))).status, 409);
  const requestCount = requests.length;
  const live = await getConversation(event(`assistant-project?project_id=${project.id}`)).json();
  assert.equal(live.running, true);
  assert.equal(live.progress.text, "Working in the background.");
  assert.equal(requests.length, requestCount, "Reconnecting must not restart the model turn");
  finishBackground!();
  await waitFor(() => !runtime.assistantTurns.has(project.id));
  const completed = await getConversation(event(`assistant-project?project_id=${project.id}`)).json();
  assert.equal(completed.running, false);
  assert.equal(completed.messages.at(-1).content, "Working in the background. Finished.");
  assert.equal(completed.messages.at(-1).metadata.stopped, false);
  const notifications = await getCompletions(event(`assistant-completions?after=${baseline.cursor}`)).json();
  assert.equal(notifications.completions.length, 1);
  assert.equal(notifications.completions[0].projectId, project.id);
  assert.equal(notifications.completions[0].outcome, "completed");
  assert.deepEqual((await getCompletions(event(`assistant-completions?after=${notifications.cursor}`)).json()).completions, []);

  mode = "abort";
  const cancelResponse = await sendMessage(event("assistant-project", backgroundRequest));
  await cancelResponse.body!.cancel();
  assert.equal(assistantRunning(project.id), true);
  assert.equal((await stopConversation(event(`assistant-project?project_id=${project.id}`)).json()).stopped, true);
  await waitFor(() => !runtime.assistantTurns.has(project.id));
  const cancelledNotice = await getCompletions(event(`assistant-completions?after=${notifications.cursor}`)).json();
  assert.equal(cancelledNotice.completions[0].outcome, "stopped");
  mode = "failure";
  const failureResponse = await sendMessage(event("assistant-project", backgroundRequest));
  await failureResponse.body!.cancel();
  await waitFor(() => !runtime.assistantTurns.has(project.id));
  const failureNotice = await getCompletions(event(`assistant-completions?after=${cancelledNotice.cursor}`)).json();
  assert.equal(failureNotice.completions[0].outcome, "failed");
  assert.match(store.listMessages(session.id).at(-1)!.metadata.error as string, /Invalid test model/);
  console.log("Background assistant passed: disconnect, progress recovery, one active turn, workspace locks, persisted completion, notification cursors, explicit cancellation, and failure reporting.");
  console.log("Pi assistant passed: automatic titles with reasoning, failure/truncation/interruption recovery, manual titles, persisted tool previews, persistent project conversations, first-prompt recovery and deduplication, native tools, streaming, cancellation, errors, and workspace locks.");
} finally { globalThis.fetch = originalFetch; await stopOrchestrator(); }
