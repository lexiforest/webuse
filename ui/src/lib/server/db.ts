import Database from "better-sqlite3";
import { drizzle } from "drizzle-orm/better-sqlite3";

import { schema } from "./schema";

const dbPath = process.env.WEBUSE_DB_PATH || "./webuse.sqlite";

export const sqlite = new Database(dbPath);
sqlite.pragma("foreign_keys = ON");

sqlite.exec(`
  CREATE TABLE IF NOT EXISTS projects (
    id integer PRIMARY KEY AUTOINCREMENT NOT NULL,
    name text NOT NULL,
    type text NOT NULL,
    git_url text,
    source_tarball blob,
    config text,
    created_at integer NOT NULL,
    updated_at integer NOT NULL
  );
  CREATE INDEX IF NOT EXISTS projects_type_idx ON projects (type);
  CREATE INDEX IF NOT EXISTS projects_created_at_idx ON projects (created_at);

  CREATE TABLE IF NOT EXISTS jobs (
    id integer PRIMARY KEY AUTOINCREMENT NOT NULL,
    project_id integer NOT NULL,
    status text NOT NULL,
    command text NOT NULL,
    started_at integer,
    finished_at integer,
    metadata text,
    created_at integer NOT NULL,
    updated_at integer NOT NULL,
    FOREIGN KEY (project_id) REFERENCES projects(id) ON UPDATE no action ON DELETE no action
  );
  CREATE INDEX IF NOT EXISTS jobs_project_id_idx ON jobs (project_id);
  CREATE INDEX IF NOT EXISTS jobs_status_idx ON jobs (status);
  CREATE INDEX IF NOT EXISTS jobs_created_at_idx ON jobs (created_at);

  CREATE TABLE IF NOT EXISTS logs (
    id integer PRIMARY KEY AUTOINCREMENT NOT NULL,
    job_id integer NOT NULL,
    stream text NOT NULL,
    message text NOT NULL,
    created_at integer NOT NULL,
    FOREIGN KEY (job_id) REFERENCES jobs(id) ON UPDATE no action ON DELETE no action
  );
  CREATE INDEX IF NOT EXISTS logs_job_id_idx ON logs (job_id);
  CREATE INDEX IF NOT EXISTS logs_created_at_idx ON logs (created_at);

  CREATE TABLE IF NOT EXISTS data_items (
    id integer PRIMARY KEY AUTOINCREMENT NOT NULL,
    job_id integer NOT NULL,
    url text,
    item text NOT NULL,
    created_at integer NOT NULL,
    FOREIGN KEY (job_id) REFERENCES jobs(id) ON UPDATE no action ON DELETE no action
  );
  CREATE INDEX IF NOT EXISTS data_items_job_id_idx ON data_items (job_id);
  CREATE INDEX IF NOT EXISTS data_items_created_at_idx ON data_items (created_at);
`);

export const db = drizzle(sqlite, { schema });

export type DatabaseClient = typeof db;
