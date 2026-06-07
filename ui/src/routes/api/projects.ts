import type { APIEvent } from "@solidjs/start/server";

import {
  createBooksToScrapeProject,
  createProject,
  deleteProject,
  getProject,
  listProjects,
  updateProject,
} from "~/lib/server/projects";

function getProjectId(event: APIEvent) {
  const url = new URL(event.request.url);
  const id = Number(url.searchParams.get("id"));
  return Number.isInteger(id) && id > 0 ? id : undefined;
}

async function readProjectInput(event: APIEvent) {
  const body = (await event.request.json()) as {
    name?: unknown;
    type?: unknown;
    target?: unknown;
    config?: unknown;
  };

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
    return { error: "Project config must be a JSON object." };
  }

  return {
    input: {
      name: body.name.trim(),
      type: body.type,
      target: body.target.trim(),
      config: body.config as Record<string, unknown> | undefined,
    },
  };
}

export async function GET(event: APIEvent) {
  const id = getProjectId(event);
  if (id !== undefined) {
    const project = getProject(id);
    if (!project) {
      return Response.json({ error: "Project not found." }, { status: 404 });
    }

    return Response.json({ project });
  }

  return Response.json({ projects: listProjects() });
}

export async function POST(event: APIEvent) {
  const contentType = event.request.headers.get("content-type") || "";

  if (!contentType.includes("application/json")) {
    return Response.json({ project: createBooksToScrapeProject() }, { status: 201 });
  }

  const result = await readProjectInput(event);
  if (result.error) {
    return Response.json({ error: result.error }, { status: 400 });
  }

  return Response.json(
    {
      project: createProject(result.input),
    },
    { status: 201 },
  );
}

export async function PUT(event: APIEvent) {
  const id = getProjectId(event);
  if (id === undefined) {
    return Response.json({ error: "A valid project id is required." }, { status: 400 });
  }

  const result = await readProjectInput(event);
  if (result.error) {
    return Response.json({ error: result.error }, { status: 400 });
  }

  const project = updateProject(id, result.input);
  if (!project) {
    return Response.json({ error: "Project not found." }, { status: 404 });
  }

  return Response.json({ project });
}

export async function DELETE(event: APIEvent) {
  const id = getProjectId(event);
  if (id === undefined) {
    return Response.json({ error: "A valid project id is required." }, { status: 400 });
  }

  deleteProject(id);
  return Response.json({ ok: true });
}
