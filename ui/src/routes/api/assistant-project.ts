import type { APIEvent } from "@solidjs/start/server";
import { body, json, projectFiles, queryInt } from "~/lib/server/http";
import { assistantRunning, cancelAssistant } from "~/lib/server/assistant";
import { observeAssistantTurn, startAssistantTurn, turnProgress } from "~/lib/server/assistant-turns";
import { WorkspaceConflict } from "~/lib/server/workspace";
import { store } from "~/lib/server/store";

export function GET(event: APIEvent) {
  const projectId = queryInt(event, "project_id"); if (!projectId) return json({ error: "A valid project_id is required." }, 400);
  const session = store.getOrCreateSession(projectId);
  if (!session) return json({ error: "Project not found." }, 404);
  const messages = store.listMessages(session.id);
  return json({ session, messages, running: assistantRunning(projectId) || !!turnProgress(projectId), progress: turnProgress(projectId), pendingMessageId: messages.find(message => message.role === "user" && message.metadata.pending === true)?.id });
}
export async function POST(event: APIEvent) {
  const value = await body(event); const projectId = Number(value?.projectId);
  let message = typeof value?.message === "string" ? value.message.trim() : "";
  if (!Number.isInteger(projectId) || projectId < 1) return json({ error: "A valid projectId is required." }, 400);
  const pendingMessageId = value?.pendingMessageId;
  if (pendingMessageId !== undefined && (!Number.isInteger(pendingMessageId) || Number(pendingMessageId) < 1)) return json({ error: "A valid pendingMessageId is required." }, 400);
  if (pendingMessageId === undefined && (!message || message.length > 32_000)) return json({ error: "Assistant message is required and must be under 32,000 characters." }, 400);
  const files = projectFiles(value?.files); if (!files) return json({ error: "Assistant files are invalid." }, 400);
  const session = store.getOrCreateSession(projectId); if (!session) return json({ error: "Project not found." }, 404);
  if (assistantRunning(projectId) || turnProgress(projectId)) return json({ error: "This project already has an active assistant turn." }, 409);
  if (!Array.isArray(value?.files) || typeof value?.revision !== "string") return json({ error: "Workspace files and revision are required." }, 400);
  try { store.saveWorkspace(projectId, files, value.revision); } catch (error) { return json({ error: error instanceof Error ? error.message : String(error) }, error instanceof WorkspaceConflict ? 409 : 400); }
  if (pendingMessageId !== undefined) {
    const pending = store.claimPendingMessage(session.id, Number(pendingMessageId));
    if (!pending) return json({ error: "This message has already been started or does not belong to this project." }, 409);
    message = pending;
  } else {
    store.appendMessage(session.id, "user", message);
  }
  const turn = startAssistantTurn({ projectId, sessionId: session.id, selectedPath: typeof value?.selectedPath === "string" ? value.selectedPath : undefined, message });
  return observeAssistantTurn(turn, event.request.signal);
}

export function DELETE(event: APIEvent) {
  const projectId = queryInt(event, "project_id");
  if (!projectId) return json({ error: "A valid project_id is required." }, 400);
  return json({ stopped: cancelAssistant(projectId) });
}
