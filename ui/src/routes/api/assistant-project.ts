import type { APIEvent } from "@solidjs/start/server";
import { body, json, projectFiles, queryInt } from "~/lib/server/http";
import { runAssistant } from "~/lib/server/assistant";
import { store } from "~/lib/server/store";

export function GET(event: APIEvent) {
  const projectId = queryInt(event, "project_id"); if (!projectId) return json({ error: "A valid project_id is required." }, 400);
  const session = store.getOrCreateSession(projectId); return session ? json({ session, messages: store.listMessages(session.id) }) : json({ error: "Project not found." }, 404);
}
export async function POST(event: APIEvent) {
  const value = await body(event); const projectId = Number(value?.projectId); const message = typeof value?.message === "string" ? value.message.trim() : "";
  if (!Number.isInteger(projectId) || projectId < 1) return json({ error: "A valid projectId is required." }, 400);
  if (!message) return json({ error: "Assistant message is required." }, 400);
  const files = projectFiles(value?.files); if (!files) return json({ error: "Assistant files are invalid." }, 400);
  const session = store.getOrCreateSession(projectId); if (!session) return json({ error: "Project not found." }, 404);
  const history = store.listMessages(session.id); store.appendMessage(session.id, "user", message);
  try {
    const result = await runAssistant(files, typeof value?.selectedPath === "string" ? value.selectedPath : undefined, history, message);
    const metadata = { changedFiles: result.changedFiles };
    store.appendMessage(session.id, "assistant", result.content, metadata);
    return json({ session, message: { role: "assistant", content: result.content, metadata }, messages: store.listMessages(session.id), files: result.files, changedFiles: result.changedFiles, selectedPath: result.selectedPath, toolResults: [] });
  } catch (error) { return json({ error: error instanceof Error ? error.message : String(error) }, 500); }
}
