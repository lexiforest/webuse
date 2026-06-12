import { blob, index, integer, sqliteTable, text } from "drizzle-orm/sqlite-core";

export const projects = sqliteTable(
  "projects",
  {
    id: integer("id").primaryKey({ autoIncrement: true }),
    name: text("name").notNull(),
    type: text("type", { enum: ["source", "yaml", "python", "git"] }).notNull(),
    gitUrl: text("git_url"),
    sourceTarball: blob("source_tarball").$type<Uint8Array>(),
    config: text("config", { mode: "json" }).$type<Record<string, unknown>>(),
    cron: text("cron"),
    nextRunAt: integer("next_run_at", { mode: "timestamp" }),
    createdAt: integer("created_at", { mode: "timestamp" }).notNull(),
    updatedAt: integer("updated_at", { mode: "timestamp" }).notNull(),
  },
  table => [
    index("projects_type_idx").on(table.type),
    index("projects_created_at_idx").on(table.createdAt),
  ],
);

export const jobs = sqliteTable(
  "jobs",
  {
    id: integer("id").primaryKey({ autoIncrement: true }),
    projectId: integer("project_id")
      .notNull()
      .references(() => projects.id),
    status: text("status", { enum: ["queued", "running", "succeeded", "failed", "cancelled"] }).notNull(),
    command: text("command").notNull(),
    startedAt: integer("started_at", { mode: "timestamp" }),
    finishedAt: integer("finished_at", { mode: "timestamp" }),
    metadata: text("metadata", { mode: "json" }).$type<Record<string, unknown>>(),
    createdAt: integer("created_at", { mode: "timestamp" }).notNull(),
    updatedAt: integer("updated_at", { mode: "timestamp" }).notNull(),
  },
  table => [
    index("jobs_project_id_idx").on(table.projectId),
    index("jobs_status_idx").on(table.status),
    index("jobs_created_at_idx").on(table.createdAt),
  ],
);

export const projectFiles = sqliteTable(
  "project_files",
  {
    id: integer("id").primaryKey({ autoIncrement: true }),
    projectId: integer("project_id")
      .notNull()
      .references(() => projects.id, { onDelete: "cascade" }),
    path: text("path").notNull(),
    content: text("content").notNull(),
    createdAt: integer("created_at", { mode: "timestamp" }).notNull(),
    updatedAt: integer("updated_at", { mode: "timestamp" }).notNull(),
  },
  table => [
    index("project_files_project_id_idx").on(table.projectId),
    index("project_files_path_idx").on(table.path),
  ],
);

export const logs = sqliteTable(
  "logs",
  {
    id: integer("id").primaryKey({ autoIncrement: true }),
    jobId: integer("job_id")
      .notNull()
      .references(() => jobs.id),
    stream: text("stream", { enum: ["stdout", "stderr"] }).notNull(),
    message: text("message").notNull(),
    createdAt: integer("created_at", { mode: "timestamp" }).notNull(),
  },
  table => [
    index("logs_job_id_idx").on(table.jobId),
    index("logs_created_at_idx").on(table.createdAt),
  ],
);

export const dataItems = sqliteTable(
  "data_items",
  {
    id: integer("id").primaryKey({ autoIncrement: true }),
    jobId: integer("job_id")
      .notNull()
      .references(() => jobs.id),
    url: text("url"),
    item: text("item", { mode: "json" }).$type<Record<string, unknown>>().notNull(),
    createdAt: integer("created_at", { mode: "timestamp" }).notNull(),
  },
  table => [
    index("data_items_job_id_idx").on(table.jobId),
    index("data_items_created_at_idx").on(table.createdAt),
  ],
);

export const schema = {
  projects,
  projectFiles,
  jobs,
  logs,
  dataItems,
};
