import http from "node:http";

import {
  cancelQueuedJob,
  createBooksToScrapeProject,
  createJob,
  createProject,
  deleteProject,
  getJob,
  getProject,
  listDataItems,
  listJobs,
  listLogs,
  listProjects,
  updateProject,
} from "./store.js";
import { cancelRunningJob, startRunner } from "./runner.js";

const port = Number(process.env.WEBUSE_WORKER_PORT || "8787");
const host = process.env.WEBUSE_WORKER_HOST || "127.0.0.1";

function json(response, body, status = 200) {
  response.writeHead(status, {
    "content-type": "application/json; charset=utf-8",
    "cache-control": "no-store",
  });
  response.end(JSON.stringify(body));
}

function getId(url) {
  const id = Number(url.searchParams.get("id"));
  return Number.isInteger(id) && id > 0 ? id : undefined;
}

async function readJson(request) {
  const chunks = [];
  for await (const chunk of request) {
    chunks.push(chunk);
  }
  if (chunks.length === 0) {
    return undefined;
  }
  return JSON.parse(Buffer.concat(chunks).toString("utf8"));
}

function validateProjectInput(body) {
  if (!body || typeof body !== "object") {
    return { error: "Project body is required." };
  }
  if (typeof body.name !== "string" || body.name.trim().length === 0) {
    return { error: "Project name is required." };
  }
  if (body.type !== "source" && body.type !== "git") {
    return { error: "Project type must be source or git." };
  }
  if (typeof body.target !== "string" || body.target.trim().length === 0) {
    return { error: "Project source is required." };
  }
  if (body.config !== undefined && (typeof body.config !== "object" || body.config === null || Array.isArray(body.config))) {
    return { error: "Project config must be an object." };
  }
  return {
    input: {
      name: body.name.trim(),
      type: body.type,
      target: body.target.trim(),
      config: body.config,
    },
  };
}

async function handleProjects(request, response, url) {
  const id = getId(url);

  if (request.method === "GET") {
    if (id !== undefined) {
      const project = getProject(id);
      return project ? json(response, { project }) : json(response, { error: "Project not found." }, 404);
    }
    return json(response, { projects: listProjects() });
  }

  if (request.method === "POST") {
    const body = await readJson(request).catch(() => undefined);
    if (!body) {
      return json(response, { project: createBooksToScrapeProject() }, 201);
    }
    const result = validateProjectInput(body);
    if (result.error) {
      return json(response, { error: result.error }, 400);
    }
    return json(response, { project: createProject(result.input) }, 201);
  }

  if (request.method === "PUT") {
    if (id === undefined) {
      return json(response, { error: "A valid project id is required." }, 400);
    }
    const result = validateProjectInput(await readJson(request));
    if (result.error) {
      return json(response, { error: result.error }, 400);
    }
    const project = updateProject(id, result.input);
    return project ? json(response, { project }) : json(response, { error: "Project not found." }, 404);
  }

  if (request.method === "DELETE") {
    if (id === undefined) {
      return json(response, { error: "A valid project id is required." }, 400);
    }
    deleteProject(id);
    return json(response, { ok: true });
  }

  return json(response, { error: "Method not allowed." }, 405);
}

async function handleJobs(request, response, url) {
  const id = getId(url);

  if (request.method === "GET") {
    if (id !== undefined) {
      const job = getJob(id);
      return job ? json(response, { job }) : json(response, { error: "Job not found." }, 404);
    }
    return json(response, { jobs: listJobs() });
  }

  if (request.method === "POST") {
    const body = await readJson(request);
    const projectId = Number(body?.projectId);
    if (!Number.isInteger(projectId) || projectId <= 0) {
      return json(response, { error: "A valid projectId is required." }, 400);
    }
    const job = createJob(projectId);
    return job ? json(response, { job }, 201) : json(response, { error: "Project not found." }, 404);
  }

  if (request.method === "DELETE") {
    if (id === undefined) {
      return json(response, { error: "A valid job id is required." }, 400);
    }
    const cancelled = cancelQueuedJob(id) || cancelRunningJob(id);
    return json(response, { ok: cancelled });
  }

  return json(response, { error: "Method not allowed." }, 405);
}

function handleLogs(response, url) {
  const jobId = getId(url);
  return json(response, { logs: listLogs(jobId) });
}

function handleData(response, url) {
  const jobId = getId(url);
  return json(response, { dataItems: listDataItems(jobId) });
}

const server = http.createServer((request, response) => {
  void (async () => {
    const url = new URL(request.url || "/", `http://${request.headers.host || `${host}:${port}`}`);
    if (url.pathname === "/health") {
      return json(response, { ok: true });
    }
    if (url.pathname === "/projects") {
      return handleProjects(request, response, url);
    }
    if (url.pathname === "/jobs") {
      return handleJobs(request, response, url);
    }
    if (url.pathname === "/logs") {
      return handleLogs(response, url);
    }
    if (url.pathname === "/data") {
      return handleData(response, url);
    }
    return json(response, { error: "Not found." }, 404);
  })().catch(error => {
    json(response, { error: error instanceof Error ? error.message : String(error) }, 500);
  });
});

startRunner();

server.listen(port, host, () => {
  console.log(`webuse worker listening on http://${host}:${port}`);
});
