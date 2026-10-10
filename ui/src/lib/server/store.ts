import { databasePath, sqlite, transaction } from "./db";
import { nextCronTime } from "./cron";
import { assertWorkspaceIdle, captureVersion, initializeWorkspace, projectDirectory, readWorkspace, restoreVersion, versionDirectory, workspaceChanges, writeWorkspace, type ProjectFile } from "./workspace";
export type { ProjectFile } from "./workspace";

type Row = Record<string, unknown>;
export type ProjectInput = {
  name: string;
  type: "yaml" | "python" | "git";
  target: string;
  cron?: string;
  config?: Record<string, unknown>;
  files?: ProjectFile[];
  revision?: string;
};

const sampleFiles: ProjectFile[] = [{
  path: "webuse.yaml",
  content: `name: Books to Scrape
spiders:
  books:
    start_urls:
      - https://books.toscrape.com/
    allowed_domains:
      - books.toscrape.com
    max_depth: 1
    pages:
      default:
        follow:
          - css: .next a
            same_domain: true
        extract:
          books:
            item_css: .product_pod
            fields:
              title:
                css: h3 a
                attr: title
              price: .price_color
              availability: .availability
`,
}];

function parseJson<T>(value: unknown, fallback: T): T {
  if (typeof value !== "string" || !value) return fallback;
  try { return JSON.parse(value) as T; } catch { return fallback; }
}

function displayDate(value: unknown) {
  return typeof value === "number" && value ? new Date(value).toISOString().replace("T", " ").slice(0, 16) : "";
}

function displayDuration(start: unknown, finish: unknown) {
  if (typeof start !== "number") return "";
  const seconds = Math.max(0, Math.round(((typeof finish === "number" ? finish : Date.now()) - start) / 1000));
  return seconds < 60 ? `${seconds}s` : `${Math.floor(seconds / 60)}m ${String(seconds % 60).padStart(2, "0")}s`;
}

function projectRow(row: Row) {
  return {
    id: row.id as number,
    name: row.name as string,
    type: row.type as ProjectInput["type"],
    target: (row.git_url as string) || "",
    cron: (row.cron as string) || "",
    nextRunAt: displayDate(row.next_run_at),
    status: (row.status as string) || "Ready",
    updatedAt: displayDate(row.updated_at),
    workspacePath: row.workspace_path as string,
    savedVersion: (row.saved_version as string | null) ?? null,
  };
}

function jobRow(row: Row) {
  return {
    id: row.id as number,
    projectId: row.project_id as number,
    project: row.project as string,
    status: row.status as "queued" | "running" | "succeeded" | "failed" | "cancelled",
    command: row.command as string,
    startedAt: displayDate((row.started_at as number) || row.created_at),
    finishedAt: displayDate(row.finished_at),
    duration: displayDuration(row.started_at, row.finished_at),
    items: Number(row.items || 0),
    metadata: parseJson<Record<string, unknown>>(row.metadata, {}),
  };
}

export const store = {
  databasePath,
  listProjects() {
    return (sqlite.prepare(`SELECT p.*, COALESCE((SELECT status FROM jobs WHERE project_id = p.id ORDER BY created_at DESC LIMIT 1), 'Ready') status FROM projects p ORDER BY updated_at DESC`).all() as Row[]).map(projectRow);
  },
  getProject(id: number) {
    const row = sqlite.prepare("SELECT * FROM projects WHERE id = ?").get(id) as Row | undefined;
    if (!row) return undefined;
    const project = projectRow(row);
    return { ...project, config: parseJson<Record<string, unknown> | undefined>(row.config, undefined), ...readWorkspace(project.workspacePath), publishedFiles: project.savedVersion ? readWorkspace(versionDirectory(id, project.savedVersion)).files : [], changes: workspaceChanges(id, project.workspacePath, project.savedVersion) };
  },
  createProject(input?: ProjectInput) {
    const value = input || { name: "Books to Scrape", type: "yaml" as const, target: "https://books.toscrape.com/", files: sampleFiles };
    const now = Date.now();
    const cron = value.cron?.trim() || null;
    // Allocate the ID durably before filesystem work. A failed creation must not
    // reuse an ID whose directory might contain recoverable files.
    const result = sqlite.prepare(`INSERT INTO projects (name, type, git_url, config, cron, next_run_at, created_at, updated_at, workspace_path) VALUES (?, ?, ?, ?, ?, ?, ?, ?, '')`).run(
      value.name, value.type, value.target, value.config ? JSON.stringify(value.config) : null, cron, cron ? nextCronTime(cron, now) : null, now, now,
    );
    const id = Number(result.lastInsertRowid);
    try {
      const root = initializeWorkspace(id, value.files || []);
      const version = value.type === "git" ? null : captureVersion(id, root);
      sqlite.prepare("UPDATE projects SET workspace_path = ?, saved_version = ? WHERE id = ?").run(root, version, id);
    } catch (error) {
      sqlite.prepare("DELETE FROM projects WHERE id = ?").run(id);
      throw error;
    }
    return this.getProject(id)!;
  },
  updateProject(id: number, input: ProjectInput) {
    assertWorkspaceIdle(id);
    const current = this.getProject(id);
    if (!current) return undefined;
    if ((current.type === "git" || input.type === "git") && (input.type !== current.type || input.target !== current.target)) throw new Error("Create a new Git import to change repositories. Existing workspace files are kept.");
    const workspace = writeWorkspace(current.workspacePath, input.files || [], input.revision || "");
    const version = captureVersion(id, current.workspacePath, workspace.revision);
    const now = Date.now();
    const cron = input.cron?.trim() || null;
    const result = sqlite.prepare(`UPDATE projects SET name = ?, type = ?, git_url = ?, config = ?, cron = ?, next_run_at = ?, updated_at = ?, saved_version = ? WHERE id = ?`).run(
      input.name, input.type, input.target, input.config ? JSON.stringify(input.config) : null, cron, cron ? nextCronTime(cron, now) : null, now, version, id,
    );
    if (!result.changes) return undefined;
    return this.getProject(id);
  },
  saveWorkspace(id: number, files: ProjectFile[], revision: string) {
    assertWorkspaceIdle(id);
    const project = this.getProject(id);
    if (!project) return undefined;
    writeWorkspace(project.workspacePath, files, revision);
    return this.getProject(id);
  },
  publishWorkspace(id: number, revision: string) {
    assertWorkspaceIdle(id);
    const project = this.getProject(id);
    if (!project) return undefined;
    const version = captureVersion(id, project.workspacePath, revision);
    sqlite.prepare("UPDATE projects SET saved_version = ?, updated_at = ? WHERE id = ?").run(version, Date.now(), id);
    return this.getProject(id);
  },
  revertWorkspace(id: number, revision: string) {
    assertWorkspaceIdle(id);
    const project = this.getProject(id);
    if (!project?.savedVersion) throw new Error("No published version to restore.");
    restoreVersion(id, project.workspacePath, project.savedVersion, revision);
    return this.getProject(id);
  },
  deleteProject(id: number) {
    assertWorkspaceIdle(id);
    if (sqlite.prepare("SELECT 1 FROM jobs WHERE project_id = ? AND status = 'running'").get(id)) throw new Error("Cancel the running project before deleting it.");
    transaction(() => {
      for (const row of sqlite.prepare("SELECT id FROM jobs WHERE project_id = ?").all(id) as { id: number }[]) {
        sqlite.prepare("DELETE FROM logs WHERE job_id = ?").run(row.id);
        sqlite.prepare("DELETE FROM data_items WHERE job_id = ?").run(row.id);
      }
      sqlite.prepare("DELETE FROM jobs WHERE project_id = ?").run(id);
      sqlite.prepare("DELETE FROM projects WHERE id = ?").run(id);
    })();
  },
  listJobs(projectId?: number) {
    const condition = projectId ? "WHERE j.project_id = ?" : "";
    return (sqlite.prepare(`SELECT j.*, p.name project, COUNT(d.id) items FROM jobs j JOIN projects p ON p.id = j.project_id LEFT JOIN data_items d ON d.job_id = j.id ${condition} GROUP BY j.id ORDER BY j.created_at DESC`).all(...(projectId ? [projectId] : [])) as Row[]).map(jobRow);
  },
  getJob(id: number) {
    const row = sqlite.prepare(`SELECT j.*, p.name project, COUNT(d.id) items FROM jobs j JOIN projects p ON p.id = j.project_id LEFT JOIN data_items d ON d.job_id = j.id WHERE j.id = ? GROUP BY j.id`).get(id) as Row | undefined;
    return row ? jobRow(row) : undefined;
  },
  createJob(projectId: number, metadata: Record<string, unknown> = {}) {
    const project = sqlite.prepare("SELECT saved_version FROM projects WHERE id = ?").get(projectId) as Row | undefined;
    if (!project) return undefined;
    const sourceVersion = metadata.assistantSample ? captureVersion(projectId, projectDirectory(projectId)) : project.saved_version;
    if (!sourceVersion) throw new Error("Publish a project version before starting a run.");
    const now = Date.now();
    const result = sqlite.prepare("INSERT INTO jobs (project_id, status, command, metadata, created_at, updated_at) VALUES (?, 'queued', ?, ?, ?, ?)").run(projectId, `python -m webuse.cli crawl project:${projectId}`, JSON.stringify({ ...metadata, sourceVersion }), now, now);
    return this.getJob(Number(result.lastInsertRowid));
  },
  claimJob() {
    return transaction(() => {
      const queued = sqlite.prepare("SELECT id FROM jobs WHERE status = 'queued' ORDER BY created_at, id LIMIT 1").get() as { id: number } | undefined;
      if (!queued) return undefined;
      const now = Date.now();
      sqlite.prepare("UPDATE jobs SET status = 'running', started_at = ?, updated_at = ? WHERE id = ?").run(now, now, queued.id);
      return this.getJob(queued.id);
    })();
  },
  updateJobCommand(id: number, command: string) { sqlite.prepare("UPDATE jobs SET command = ?, updated_at = ? WHERE id = ?").run(command, Date.now(), id); },
  finishJob(id: number, status: string, metadata: Record<string, unknown> = {}) { const now = Date.now(); sqlite.prepare("UPDATE jobs SET status = ?, finished_at = ?, metadata = ?, updated_at = ? WHERE id = ?").run(status, now, JSON.stringify({ ...this.getJob(id)?.metadata, ...metadata }), now, id); },
  cancelQueuedJob(id: number) { const now = Date.now(); return sqlite.prepare("UPDATE jobs SET status = 'cancelled', finished_at = ?, updated_at = ? WHERE id = ? AND status = 'queued'").run(now, now, id).changes > 0; },
  appendLog(jobId: number, stream: "stdout" | "stderr", message: string) { sqlite.prepare("INSERT INTO logs (job_id, stream, message, created_at) VALUES (?, ?, ?, ?)").run(jobId, stream, message, Date.now()); },
  listLogs(jobId?: number, limit = 100, offset = 0) {
    const safeLimit = Math.max(1, Math.min(limit, 500));
    const rows = (jobId ? sqlite.prepare("SELECT * FROM logs WHERE job_id = ? ORDER BY created_at, id LIMIT ? OFFSET ?").all(jobId, safeLimit, Math.max(offset, 0)) : sqlite.prepare("SELECT * FROM logs ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?").all(safeLimit, Math.max(offset, 0))) as Row[];
    return rows.map(row => ({ id: row.id, jobId: row.job_id, stream: row.stream, message: row.message, time: new Date(row.created_at as number).toLocaleTimeString("en-GB") }));
  },
  countLogs(jobId?: number) {
    const row = (jobId ? sqlite.prepare("SELECT COUNT(*) total FROM logs WHERE job_id = ?").get(jobId) : sqlite.prepare("SELECT COUNT(*) total FROM logs").get()) as Row;
    return Number(row.total || 0);
  },
  insertDataItem(jobId: number, item: Record<string, unknown>) { sqlite.prepare("INSERT INTO data_items (job_id, url, item, created_at) VALUES (?, ?, ?, ?)").run(jobId, typeof item.url === "string" ? item.url : null, JSON.stringify(item), Date.now()); },
  clearDataItems(jobId: number) { sqlite.prepare("DELETE FROM data_items WHERE job_id = ?").run(jobId); },
  listDataItems(jobId?: number, limit = -1) {
    const rows = (jobId ? sqlite.prepare("SELECT * FROM data_items WHERE job_id = ? ORDER BY id LIMIT ?").all(jobId, limit) : sqlite.prepare("SELECT * FROM data_items ORDER BY created_at DESC, id DESC LIMIT 500").all()) as Row[];
    return rows.map(row => ({ id: row.id, jobId: row.job_id, url: row.url || "", item: parseJson(row.item, {}), createdAt: displayDate(row.created_at) }));
  },
  enqueueDueJobs(now = Date.now()) {
    const due = sqlite.prepare("SELECT id, cron FROM projects WHERE saved_version IS NOT NULL AND cron IS NOT NULL AND cron != '' AND next_run_at <= ? ORDER BY next_run_at, id").all(now) as { id: number; cron: string }[];
    for (const project of due) {
      sqlite.prepare("UPDATE projects SET next_run_at = ?, updated_at = ? WHERE id = ?").run(nextCronTime(project.cron, now), now, project.id);
      if (!sqlite.prepare("SELECT 1 FROM jobs WHERE project_id = ? AND status IN ('queued', 'running')").get(project.id)) this.createJob(project.id, { scheduled: true, cron: project.cron, scheduledAt: now });
    }
  },
  reconcileRunningJobs() {
    for (const row of sqlite.prepare("SELECT id FROM jobs WHERE status = 'running'").all() as { id: number }[]) this.appendLog(row.id, "stderr", "Node orchestrator restarted while this crawl was running");
    const now = Date.now();
    sqlite.prepare("UPDATE jobs SET status = 'failed', finished_at = ?, updated_at = ? WHERE status = 'running'").run(now, now);
  },
  getSettings() { return parseJson<Record<string, unknown>>((sqlite.prepare("SELECT value FROM settings WHERE key = 'settings'").get() as Row | undefined)?.value, {}); },
  saveSettings(settings: Record<string, unknown>) { sqlite.prepare("INSERT INTO settings (key, value, updated_at) VALUES ('settings', ?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at").run(JSON.stringify(settings), Date.now()); },
  getAssistantState(sessionId: number): unknown[] {
    return parseJson((sqlite.prepare("SELECT entries FROM assistant_state WHERE session_id = ?").get(sessionId) as Row | undefined)?.entries, []);
  },
  saveAssistantState(sessionId: number, entries: unknown[]) {
    sqlite.prepare("INSERT INTO assistant_state (session_id, entries) VALUES (?, ?) ON CONFLICT(session_id) DO UPDATE SET entries = excluded.entries").run(sessionId, JSON.stringify(entries));
  },
  getOrCreateSession(projectId: number) {
    let row = sqlite.prepare("SELECT * FROM assistant_sessions WHERE project_id = ? ORDER BY updated_at DESC, id DESC LIMIT 1").get(projectId) as Row | undefined;
    if (!row) {
      const project = this.getProject(projectId); if (!project) return undefined;
      const now = Date.now(); const result = sqlite.prepare("INSERT INTO assistant_sessions (project_id, title, created_at, updated_at) VALUES (?, ?, ?, ?)").run(projectId, project.name, now, now);
      row = sqlite.prepare("SELECT * FROM assistant_sessions WHERE id = ?").get(result.lastInsertRowid) as Row;
    }
    return { id: row.id as number, projectId: row.project_id as number, title: row.title as string };
  },
  listMessages(sessionId: number) { return (sqlite.prepare("SELECT * FROM assistant_messages WHERE session_id = ? ORDER BY created_at, id").all(sessionId) as Row[]).map(row => ({ id: row.id as number, sessionId: row.session_id as number, role: row.role as "user" | "assistant", content: row.content as string, metadata: parseJson<Record<string, unknown>>(row.metadata, {}) })); },
  appendMessage(sessionId: number, role: "user" | "assistant", content: string, metadata: Record<string, unknown> = {}) { const now = Date.now(); sqlite.prepare("INSERT INTO assistant_messages (session_id, role, content, metadata, created_at) VALUES (?, ?, ?, ?, ?)").run(sessionId, role, content, JSON.stringify(metadata), now); sqlite.prepare("UPDATE assistant_sessions SET updated_at = ? WHERE id = ?").run(now, sessionId); },
};
