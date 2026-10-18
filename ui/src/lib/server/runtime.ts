import type { spawn } from "node:child_process";
import type { DatabaseSync } from "node:sqlite";
import type { AssistantEvent, ToolActivity } from "./assistant";

export type TurnEvent = AssistantEvent | { type: "result"; [key: string]: unknown };
export type AssistantTurn = {
  text: string;
  tools: ToolActivity[];
  status: string;
  listeners: Set<(event: TurnEvent) => void>;
};

type RuntimeState = {
  database?: DatabaseSync;
  assistants: Map<number, AbortController>;
  assistantTurns: Map<number, AssistantTurn>;
  workspaceLocks: Set<number>;
  orchestrator: {
    active: Map<number, ReturnType<typeof spawn>>;
    running: Map<number, Promise<void>>;
    cancelling: Set<number>;
    stopping: boolean;
    shutdown?: Promise<void>;
    terminations: WeakMap<ReturnType<typeof spawn>, Promise<void>>;
    timer?: ReturnType<typeof setInterval>;
    ticking: boolean;
  };
};

// Vinxi loads Nitro plugins and SSR routes as separate module graphs.
const shared = globalThis as typeof globalThis & { __webuseRuntime?: RuntimeState };
export const runtime: RuntimeState = shared.__webuseRuntime ??= {
  assistants: new Map(),
  assistantTurns: new Map(),
  workspaceLocks: new Set(),
  orchestrator: {
    active: new Map(),
    running: new Map(),
    cancelling: new Set(),
    stopping: false,
    terminations: new WeakMap(),
    ticking: false
  }
};
// Preserve active turns across development module reloads as well as module graphs.
runtime.assistantTurns ??= new Map();
