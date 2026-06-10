import { sqlite } from "./db.js";

const booksToScrapeConfig = {
  start_urls: ["https://books.toscrape.com/"],
  allowed_domains: ["books.toscrape.com"],
  max_depth: 1,
  follow: [{ css: ".next a", same_domain: true }],
  extract: {
    item_css: ".product_pod",
    fields: {
      title: { css: "h3 a", attr: "title" },
      price: ".price_color",
      availability: ".availability",
    },
  },
};

function now() {
  return Date.now();
}

function serializeDate(value) {
  return value ? new Date(value).toISOString().replace("T", " ").slice(0, 16) : "";
}

function parseJson(value, fallback = undefined) {
  if (value === null || value === undefined || value === "") {
    return fallback;
  }
  return JSON.parse(value);
}

function projectRow(row) {
  return {
    id: row.id,
    name: row.name,
    type: row.type,
    target: row.git_url || "https://books.toscrape.com/",
    status: row.status || "Ready",
    updatedAt: serializeDate(row.updated_at),
  };
}

function projectDetail(row) {
  return {
    ...projectRow(row),
    config: parseJson(row.config),
  };
}

function jobRow(row) {
  return {
    id: row.id,
    projectId: row.project_id,
    project: row.project,
    status: row.status,
    command: row.command,
    startedAt: serializeDate(row.started_at || row.created_at),
    finishedAt: serializeDate(row.finished_at),
    duration: duration(row.started_at, row.finished_at),
    items: row.items || 0,
    metadata: parseJson(row.metadata, {}),
  };
}

function logRow(row) {
  return {
    id: row.id,
    jobId: row.job_id,
    stream: row.stream,
    message: row.message,
    time: new Date(row.created_at).toISOString().slice(11, 19),
  };
}

function dataItemRow(row) {
  return {
    id: row.id,
    jobId: row.job_id,
    url: row.url || "",
    item: parseJson(row.item, {}),
    createdAt: serializeDate(row.created_at),
  };
}

function duration(startedAt, finishedAt) {
  if (!startedAt) {
    return "";
  }
  const end = finishedAt || now();
  const seconds = Math.max(0, Math.round((end - startedAt) / 1000));
  if (seconds < 60) {
    return `${seconds}s`;
  }
  const minutes = Math.floor(seconds / 60);
  const remainder = seconds % 60;
  return `${minutes}m ${remainder.toString().padStart(2, "0")}s`;
}

export function listProjects() {
  return sqlite
    .prepare(
      `
      SELECT p.*,
        COALESCE((
          SELECT status FROM jobs
          WHERE project_id = p.id
          ORDER BY created_at DESC
          LIMIT 1
        ), 'Ready') AS status
      FROM projects p
      ORDER BY p.updated_at DESC
    `,
    )
    .all()
    .map(projectRow);
}

export function getProject(id) {
  const row = sqlite.prepare("SELECT * FROM projects WHERE id = ?").get(id);
  return row ? projectDetail(row) : undefined;
}

export function createProject(input) {
  const timestamp = now();
  const row = sqlite
    .prepare(
      `
      INSERT INTO projects (name, type, git_url, config, created_at, updated_at)
      VALUES (?, ?, ?, ?, ?, ?)
      RETURNING *
    `,
    )
    .get(
      input.name,
      input.type,
      input.target,
      input.config ? JSON.stringify(input.config) : null,
      timestamp,
      timestamp,
    );
  return projectRow({ ...row, status: "Ready" });
}

export function createBooksToScrapeProject() {
  return createProject({
    name: "Books to Scrape",
    type: "source",
    target: "https://books.toscrape.com/",
    config: booksToScrapeConfig,
  });
}

export function updateProject(id, input) {
  const row = sqlite
    .prepare(
      `
      UPDATE projects
      SET name = ?, type = ?, git_url = ?, config = ?, updated_at = ?
      WHERE id = ?
      RETURNING *
    `,
    )
    .get(
      input.name,
      input.type,
      input.target,
      input.config ? JSON.stringify(input.config) : null,
      now(),
      id,
    );
  return row ? projectDetail(row) : undefined;
}

export function deleteProject(id) {
  const tx = sqlite.transaction(() => {
    const jobIds = sqlite.prepare("SELECT id FROM jobs WHERE project_id = ?").all(id);
    for (const job of jobIds) {
      sqlite.prepare("DELETE FROM data_items WHERE job_id = ?").run(job.id);
      sqlite.prepare("DELETE FROM logs WHERE job_id = ?").run(job.id);
    }
    sqlite.prepare("DELETE FROM jobs WHERE project_id = ?").run(id);
    return sqlite.prepare("DELETE FROM projects WHERE id = ?").run(id).changes;
  });
  return tx() > 0;
}

export function listJobs() {
  return sqlite
    .prepare(
      `
      SELECT j.*, p.name AS project, COUNT(d.id) AS items
      FROM jobs j
      JOIN projects p ON p.id = j.project_id
      LEFT JOIN data_items d ON d.job_id = j.id
      GROUP BY j.id
      ORDER BY j.created_at DESC
    `,
    )
    .all()
    .map(jobRow);
}

export function getJob(id) {
  const row = sqlite
    .prepare(
      `
      SELECT j.*, p.name AS project, COUNT(d.id) AS items
      FROM jobs j
      JOIN projects p ON p.id = j.project_id
      LEFT JOIN data_items d ON d.job_id = j.id
      WHERE j.id = ?
      GROUP BY j.id
    `,
    )
    .get(id);
  return row ? jobRow(row) : undefined;
}

export function createJob(projectId) {
  const project = getProject(projectId);
  if (!project) {
    return undefined;
  }
  const timestamp = now();
  const row = sqlite
    .prepare(
      `
      INSERT INTO jobs (project_id, status, command, created_at, updated_at)
      VALUES (?, 'queued', ?, ?, ?)
      RETURNING *
    `,
    )
    .get(projectId, `webuse crawl project:${projectId}`, timestamp, timestamp);
  return getJob(row.id);
}

export function claimJob() {
  const tx = sqlite.transaction(() => {
    const row = sqlite
      .prepare("SELECT id FROM jobs WHERE status = 'queued' ORDER BY created_at LIMIT 1")
      .get();
    if (!row) {
      return undefined;
    }
    const timestamp = now();
    const result = sqlite
      .prepare(
        `
        UPDATE jobs
        SET status = 'running', started_at = ?, updated_at = ?
        WHERE id = ? AND status = 'queued'
      `,
      )
      .run(timestamp, timestamp, row.id);
    return result.changes > 0 ? getJob(row.id) : undefined;
  });
  return tx();
}

export function reconcileRunningJobs() {
  const timestamp = now();
  const rows = sqlite.prepare("SELECT id FROM jobs WHERE status = 'running'").all();
  for (const row of rows) {
    appendLog(row.id, "stderr", "worker restarted while this job was running");
  }
  sqlite
    .prepare(
      `
      UPDATE jobs
      SET status = 'failed', finished_at = ?, updated_at = ?
      WHERE status = 'running'
    `,
    )
    .run(timestamp, timestamp);
}

export function updateJobCommand(id, command) {
  sqlite.prepare("UPDATE jobs SET command = ?, updated_at = ? WHERE id = ?").run(command, now(), id);
}

export function finishJob(id, status, metadata = {}) {
  const timestamp = now();
  sqlite
    .prepare(
      `
      UPDATE jobs
      SET status = ?, finished_at = ?, metadata = ?, updated_at = ?
      WHERE id = ?
    `,
    )
    .run(status, timestamp, JSON.stringify(metadata), timestamp, id);
}

export function cancelQueuedJob(id) {
  const timestamp = now();
  return (
    sqlite
      .prepare(
        `
        UPDATE jobs
        SET status = 'cancelled', finished_at = ?, updated_at = ?
        WHERE id = ? AND status = 'queued'
      `,
      )
      .run(timestamp, timestamp, id).changes > 0
  );
}

export function appendLog(jobId, stream, message) {
  sqlite
    .prepare("INSERT INTO logs (job_id, stream, message, created_at) VALUES (?, ?, ?, ?)")
    .run(jobId, stream, message, now());
}

export function listLogs(jobId) {
  const rows = jobId
    ? sqlite.prepare("SELECT * FROM logs WHERE job_id = ? ORDER BY created_at, id").all(jobId)
    : sqlite.prepare("SELECT * FROM logs ORDER BY created_at DESC, id DESC LIMIT 500").all();
  return rows.map(logRow);
}

export function insertDataItem(jobId, item) {
  const url = typeof item.url === "string" ? item.url : null;
  sqlite
    .prepare("INSERT INTO data_items (job_id, url, item, created_at) VALUES (?, ?, ?, ?)")
    .run(jobId, url, JSON.stringify(item), now());
}

export function clearDataItems(jobId) {
  sqlite.prepare("DELETE FROM data_items WHERE job_id = ?").run(jobId);
}

export function listDataItems(jobId) {
  const rows = jobId
    ? sqlite.prepare("SELECT * FROM data_items WHERE job_id = ? ORDER BY id").all(jobId)
    : sqlite.prepare("SELECT * FROM data_items ORDER BY created_at DESC, id DESC LIMIT 500").all();
  return rows.map(dataItemRow);
}
