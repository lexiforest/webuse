import { runAssistant, type AssistantEvent } from "./assistant";
import { runtime, type AssistantTurn, type TurnEvent } from "./runtime";
import { store } from "./store";

export function turnProgress(projectId: number) {
  const turn = runtime.assistantTurns.get(projectId);
  return turn ? { text: turn.text, tools: turn.tools, status: turn.status } : undefined;
}

export function startAssistantTurn(options: { projectId: number; sessionId: number; message: string; selectedPath?: string }) {
  if (runtime.assistantTurns.has(options.projectId)) throw new Error("This project already has an active assistant turn.");
  const turn: AssistantTurn = { text: "", tools: [], status: "", listeners: new Set() };
  runtime.assistantTurns.set(options.projectId, turn);
  const publish = (event: TurnEvent) => {
    for (const listener of turn.listeners) listener(event);
  };
  const onEvent = (event: AssistantEvent) => {
    if (event.type === "text") turn.text += event.text;
    if (event.type === "status") turn.status = event.text;
    if (event.type === "tool") {
      const index = turn.tools.findIndex(tool => tool.id === event.tool.id);
      if (index < 0) turn.tools.push(event.tool);
      else turn.tools[index] = event.tool;
      turn.status = "";
    }
    publish(event);
  };
  // The server owns the turn. HTTP observers can disconnect without cancelling Pi.
  void runAssistant({ ...options, onEvent }).catch(error => ({
    content: `Assistant error: ${error instanceof Error ? error.message : String(error)}`,
    error: error instanceof Error ? error.message : String(error),
    changedFiles: [], toolResults: turn.tools, stopped: false, titleError: undefined,
  })).then(result => {
    store.appendMessage(options.sessionId, "assistant", result.content, {
      backgroundTurn: true, changedFiles: result.changedFiles, toolResults: result.toolResults,
      stopped: result.stopped, error: result.error, titleError: result.titleError,
    });
    publish({ type: "result", session: store.getOrCreateSession(options.projectId), messages: store.listMessages(options.sessionId), ...result });
  }).catch(error => {
    console.error("Could not persist assistant result", error);
    publish({ type: "result", error: "Could not save the assistant response. Check server logs." });
  }).finally(() => {
    runtime.assistantTurns.delete(options.projectId);
    turn.listeners.clear();
  });
  return turn;
}

export function observeAssistantTurn(turn: AssistantTurn, signal: AbortSignal) {
  const encoder = new TextEncoder();
  let detach = () => {};
  const stream = new ReadableStream<Uint8Array>({
    start(output) {
      let closed = false;
      detach = () => {
        if (closed) return;
        closed = true;
        turn.listeners.delete(send);
        signal.removeEventListener("abort", disconnect);
      };
      const disconnect = () => { detach(); try { output.close(); } catch { /* Already cancelled by the client. */ } };
      const send = (event: TurnEvent) => {
        if (closed) return;
        try {
          output.enqueue(encoder.encode(`${JSON.stringify(event)}\n`));
          if (event.type === "result") disconnect();
        } catch { detach(); }
      };
      turn.listeners.add(send);
      signal.addEventListener("abort", disconnect, { once: true });
      if (signal.aborted) disconnect();
    },
    cancel() { detach(); },
  });
  return new Response(stream, { headers: { "content-type": "application/x-ndjson", "cache-control": "no-store", "x-accel-buffering": "no" } });
}
