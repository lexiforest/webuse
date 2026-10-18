import { databasePath, sqlite, transaction } from "./db";
import { nextCronTime } from "./cron";
import { randomUUID } from "node:crypto";
import { defaultPanels, panelSelection } from "../monitoring";
import { assertWorkspaceIdle, initializeWorkspace, readWorkspace, writeWorkspace, type ProjectFile } from "./workspace";
export type { ProjectFile } from "./workspace";

type Row = Record<string, unknown>;
export type ProjectInput = {
  name: string;
  target: string;
  cron?: string;
  crawlCommand?: string;
  config?: Record<string, unknown>;
  files?: ProjectFile[];
  revision?: string;
};

function parseJson<T>(value: unknown, fallback: T): T {
  if (typeof value !== "string" || !value) return fallback;
  try { return JSON.parse(value) as T; } catch { return fallback; }
}

function provisionalTitle(prompt: string) {
  const title = prompt.split("\n", 1)[0].replace(/https?:\/\/\S+/gi, "").replace(/\s+/g, " ").trim() || "New crawler";
  return title.length > 56 ? `${title.slice(0, 53).trimEnd()}...` : title;
}

function setTitlePending(sessionId: number, pending: boolean) {
  sqlite.prepare("UPDATE assistant_messages SET metadata = json_set(COALESCE(metadata, '{}'), '$.titlePending', json(?)) WHERE id = (SELECT id FROM assistant_messages WHERE session_id = ? AND role = 'user' ORDER BY id LIMIT 1)").run(JSON.stringify(pending), sessionId);
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
    target: (row.target as string) || "",
    cron: (row.cron as string) || "",
    crawlCommand: (row.crawl_command as string) || "",
    nextExecutionAt: displayDate(row.next_run_at),
    status: (row.status as string) || "Ready",
    updatedAt: displayDate(row.updated_at),
    workspacePath: row.workspace_path as string,
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
    startedAtMs: Number(row.started_at || row.created_at),
    finishedAtMs: row.finished_at ? Number(row.finished_at) : null,
    duration: displayDuration(row.started_at, row.finished_at),
    items: Number(row.items || 0),
    metadata: parseJson<Record<string, unknown>>(row.metadata, {}),
  };
}

export const store = {
  databasePath,
  monitoringInstance() {
    sqlite.prepare("INSERT OR IGNORE INTO settings (key, value, updated_at) VALUES ('monitoring-instance', ?, ?)").run(randomUUID(), Date.now());
    return String((sqlite.prepare("SELECT value FROM settings WHERE key = 'monitoring-instance'").get() as Row).value);
  },
  monitoringPanels(projectId: number) {
    const row = sqlite.prepare("SELECT panels FROM monitoring_preferences WHERE project_id = ?").get(projectId) as Row | undefined;
    return row ? panelSelection(parseJson(row.panels, defaultPanels)) : [...defaultPanels];
  },
  saveMonitoringPanels(projectId: number, panels: unknown) {
    const value = panelSelection(panels);
    sqlite.prepare("INSERT INTO monitoring_preferences (project_id, panels) VALUES (?, ?) ON CONFLICT(project_id) DO UPDATE SET panels = excluded.panels").run(projectId, JSON.stringify(value));
    return value;
  },
  listProjects() {
    return (sqlite.prepare(`SELECT p.*, COALESCE((SELECT status FROM jobs WHERE project_id = p.id ORDER BY created_at DESC LIMIT 1), 'Ready') status FROM projects p ORDER BY updated_at DESC, id DESC`).all() as Row[]).map(projectRow);
  },
  getProject(id: number) {
    const row = sqlite.prepare("SELECT * FROM projects WHERE id = ?").get(id) as Row | undefined;
    if (!row) return undefined;
    const project = projectRow(row);
    return { ...project, config: parseJson<Record<string, unknown> | undefined>(row.config, undefined), ...readWorkspace(project.workspacePath) };
  },
  createProject(value: ProjectInput) {
    const now = Date.now();
    const cron = value.cron?.trim() || null;
    // Allocate the ID durably before filesystem work. A failed creation must not
    // reuse an ID whose directory might contain recoverable files.
    const result = sqlite.prepare(`INSERT INTO projects (name, target, config, cron, next_run_at, created_at, updated_at, crawl_command, workspace_path) VALUES (?, ?, ?, ?, ?, ?, ?, ?, '')`).run(
      value.name, value.target, value.config ? JSON.stringify(value.config) : null, cron, cron ? nextCronTime(cron, now) : null, now, now, value.crawlCommand?.trim() || "",
    );
    const id = Number(result.lastInsertRowid);
    try {
      const root = initializeWorkspace(id, value.files || []);
      sqlite.prepare("UPDATE projects SET workspace_path = ? WHERE id = ?").run(root, id);
    } catch (error) {
      sqlite.prepare("DELETE FROM projects WHERE id = ?").run(id);
      throw error;
    }
    return this.getProject(id)!;
  },
  createHarnessProject(prompt: string) {
    const name = provisionalTitle(prompt);
    const target = prompt.match(/https?:\/\/[^\s<>"')\]]+/i)?.[0]?.replace(/[.,;:!?]+$/, "") || "Generated from prompt";
    const project = this.createProject({ name, target, files: [{ path: "webuse.yaml", content: `name: ${JSON.stringify(name)}\nspiders: {}\n` }] });
    const session = this.getOrCreateSession(project.id)!;
    this.appendMessage(session.id, "user", prompt, { pending: true });
    return project;
  },
  updateProject(id: number, input: ProjectInput) {
    assertWorkspaceIdle(id);
    const current = this.getProject(id);
    if (!current) return undefined;
    writeWorkspace(current.workspacePath, input.files || [], input.revision || "");
    const now = Date.now();
    const cron = input.cron?.trim() || null;
    const result = sqlite.prepare(`UPDATE projects SET name = ?, target = ?, config = ?, cron = ?, next_run_at = ?, updated_at = ?, crawl_command = ? WHERE id = ?`).run(
      input.name, input.target, input.config ? JSON.stringify(input.config) : null, cron, cron ? nextCronTime(cron, now) : null, now, input.crawlCommand?.trim() || "", id,
    );
    if (!result.changes) return undefined;
    if (input.name !== current.name) {
      for (const session of sqlite.prepare("SELECT id FROM assistant_sessions WHERE project_id = ?").all(id) as { id: number }[]) setTitlePending(session.id, false);
      sqlite.prepare("UPDATE assistant_sessions SET title = ? WHERE project_id = ?").run(input.name, id);
    }
    return this.getProject(id);
  },
  saveWorkspace(id: number, files: ProjectFile[], revision: string) {
    assertWorkspaceIdle(id);
    const project = this.getProject(id);
    if (!project) return undefined;
    writeWorkspace(project.workspacePath, files, revision);
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
    const project = sqlite.prepare("SELECT workspace_path FROM projects WHERE id = ?").get(projectId) as Row | undefined;
    if (!project) return undefined;
    const now = Date.now();
    const result = sqlite.prepare("INSERT INTO jobs (project_id, status, command, metadata, created_at, updated_at) VALUES (?, 'queued', ?, ?, ?, ?)").run(projectId, `python -m webuse.cli crawl project:${projectId}`, JSON.stringify({ ...metadata, workspacePath: project.workspace_path }), now, now);
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
  updateJobMetadata(id: number, metadata: Record<string, unknown>) { sqlite.prepare("UPDATE jobs SET metadata = ? WHERE id = ?").run(JSON.stringify({ ...this.getJob(id)?.metadata, ...metadata }), id); },
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
    const due = sqlite.prepare("SELECT id, cron FROM projects WHERE cron IS NOT NULL AND cron != '' AND next_run_at <= ? ORDER BY next_run_at, id").all(now) as { id: number; cron: string }[];
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
  sessionTitlePrompt(sessionId: number, expectedName: string) {
    const first = sqlite.prepare("SELECT content, metadata FROM assistant_messages WHERE session_id = ? AND role = 'user' ORDER BY id LIMIT 1").get(sessionId) as Row | undefined;
    if (!first) return undefined;
    const pending = parseJson<Record<string, unknown>>(first.metadata, {}).titlePending;
    const session = sqlite.prepare("SELECT title FROM assistant_sessions WHERE id = ?").get(sessionId) as Row | undefined;
    if (pending === false || session?.title !== expectedName) return undefined;
    // Older conversations have no marker. Retry only if they still have the initial prompt-derived name.
    return pending === true || expectedName === provisionalTitle(first.content as string) ? first.content as string : undefined;
  },
  renameSession(sessionId: number, title: string, expectedName: string) {
    return transaction(() => {
      const now = Date.now();
      const changed = sqlite.prepare("UPDATE projects SET name = ?, updated_at = ? WHERE id = (SELECT project_id FROM assistant_sessions WHERE id = ?) AND name = ?").run(title, now, sessionId, expectedName);
      if (changed.changes) {
        sqlite.prepare("UPDATE assistant_sessions SET title = ?, updated_at = ? WHERE id = ?").run(title, now, sessionId);
        setTitlePending(sessionId, false);
      }
      return !!changed.changes;
    })();
  },
  listMessages(sessionId: number) { return (sqlite.prepare("SELECT * FROM assistant_messages WHERE session_id = ? ORDER BY created_at, id").all(sessionId) as Row[]).map(row => ({ id: row.id as number, sessionId: row.session_id as number, role: row.role as "user" | "assistant", content: row.content as string, metadata: parseJson<Record<string, unknown>>(row.metadata, {}) })); },
  assistantCompletions(after?: number) {
    const latest = Number((sqlite.prepare("SELECT COALESCE(MAX(id), 0) id FROM assistant_messages").get() as Row).id);
    if (after === undefined) return { cursor: latest, completions: [] };
    const rows = sqlite.prepare(`SELECT m.id, m.metadata, p.id project_id, p.name project
      FROM assistant_messages m JOIN assistant_sessions s ON s.id = m.session_id JOIN projects p ON p.id = s.project_id
      WHERE m.id > ? AND m.role = 'assistant' AND json_extract(m.metadata, '$.backgroundTurn') = 1
      ORDER BY m.id LIMIT 100`).all(after) as Row[];
    const completions = rows.map(row => {
      const metadata = parseJson<Record<string, unknown>>(row.metadata, {});
      return { id: Number(row.id), projectId: Number(row.project_id), project: String(row.project), outcome: metadata.stopped ? "stopped" : metadata.error ? "failed" : "completed" };
    });
    return { cursor: rows.length === 100 ? Number(rows.at(-1)!.id) : latest, completions };
  },
  claimPendingMessage(sessionId: number, messageId: number) {
    return transaction(() => {
      const message = this.listMessages(sessionId).find(message => message.id === messageId && message.role === "user" && message.metadata.pending === true);
      if (!message) return undefined;
      sqlite.prepare("UPDATE assistant_messages SET metadata = ? WHERE id = ?").run(JSON.stringify({ ...message.metadata, pending: false }), messageId);
      return message.content;
    })();
  },
  appendMessage(sessionId: number, role: "user" | "assistant", content: string, metadata: Record<string, unknown> = {}) {
    const now = Date.now();
    if (role === "user" && !sqlite.prepare("SELECT 1 FROM assistant_messages WHERE session_id = ? AND role = 'user' LIMIT 1").get(sessionId)) metadata = { titlePending: true, ...metadata };
    sqlite.prepare("INSERT INTO assistant_messages (session_id, role, content, metadata, created_at) VALUES (?, ?, ?, ?, ?)").run(sessionId, role, content, JSON.stringify(metadata), now);
    sqlite.prepare("UPDATE assistant_sessions SET updated_at = ? WHERE id = ?").run(now, sessionId);
    sqlite.prepare("UPDATE projects SET updated_at = ? WHERE id = (SELECT project_id FROM assistant_sessions WHERE id = ?)").run(now, sessionId);
  },
};
