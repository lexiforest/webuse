import assert from "node:assert/strict";
import { chmodSync, existsSync, mkdirSync, readFileSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { spawnSync } from "node:child_process";
import { store } from "../src/lib/server/store";
import { sqlite } from "../src/lib/server/db";
import { captureVersion, cloneWorkspace, lockWorkspace, materializeVersion, versionDirectory, workspaceRoot } from "../src/lib/server/workspace";

const project = store.createProject({ name: "Workspace", type: "python", target: "https://example.com", files: [{ path: "crawler.py", content: "original" }] });
assert.throws(() => store.createProject({ name: "Invalid", type: "python", target: "https://example.com", files: [{ path: "../escape", content: "bad" }] }), /Invalid/);
const afterFailure = store.createProject({ name: "After failure", type: "python", target: "https://example.com", files: [] });
assert.ok(afterFailure.id > project.id + 1, "Failed creation must not reuse a filesystem identity");
const root = project.workspacePath;
const originalVersion = project.savedVersion!;
assert.equal(readFileSync(join(root, "crawler.py"), "utf8"), "original");
assert.equal(sqlite.prepare("SELECT name FROM sqlite_master WHERE name = 'project_files'").get(), undefined);

writeFileSync(join(root, "crawler.py"), "external edit");
assert.throws(() => store.saveWorkspace(project.id, project.files, project.revision), /changed on disk/);
assert.equal(readFileSync(join(root, "crawler.py"), "utf8"), "external edit", "Stale saves must not overwrite an external editor");
const latest = store.getProject(project.id)!;
assert.equal(latest.changes[0].status, "modified");
for (const path of ["../escape", "/absolute", "a/../b", "a\\b", ".env", ".git/config", "a\0b"]) {
  assert.throws(() => store.saveWorkspace(project.id, [{ path, content: "bad" }], latest.revision), /Invalid|excluded/);
}
assert.throws(() => store.saveWorkspace(project.id, [{ path: "crawler.py", content: "must not change" }, { path: "crawler.py/nested", content: "bad" }], latest.revision), /conflicts/);
assert.equal(readFileSync(join(root, "crawler.py"), "utf8"), "external edit");
const release = lockWorkspace(project.id);
assert.throws(() => store.updateProject(project.id, { ...latest }), /busy/);
assert.throws(() => store.revertWorkspace(project.id, latest.revision), /busy/);
assert.throws(() => store.deleteProject(project.id), /busy/);
release();

mkdirSync(join(root, "fixtures"));
writeFileSync(join(root, "fixtures", "image.bin"), Buffer.from([0, 1, 2, 255]));
writeFileSync(join(root, "large.txt"), "x".repeat(256_001));
writeFileSync(join(root, ".env"), "SECRET=local-only");
mkdirSync(join(root, ".venv"));
writeFileSync(join(root, ".venv", "keep"), "environment");
const beforeSave = store.getProject(project.id)!;
assert.deepEqual(beforeSave.omitted, ["fixtures/image.bin", "large.txt"]);
store.saveWorkspace(project.id, [{ path: "crawler.py", content: "second" }], beforeSave.revision);
assert.equal(readFileSync(join(root, "fixtures", "image.bin")).length, 4);
assert.ok(existsSync(join(root, "large.txt")));
const queued = store.createJob(project.id)!;
assert.equal(queued.metadata.sourceVersion, originalVersion, "Normal runs pin the published version when enqueued");
const second = store.publishWorkspace(project.id, store.getProject(project.id)!.revision)!;
assert.notEqual(second.savedVersion, originalVersion);
assert.equal(existsSync(join(versionDirectory(project.id, second.savedVersion!), ".env")), false);
assert.equal(existsSync(join(versionDirectory(project.id, second.savedVersion!), ".venv")), false);
const copy = join(workspaceRoot, "queued-source");
materializeVersion(project.id, queued.metadata.sourceVersion as string, copy);
assert.equal(readFileSync(join(copy, "crawler.py"), "utf8"), "original");
writeFileSync(join(copy, "crawler.py"), "runtime mutation");
assert.equal(readFileSync(join(versionDirectory(project.id, originalVersion), "crawler.py"), "utf8"), "original", "Run copies must not share mutable files with saved versions");
store.cancelQueuedJob(queued.id);

writeFileSync(join(root, "crawler.py"), "unpublished third");
sqlite.prepare("UPDATE projects SET cron = '* * * * *', next_run_at = 1 WHERE id = ?").run(project.id);
store.enqueueDueJobs();
const scheduled = store.listJobs(project.id).find(job => job.status === "queued")!;
assert.equal(scheduled.metadata.sourceVersion, second.savedVersion);
store.cancelQueuedJob(scheduled.id);
const sample = store.createJob(project.id, { assistantSample: { maxRequests: 1, deadline: Date.now() + 60_000 } })!;
writeFileSync(join(root, "crawler.py"), "fourth after enqueue");
const sampleCopy = join(workspaceRoot, "sample-source");
materializeVersion(project.id, sample.metadata.sourceVersion as string, sampleCopy);
assert.equal(readFileSync(join(sampleCopy, "crawler.py"), "utf8"), "unpublished third");
store.finishJob(sample.id, "succeeded", { itemCount: 1 });
assert.equal(store.getJob(sample.id)!.metadata.sourceVersion, sample.metadata.sourceVersion);

writeFileSync(join(root, "new.txt"), "remove on revert");
const reverted = store.revertWorkspace(project.id, store.getProject(project.id)!.revision)!;
assert.equal(readFileSync(join(root, "crawler.py"), "utf8"), "second");
assert.equal(existsSync(join(root, "new.txt")), false);
assert.equal(readFileSync(join(root, ".env"), "utf8"), "SECRET=local-only");
assert.equal(readFileSync(join(root, ".venv", "keep"), "utf8"), "environment");
assert.equal(reverted.changes.length, 0);
if (process.platform !== "win32") {
  chmodSync(join(root, "crawler.py"), 0o755);
  assert.notEqual(store.getProject(project.id)!.revision, reverted.revision, "Executable modes participate in source versions");
  symlinkSync(copy, join(root, "linked"));
  assert.throws(() => captureVersion(project.id, root), /Symlinks/);
  rmSync(join(root, "linked"));
}
const savedFile = join(versionDirectory(project.id, originalVersion), "crawler.py");
writeFileSync(savedFile, "tampered");
assert.throws(() => materializeVersion(project.id, originalVersion, join(workspaceRoot, "bad-copy")), /modified on disk/);
writeFileSync(savedFile, "original");

// Clone an empty local repository without network access or modifying the user's Git history.
const gitSource = join(workspaceRoot, "git-source");
const gitInit = spawnSync("git", ["init", "--bare", gitSource], { encoding: "utf8" });
assert.equal(gitInit.status, 0, gitInit.stderr);
const imported = store.createProject({ name: "Git import", type: "git", target: gitSource, files: [] });
await cloneWorkspace(imported.id, gitSource);
writeFileSync(join(imported.workspacePath, "crawler.py"), "editable clone");
const importedSaved = store.publishWorkspace(imported.id, store.getProject(imported.id)!.revision)!;
assert.ok(importedSaved.savedVersion);
assert.equal(importedSaved.files[0].content, "editable clone");
assert.ok(existsSync(join(imported.workspacePath, ".git")));
console.log("Workspaces passed: disk persistence, conflict detection, binary files, snapshot isolation, scheduling, revert, path validation, and Git import.");
