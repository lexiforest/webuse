import { DatabaseSync } from "node:sqlite";
import { mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { homedir } from "node:os";
import { runtime } from "./runtime";

export const databasePath = resolve(process.env.WEBUSE_DB_PATH || resolve(homedir(), ".webuse", "webuse.db"));
mkdirSync(dirname(databasePath), { recursive: true });

export const sqlite = runtime.database ??= new DatabaseSync(databasePath);
sqlite.exec("PRAGMA foreign_keys = ON; PRAGMA journal_mode = WAL;");

export function transaction<Args extends unknown[], Result>(callback: (...args: Args) => Result) {
  return (...args: Args): Result => {
    sqlite.exec("BEGIN IMMEDIATE");
    try {
      const result = callback(...args);
      sqlite.exec("COMMIT");
      return result;
    } catch (error) {
      if (sqlite.isTransaction) sqlite.exec("ROLLBACK");
      throw error;
    }
  };
}

sqlite.exec(`
  CREATE TABLE IF NOT EXISTS projects (
    id integer PRIMARY KEY AUTOINCREMENT NOT NULL,
    name text NOT NULL,
    target text,
    config text,
    workspace_path text NOT NULL,
    crawl_command text NOT NULL DEFAULT '',
    cron text,
    next_run_at integer,
    created_at integer NOT NULL,
    updated_at integer NOT NULL
  );
  CREATE INDEX IF NOT EXISTS projects_created_at_idx ON projects (created_at);

  CREATE TABLE IF NOT EXISTS jobs (
    id integer PRIMARY KEY AUTOINCREMENT NOT NULL,
    project_id integer NOT NULL REFERENCES projects(id),
    status text NOT NULL,
    command text NOT NULL,
    started_at integer,
    finished_at integer,
    metadata text,
    created_at integer NOT NULL,
    updated_at integer NOT NULL
  );
  CREATE INDEX IF NOT EXISTS jobs_project_id_idx ON jobs (project_id);
  CREATE INDEX IF NOT EXISTS jobs_status_idx ON jobs (status);
  CREATE INDEX IF NOT EXISTS jobs_created_at_idx ON jobs (created_at);

  CREATE TABLE IF NOT EXISTS logs (
    id integer PRIMARY KEY AUTOINCREMENT NOT NULL,
    job_id integer NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    stream text NOT NULL,
    message text NOT NULL,
    created_at integer NOT NULL
  );
  CREATE INDEX IF NOT EXISTS logs_job_id_idx ON logs (job_id);
  CREATE INDEX IF NOT EXISTS logs_created_at_idx ON logs (created_at);

  CREATE TABLE IF NOT EXISTS data_items (
    id integer PRIMARY KEY AUTOINCREMENT NOT NULL,
    job_id integer NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    url text,
    item text NOT NULL,
    created_at integer NOT NULL
  );
  CREATE INDEX IF NOT EXISTS data_items_job_id_idx ON data_items (job_id);
  CREATE INDEX IF NOT EXISTS data_items_created_at_idx ON data_items (created_at);

  CREATE TABLE IF NOT EXISTS settings (
    key text PRIMARY KEY NOT NULL,
    value text NOT NULL,
    updated_at integer NOT NULL
  );
  CREATE TABLE IF NOT EXISTS monitoring_preferences (
    project_id integer PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,
    panels text NOT NULL
  );

  CREATE TABLE IF NOT EXISTS assistant_sessions (
    id integer PRIMARY KEY AUTOINCREMENT NOT NULL,
    project_id integer NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    title text,
    created_at integer NOT NULL,
    updated_at integer NOT NULL
  );

  CREATE TABLE IF NOT EXISTS assistant_messages (
    id integer PRIMARY KEY AUTOINCREMENT NOT NULL,
    session_id integer NOT NULL REFERENCES assistant_sessions(id) ON DELETE CASCADE,
    role text NOT NULL,
    content text NOT NULL,
    metadata text,
    created_at integer NOT NULL
  );
  CREATE TABLE IF NOT EXISTS assistant_state (
    session_id integer PRIMARY KEY REFERENCES assistant_sessions(id) ON DELETE CASCADE,
    entries text NOT NULL
  );
`);

transaction(() => {
  const columns = (sqlite.prepare("PRAGMA table_info(projects)").all() as { name: string }[]).map(column => column.name);
  if (columns.includes("type")) {
    sqlite.exec("DROP INDEX IF EXISTS projects_type_idx; ALTER TABLE projects DROP COLUMN type;");
  }
  if (columns.includes("git_url")) sqlite.exec("ALTER TABLE projects RENAME COLUMN git_url TO target;");
})();

if (!(sqlite.prepare("PRAGMA table_info(projects)").all() as { name: string }[]).some(column => column.name === "crawl_command")) {
  sqlite.exec("ALTER TABLE projects ADD COLUMN crawl_command text NOT NULL DEFAULT ''");
}
