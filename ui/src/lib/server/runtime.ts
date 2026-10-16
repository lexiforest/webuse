import type { spawn } from "node:child_process";
import type { DatabaseSync } from "node:sqlite";

type RuntimeState = {
  database?: DatabaseSync;
  assistants: Map<number, AbortController>;
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
