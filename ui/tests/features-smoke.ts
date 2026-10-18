import assert from "node:assert/strict";
import { readFileSync, realpathSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { modelStatus, resolvedLlm, clearModelCache } from "../src/lib/server/models";
import { defaults } from "../src/lib/server/settings";
import { store } from "../src/lib/server/store";
import { crawlEnvironment, ensureOrchestrator } from "../src/lib/server/orchestrator";
import { visualSpiders } from "../src/lib/project-config";
import { projectInput } from "../src/lib/server/http";
import { GET as exportData } from "../src/routes/api/data";
import { GET as getLogs } from "../src/routes/api/logs";
import { GET as getExecutions, POST as createExecution, DELETE as cancelExecution } from "../src/routes/api/executions";
import type { APIEvent } from "@solidjs/start/server";

const waitFor = async (predicate: () => boolean) => {
  const deadline = Date.now() + 8000;
  while (!predicate()) {
    assert.ok(Date.now() < deadline, "Timed out waiting for execution evidence");
    await new Promise(resolve => setTimeout(resolve, 30));
  }
};

const apiEvent = (path: string, init?: RequestInit) => ({ request: new Request(`http://localhost/api/${path}`, init) }) as APIEvent;

if (process.platform !== "win32") {
  const originalPython = process.env.WEBUSE_PYTHON_COMMAND;
  const originalDefaults = defaults.llm;
  const originalSettings = store.getSettings();
  const probe = join(process.env.WEBUSE_WORK_DIR!, "model-probe");
  const probes = probe + "-calls";
  writeFileSync(probe, `#!${process.execPath}
const fs = require('node:fs');
let input = '';
process.stdin.on('data', chunk => input += chunk);
process.stdin.on('end', () => {
  const value = JSON.parse(input);
  fs.appendFileSync(${JSON.stringify(probes)}, 'probe\\n');
  const localModels = value.model === 'offline' ? [] : [{model:'local-model',baseUrl:'http://localhost:1234/v1',provider:'lmstudio'}];
  console.log(JSON.stringify({localModels,configured:value,models:value.apiKey === 'test-key' ? ['configured-model'] : []}));
});
`, { mode: 0o755 });
  try {
    process.env.WEBUSE_PYTHON_COMMAND = probe;
    defaults.llm = { model: "", baseUrl: "", apiKey: "" };
    store.saveSettings({}); clearModelCache();
    const [selected, status] = await Promise.all([resolvedLlm(), modelStatus()]);
    assert.equal(selected.model, "local-model");
    assert.equal(status.connected, true);
    assert.equal(status.source, "discovered");
    assert.equal(readFileSync(probes, "utf8"), "probe\n", "Concurrent discovery must share one probe");
    store.saveSettings({ llm: { model: "configured-model", baseUrl: "http://model.invalid/v1", apiKey: "test-key" } });
    assert.equal((await resolvedLlm()).model, "configured-model");
    const explicit = await modelStatus();
    assert.equal(explicit.connected, true);
    assert.equal(JSON.stringify(explicit).includes("test-key"), false);
    store.saveSettings({ llm: { model: "offline", baseUrl: "http://model.invalid/v1" } });
    assert.equal((await modelStatus()).connected, false);
    assert.equal((await resolvedLlm()).model, "offline", "Do not silently switch an explicit selection to a local model");
    defaults.llm = { model: "configured-model", baseUrl: "http://env.invalid/v1", apiKey: "test-key" };
    store.saveSettings({});
    assert.equal((await resolvedLlm()).baseUrl, "http://env.invalid/v1");
    store.saveSettings({ llm: { model: "local-model", baseUrl: "http://localhost:1234/v1", apiKey: "" } });
    assert.equal((await resolvedLlm()).apiKey, "", "Do not send environment credentials to a saved local endpoint");
    assert.equal(crawlEnvironment().WEBUSE_LLM_API_KEY, "webuse-local");
    defaults.llm = { model: "", baseUrl: "", apiKey: "" };
    store.saveSettings({}); clearModelCache();
    writeFileSync(probe, `#!${process.execPath}\nprocess.stdin.resume(); process.stdin.on('end',()=>console.log(JSON.stringify({localModels:[],models:[],configured:{model:'',baseUrl:'',apiKey:''}})));\n`, { mode: 0o755 });
    assert.equal((await modelStatus()).connected, false);
    assert.equal((await resolvedLlm()).model, "");
  } finally {
    process.env.WEBUSE_PYTHON_COMMAND = originalPython;
    defaults.llm = originalDefaults;
    store.saveSettings(originalSettings); clearModelCache();
  }

  const command = `${JSON.stringify(process.execPath)} crawler.cjs`;
  const project = store.createProject({ name: "Custom command", target: "https://example.com", crawlCommand: command, files: [{ path: "crawler.cjs", content: `
const fs = require('node:fs');
const output = process.env.WEBUSE_OUTPUT_PATH;
fs.writeFileSync(output, JSON.stringify({cwd:process.cwd(), max:process.env.WEBUSE_MAX_REQUESTS, executionId:process.env.WEBUSE_EXECUTION_ID}) + '\\n');
const bytes = Buffer.from(JSON.stringify({title:'書籍'}) + '\\n');
fs.appendFileSync(output, bytes.subarray(0, 12));
setTimeout(() => { fs.appendFileSync(output, bytes.subarray(12)); fs.appendFileSync(output, 'invalid\\n' + JSON.stringify({last:true})); process.exit(7); }, 1200);
` }] });
  const created = await createExecution(apiEvent("executions", { method: "POST", body: JSON.stringify({ projectId: project.id }) }));
  assert.equal(created.status, 201);
  const createdBody = await created.json();
  assert.deepEqual(Object.keys(createdBody), ["execution"]);
  const execution = createdBody.execution;
  await waitFor(() => store.getJob(execution.id)!.items === 1);
  assert.equal(store.getJob(execution.id)!.status, "running", "Records should appear while the command runs");
  await waitFor(() => store.getJob(execution.id)!.status === "failed");
  assert.equal(store.getJob(execution.id)!.command, command);
  assert.deepEqual(store.listDataItems(execution.id).map(row => row.item), [{ cwd: realpathSync(project.workspacePath), max: "", executionId: String(execution.id) }, { title: "書籍" }, { last: true }]);
  assert.equal(store.listLogs(execution.id).filter(row => String(row.message).includes("malformed JSONL")).length, 1);
  const exported = exportData({ request: new Request(`http://localhost/api/data?execution_id=${execution.id}&format=jsonl`) } as APIEvent);
  assert.equal(exported.headers.get("content-disposition"), `attachment; filename="execution-${execution.id}.jsonl"`);
  assert.equal((await exported.text()).trim().split("\n").length, 3);
  const listed = await getExecutions(apiEvent(`executions?project_id=${project.id}`)).json();
  assert.deepEqual(Object.keys(listed), ["executions"]);
  assert.deepEqual(listed.executions.map((item: { id: number }) => item.id), [execution.id]);
  const detail = await getExecutions(apiEvent(`executions?id=${execution.id}`)).json();
  assert.equal(detail.execution.status, "failed");
  const logs = await getLogs(apiEvent(`logs?execution_id=${execution.id}`)).json();
  assert.equal(logs.total, store.countLogs(execution.id));
  assert.deepEqual(logs.logs, store.listLogs(execution.id));
  const data = await exportData(apiEvent(`data?execution_id=${execution.id}`)).json();
  assert.deepEqual(data.dataItems, store.listDataItems(execution.id));

  const current = store.getProject(project.id)!;
  store.updateProject(project.id, { ...current, files: [{ path: "crawler.cjs", content: `const fs = require('node:fs'); fs.writeFileSync(process.env.WEBUSE_OUTPUT_PATH, JSON.stringify({max:process.env.WEBUSE_MAX_REQUESTS})+'\\n'); setInterval(()=>{},1000);` }] });
  const sample = store.createJob(project.id, { assistantSample: { maxRequests: 2, deadline: Date.now() + 60_000 } })!;
  ensureOrchestrator();
  await waitFor(() => store.getJob(sample.id)!.items === 1);
  assert.equal(cancelExecution(apiEvent(`executions?id=${sample.id}`, { method: "DELETE" })).status, 200);
  await waitFor(() => store.getJob(sample.id)!.status === "cancelled");
  assert.deepEqual(store.listDataItems(sample.id)[0].item, { max: "2" });
}

assert.ok(projectInput({ name: "Bad", target: "x", files: [], crawlCommand: 42 }).error);
const files = [
  { path: "spiders/books.py", content: 'class BooksSpider:\n    spider_config_path = "spiders/books.yaml"' },
  { path: "spiders/books.yaml", content: 'start_urls: [https://example.com]\npages:\n  default:\n    extract:\n      books:\n        fields:\n          title: title' },
];
const visual = visualSpiders({ spiders: { books: { path: "spiders/books.py" }, direct: "spiders/books.yaml", missing: { config: "missing.yaml" } } }, files);
assert.equal(visual.spiders.length, 2);
assert.deepEqual(visual.spiders[0].config.start_urls, ["https://example.com"]);
assert.ok(visual.notes.some(note => note.includes("missing.yaml")));
console.log("Features passed: model discovery/precedence/status, custom commands, live and partial records, JSONL export, and referenced YAML visualization.");
