import assert from "node:assert/strict";
import { writeFileSync } from "node:fs";
import { join } from "node:path";
import { setTimeout as delay } from "node:timers/promises";
import type { NitroApp } from "nitropack/types";
import orchestratorPlugin from "../server/plugins/orchestrator";
import { ensureOrchestrator } from "../src/lib/server/orchestrator";
import { store } from "../src/lib/server/store";

const root = process.env.WEBUSE_WORK_DIR!;
const executable = join(root, "runner");
const descendant = `
  const fs = require('node:fs');
  for (const signal of ['SIGINT', 'SIGTERM']) process.on(signal, () => fs.appendFileSync(${JSON.stringify(join(root, "signals"))}, 'descendant:' + signal + '\\n'));
  process.send('ready');
  setInterval(() => {}, 1000);
`;
writeFileSync(executable, `#!${process.execPath}
const fs = require('node:fs');
const { spawn } = require('node:child_process');
const child = spawn(process.execPath, ['-e', ${JSON.stringify(descendant)}], { stdio: ['ignore', 'ignore', 'ignore', 'ipc'] });
for (const signal of ['SIGINT', 'SIGTERM']) process.on(signal, () => {
  fs.appendFileSync(${JSON.stringify(join(root, "signals"))}, 'worker:' + signal + '\\n');
  process.exit(0);
});
child.on('message', () => console.log('ready:' + child.pid));
`, { mode: 0o755 });
process.env.WEBUSE_PYTHON_COMMAND = executable;
const project = store.createProject({ name: "Shutdown", type: "python", target: "https://test/", files: [] });
const first = store.createJob(project.id)!;
const pending = store.createJob(project.id)!;
let close: () => Promise<void> = async () => {};
orchestratorPlugin({ hooks: { hook(name: string, callback: () => Promise<void>) {
  assert.equal(name, "close"); close = callback;
} } } as unknown as NitroApp);
for (const signal of ["SIGINT", "SIGTERM"] as const) process.on(signal, async () => {
  await close();
  // A route/module calling ensure during shutdown must not restart scheduling.
  ensureOrchestrator();
  await delay(50);
  assert.equal(store.getJob(first.id)!.status, "cancelled");
  assert.equal(store.getJob(pending.id)!.status, "queued");
  writeFileSync(join(root, "stopped"), "clean");
  process.exit(0);
});
const deadline = Date.now() + 5000;
while (true) {
  const ready = store.listLogs(first.id).find(log => String(log.message).startsWith("ready:"));
  if (ready) {
    const { runtime } = await import("../src/lib/server/runtime");
    process.send!({ worker: runtime.orchestrator.active.get(first.id)!.pid, descendant: Number(String(ready.message).split(":")[1]) });
    break;
  }
  assert.ok(Date.now() < deadline, "Crawler never became ready");
  await delay(25);
}
