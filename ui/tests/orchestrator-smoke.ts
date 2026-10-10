import assert from "node:assert/strict";
import { mkdir, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { nextCronTime, validCron } from "../src/lib/server/cron";
import { cancelRun, ensureOrchestrator, stopOrchestrator } from "../src/lib/server/orchestrator";
import { store } from "../src/lib/server/store";
import { sqlite, transaction } from "../src/lib/server/db";

assert.equal(validCron("0 * * * *"), true);
assert.equal(validCron("not a schedule"), false);
assert.equal(nextCronTime("0 * * * *", Date.UTC(2026, 8, 4, 0, 1)), Date.UTC(2026, 8, 4, 1, 0));

const project = store.createProject({
  name: "Smoke",
  type: "yaml",
  target: "https://example.com",
  cron: "0 * * * *",
  files: [{ path: "webuse.yaml", content: "spiders:\n  smoke:\n    start_urls:\n      - https://example.com\n" }],
});
assert.ok(project.nextRunAt);
store.saveSettings({ llm: { model: "local-test" } });
assert.equal((store.getSettings().llm as { model: string }).model, "local-test");
assert.throws(transaction(() => {
  sqlite.prepare("UPDATE projects SET name = 'rollback' WHERE id = ?").run(project.id);
  throw new Error("rollback test");
}), /rollback test/);
assert.equal(store.getProject(project.id)!.files.length, 1);
assert.equal(store.getProject(project.id)!.name, "Smoke");
assert.equal(sqlite.isTransaction, false);
const run = store.createJob(project.id);
assert.ok(run);
ensureOrchestrator();

const deadline = Date.now() + 5000;
let current = store.getJob(run!.id);
while (current?.status === "queued" || current?.status === "running") {
  if (Date.now() > deadline) throw new Error("Crawler process did not finish before the smoke-test timeout.");
  await new Promise(resolve => setTimeout(resolve, 50));
  current = store.getJob(run!.id);
}

assert.equal(current?.status, "failed");
assert.match(store.listLogs(run!.id)[0].message as string, /webuse\.cli/);
if (process.platform !== "win32") {
  const directory = process.env.WEBUSE_WORK_DIR!;
  await mkdir(directory, { recursive: true });
  const executable = join(directory, "graceful-runner");
  await writeFile(executable, `#!${process.execPath}\nprocess.on('SIGTERM', () => process.exit(0));\nconsole.log('ready');\nsetInterval(() => {}, 1000);\n`, { mode: 0o755 });
  const originalPython = process.env.WEBUSE_PYTHON_COMMAND;
  process.env.WEBUSE_PYTHON_COMMAND = executable;
  const graceful = store.createJob(project.id)!;
  ensureOrchestrator();
  try {
    const timeout = Date.now() + 5000;
    while (!store.listLogs(graceful.id).some(log => log.message === "ready")) {
      assert.ok(Date.now() < timeout, "Test runner did not start");
      await new Promise(resolve => setTimeout(resolve, 25));
    }
    assert.equal(cancelRun(graceful.id), true);
    while (store.getJob(graceful.id)?.status === "running") {
      assert.ok(Date.now() < timeout, "Test runner did not stop");
      await new Promise(resolve => setTimeout(resolve, 25));
    }
    assert.equal(store.getJob(graceful.id)?.status, "cancelled", "A graceful exit after Stop must not count as success");
  } finally { process.env.WEBUSE_PYTHON_COMMAND = originalPython; }
}
stopOrchestrator();
