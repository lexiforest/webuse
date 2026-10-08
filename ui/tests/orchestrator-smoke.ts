import assert from "node:assert/strict";
import { nextCronTime, validCron } from "../src/lib/server/cron";
import { ensureOrchestrator, stopOrchestrator } from "../src/lib/server/orchestrator";
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
  sqlite.prepare("DELETE FROM project_files WHERE project_id = ?").run(project.id);
  throw new Error("rollback test");
}), /rollback test/);
assert.equal(store.getProject(project.id)!.files.length, 1);
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
stopOrchestrator();
