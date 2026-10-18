import assert from "node:assert/strict";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { DatabaseSync } from "node:sqlite";
import type { APIEvent } from "@solidjs/start/server";

// Seed the previous schema before loading the store, including a Git workspace and conversation.
const directory = join(process.env.WEBUSE_WORKSPACE_DIR!, "legacy", "working");
mkdirSync(directory, { recursive: true });
writeFileSync(join(directory, "crawler.py"), "print('existing crawler')\n");
const legacy = new DatabaseSync(process.env.WEBUSE_DB_PATH!);
legacy.exec(`
  PRAGMA foreign_keys = ON;
  CREATE TABLE projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL, name TEXT NOT NULL, type TEXT NOT NULL,
    git_url TEXT, config TEXT, workspace_path TEXT NOT NULL, crawl_command TEXT NOT NULL DEFAULT '',
    cron TEXT, next_run_at INTEGER, created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL
  );
  CREATE INDEX projects_type_idx ON projects(type);
  CREATE TABLE assistant_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL, project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    title TEXT, created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL
  );
  CREATE TABLE assistant_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL, session_id INTEGER NOT NULL REFERENCES assistant_sessions(id) ON DELETE CASCADE,
    role TEXT NOT NULL, content TEXT NOT NULL, metadata TEXT, created_at INTEGER NOT NULL
  );
`);
legacy.prepare("INSERT INTO projects VALUES (1, 'Existing workspace', 'git', 'https://example.com/repo.git', '{}', ?, 'python crawler.py', NULL, NULL, 1, 1)").run(directory);
legacy.exec("INSERT INTO assistant_sessions VALUES (1, 1, 'Existing conversation', 1, 1); INSERT INTO assistant_messages VALUES (1, 1, 'user', 'Keep this conversation', '{}', 1);");
legacy.close();

const { store } = await import("../src/lib/server/store");
const { sqlite } = await import("../src/lib/server/db");
const { GET, POST, PUT } = await import("../src/routes/api/projects");
const event = (method: string, value?: unknown, id?: number) => ({ request: new Request(`http://localhost/api/projects${id ? `?id=${id}` : ""}`, { method, ...(value ? { headers: { "content-type": "application/json" }, body: JSON.stringify(value) } : {}) }) }) as APIEvent;

{
  const columns = (sqlite.prepare("PRAGMA table_info(projects)").all() as { name: string }[]).map(column => column.name);
  assert.ok(!columns.includes("type"));
  assert.ok(!columns.includes("git_url"));
  assert.ok(columns.includes("target"));
  const existing = store.getProject(1)!;
  assert.equal("type" in existing, false);
  assert.equal(existing.target, "https://example.com/repo.git");
  assert.equal(existing.workspacePath, directory);
  assert.equal(existing.crawlCommand, "python crawler.py");
  assert.equal(existing.files[0].content, "print('existing crawler')\n");
  assert.equal(store.listMessages(1)[0].content, "Keep this conversation");
  const execution = store.createJob(1)!;
  assert.equal(execution.metadata.workspacePath, directory);
  store.cancelQueuedJob(execution.id);
  const updated = await PUT(event("PUT", { ...existing, target: "https://example.com/data" }, 1));
  assert.equal(updated.status, 200, "Former Git workspaces must be editable as ordinary projects");
  assert.equal(readFileSync(join(directory, "crawler.py"), "utf8"), "print('existing crawler')\n");
  const files = [{ path: "webuse.yaml", content: "name: mixed\nspiders: {}\n" }, { path: "crawler.py", content: "print('mixed files')\n" }];
  const created = await POST(event("POST", { name: "Mixed workspace", target: "https://example.com", files }));
  assert.equal(created.status, 201);
  const project = (await created.json()).project;
  assert.equal("type" in project, false);
  assert.equal(project.files.length, 2);
  const beforeInvalid = store.listProjects().length;
  assert.equal((await POST(event("POST", { name: "Old import request", type: "git", target: directory, files: [] }))).status, 400);
  assert.equal(store.listProjects().length, beforeInvalid);
  assert.ok((await GET(event("GET")).json()).projects.every((row: object) => !("type" in row)));
  assert.deepEqual(sqlite.prepare("PRAGMA foreign_key_check").all(), []);
  store.deleteProject(project.id);
  store.deleteProject(1);
  console.log("Project model passed: legacy schema migration, preserved workspaces and conversations, mixed files, type-free API, and disabled Git import.");
}
