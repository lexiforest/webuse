import assert from "node:assert/strict";
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { mkdir, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { nextCronTime, validCron } from "../src/lib/server/cron";
import { ensureOrchestrator } from "../src/lib/server/orchestrator";
import { store } from "../src/lib/server/store";
import { sqlite, transaction } from "../src/lib/server/db";

assert.equal(validCron("0 * * * *"), true);
assert.equal(validCron("not a schedule"), false);
assert.equal(nextCronTime("0 * * * *", Date.UTC(2026, 8, 4, 0, 1)), Date.UTC(2026, 8, 4, 1, 0));

const project = store.createProject({
  name: "Smoke",
  target: "https://example.com",
  cron: "0 * * * *",
  files: [{ path: "webuse.yaml", content: "spiders:\n  smoke:\n    start_urls:\n      - https://example.com\n" }],
});
assert.ok(project.nextExecutionAt);
store.saveSettings({ llm: { model: "local-test" } });
assert.equal((store.getSettings().llm as { model: string }).model, "local-test");
assert.throws(transaction(() => {
  sqlite.prepare("UPDATE projects SET name = 'rollback' WHERE id = ?").run(project.id);
  throw new Error("rollback test");
}), /rollback test/);
assert.equal(store.getProject(project.id)!.files.length, 1);
assert.equal(store.getProject(project.id)!.name, "Smoke");
assert.equal(sqlite.isTransaction, false);
const execution = store.createJob(project.id);
assert.ok(execution);
ensureOrchestrator();

const deadline = Date.now() + 5000;
let current = store.getJob(execution!.id);
while (current?.status === "queued" || current?.status === "running") {
  if (Date.now() > deadline) throw new Error("Crawler process did not finish before the smoke-test timeout.");
  await new Promise(resolve => setTimeout(resolve, 50));
  current = store.getJob(execution!.id);
}

assert.equal(current?.status, "failed");
assert.ok(current?.command.includes(`crawl ${project.workspacePath} -o `));
assert.doesNotMatch(current?.command ?? "", /crawl .*webuse\.(yaml|yml|toml)/);
assert.match(store.listLogs(execution!.id)[0].message as string, /webuse\.cli/);
if (process.platform !== "win32") {
  const directory = process.env.WEBUSE_WORK_DIR!;
  await mkdir(directory, { recursive: true });
  const liveRunner = join(directory, "live-runner");
  await writeFile(liveRunner, `#!${process.execPath}
const fs = require('node:fs');
const value = fs.readFileSync('live.txt', 'utf8');
fs.writeFileSync(process.argv[process.argv.indexOf('-o') + 1], JSON.stringify({ value }) + '\\n');
fs.writeFileSync('runtime.txt', 'written in workspace');
`, { mode: 0o755 });
  const originalPython = process.env.WEBUSE_PYTHON_COMMAND;
  process.env.WEBUSE_PYTHON_COMMAND = liveRunner;
  try {
    const live = store.createJob(project.id)!;
    writeFileSync(join(project.workspacePath, "live.txt"), "edited after enqueue");
    ensureOrchestrator();
    const timeout = Date.now() + 5000;
    while (["queued", "running"].includes(store.getJob(live.id)!.status)) {
      assert.ok(Date.now() < timeout, "Live-source execution did not finish");
      await new Promise(resolve => setTimeout(resolve, 25));
    }
    assert.equal(store.getJob(live.id)!.status, "succeeded");
    assert.deepEqual(store.listDataItems(live.id)[0].item, { value: "edited after enqueue" });
    assert.equal(readFileSync(join(project.workspacePath, "runtime.txt"), "utf8"), "written in workspace");
    assert.equal(existsSync(join(directory, String(live.id), "project")), false);
  } finally { process.env.WEBUSE_PYTHON_COMMAND = originalPython; }
  const executable = join(directory, "graceful-runner");
  await writeFile(executable, `#!${process.execPath}\nprocess.on('SIGTERM', () => process.exit(0));\nconsole.log('ready');\nsetInterval(() => {}, 1000);\n`, { mode: 0o755 });
  process.env.WEBUSE_PYTHON_COMMAND = executable;
  const graceful = store.createJob(project.id)!;
  ensureOrchestrator();
  try {
    const timeout = Date.now() + 5000;
    while (!store.listLogs(graceful.id).some(log => log.message === "ready")) {
      assert.ok(Date.now() < timeout, "Test runner did not start");
      await new Promise(resolve => setTimeout(resolve, 25));
    }
    // A separately bundled route must see the job started by the Nitro plugin.
    const peerPath = "./orchestrator-peer.mjs";
    const peer = await import(peerPath);
    peer.ensureOrchestrator();
    assert.equal(store.getJob(graceful.id)?.status, "running");
    assert.equal(peer.cancelExecution(graceful.id), true);
    while (store.getJob(graceful.id)?.status === "running") {
      assert.ok(Date.now() < timeout, "Test runner did not stop");
      await new Promise(resolve => setTimeout(resolve, 25));
    }
    assert.equal(store.getJob(graceful.id)?.status, "cancelled", "A graceful exit after Stop must not count as success");
  } finally { process.env.WEBUSE_PYTHON_COMMAND = originalPython; }
}
