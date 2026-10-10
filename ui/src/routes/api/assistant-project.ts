import type { APIEvent } from "@solidjs/start/server";
import { body, json, projectFiles, queryInt } from "~/lib/server/http";
import { assistantRunning, cancelAssistant, runAssistant } from "~/lib/server/assistant";
import { WorkspaceConflict } from "~/lib/server/workspace";
import { store } from "~/lib/server/store";

export function GET(event: APIEvent) {
  const projectId = queryInt(event, "project_id"); if (!projectId) return json({ error: "A valid project_id is required." }, 400);
  const session = store.getOrCreateSession(projectId); return session ? json({ session, messages: store.listMessages(session.id) }) : json({ error: "Project not found." }, 404);
}
export async function POST(event: APIEvent) {
  const value = await body(event); const projectId = Number(value?.projectId); const message = typeof value?.message === "string" ? value.message.trim() : "";
  if (!Number.isInteger(projectId) || projectId < 1) return json({ error: "A valid projectId is required." }, 400);
  if (!message || message.length > 32_000) return json({ error: "Assistant message is required and must be under 32,000 characters." }, 400);
  const files = projectFiles(value?.files); if (!files) return json({ error: "Assistant files are invalid." }, 400);
  const session = store.getOrCreateSession(projectId); if (!session) return json({ error: "Project not found." }, 404);
  if (assistantRunning(projectId)) return json({ error: "This project already has an active assistant turn." }, 409);
  if (!Array.isArray(value?.files) || typeof value?.revision !== "string") return json({ error: "Workspace files and revision are required." }, 400);
  try { store.saveWorkspace(projectId, files, value.revision); } catch (error) { return json({ error: error instanceof Error ? error.message : String(error) }, error instanceof WorkspaceConflict ? 409 : 400); }
  store.appendMessage(session.id, "user", message);
  const controller = new AbortController();
  const encoder = new TextEncoder();
  let connected = true;
  const stream = new ReadableStream<Uint8Array>({
    start(output) {
      const send = (value: unknown) => { if (connected) output.enqueue(encoder.encode(`${JSON.stringify(value)}\n`)); };
      void runAssistant({ projectId, sessionId: session.id, selectedPath: typeof value?.selectedPath === "string" ? value.selectedPath : undefined, message, signal: AbortSignal.any([event.request.signal, controller.signal]), onEvent: send }).then(result => {
        const metadata = { changedFiles: result.changedFiles, toolResults: result.toolResults, stopped: result.stopped };
        store.appendMessage(session.id, "assistant", result.content, metadata);
        send({ type: "result", session, messages: store.listMessages(session.id), ...result });
      }).catch(error => { send({ type: "error", error: error instanceof Error ? error.message : String(error) }); }).finally(() => { if (connected) output.close(); });
    },
    cancel() { connected = false; controller.abort(); },
  });
  return new Response(stream, { headers: { "content-type": "application/x-ndjson", "cache-control": "no-store", "x-accel-buffering": "no" } });
}

export function DELETE(event: APIEvent) {
  const projectId = queryInt(event, "project_id");
  if (!projectId) return json({ error: "A valid project_id is required." }, 400);
  return json({ stopped: cancelAssistant(projectId) });
}
