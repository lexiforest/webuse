import type { APIEvent } from "@solidjs/start/server";
import { body, json, projectFiles, projectInput, queryInt } from "~/lib/server/http";
import { ensureOrchestrator } from "~/lib/server/orchestrator";
import { store } from "~/lib/server/store";
import { cloneWorkspace, WorkspaceConflict } from "~/lib/server/workspace";

function failure(error: unknown) { return json({ error: error instanceof Error ? error.message : String(error) }, error instanceof WorkspaceConflict ? 409 : 400); }

export function GET(event: APIEvent) {
  ensureOrchestrator(); const id = queryInt(event, "id");
  if (!id) return json({ projects: store.listProjects() });
  try { const project = store.getProject(id); return project ? json({ project }) : json({ error: "Project not found." }, 404); } catch (error) { return failure(error); }
}
export async function POST(event: APIEvent) {
  ensureOrchestrator();
  if (!event.request.headers.get("content-type")?.includes("application/json")) return json({ project: store.createProject() }, 201);
  const result = projectInput(await body(event));
  if (!result.input) return json({ error: result.error }, 400);
  try {
    let project = store.createProject(result.input);
    if (project.type === "git") {
      try {
        await cloneWorkspace(project.id, project.target);
        project = store.publishWorkspace(project.id, store.getProject(project.id)!.revision)!;
      } catch (error) { store.deleteProject(project.id); throw error; }
    }
    return json({ project }, 201);
  } catch (error) { return failure(error); }
}
export async function PUT(event: APIEvent) {
  ensureOrchestrator(); const id = queryInt(event, "id");
  if (!id) return json({ error: "A valid project id is required." }, 400);
  const result = projectInput(await body(event)); if (!result.input) return json({ error: result.error }, 400);
  try { const project = store.updateProject(id, result.input); return project ? json({ project }) : json({ error: "Project not found." }, 404); } catch (error) { return failure(error); }
}
export async function PATCH(event: APIEvent) {
  const id = queryInt(event, "id"), value = await body(event);
  if (!id || typeof value?.revision !== "string") return json({ error: "Project id and workspace revision are required." }, 400);
  try {
    const files = projectFiles(value.files);
    if (!files || (value.action !== "revert" && !Array.isArray(value.files))) return json({ error: "Project files are invalid." }, 400);
    const project = value.action === "revert" ? store.revertWorkspace(id, value.revision) : store.saveWorkspace(id, files, value.revision);
    return project ? json({ project }) : json({ error: "Project not found." }, 404);
  } catch (error) { return failure(error); }
}
export function DELETE(event: APIEvent) {
  ensureOrchestrator(); const id = queryInt(event, "id"); if (!id) return json({ error: "A valid project id is required." }, 400);
  try { store.deleteProject(id); return json({ ok: true }); } catch (error) { return json({ error: error instanceof Error ? error.message : String(error) }, 409); }
}
