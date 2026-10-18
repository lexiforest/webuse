import { spawn } from "node:child_process";
import { mkdirSync, readFileSync } from "node:fs";
import { dirname, delimiter, isAbsolute, join, resolve } from "node:path";
import { createInterface } from "node:readline";
import { setTimeout as delay } from "node:timers/promises";

import { store } from "./store";
import { runtime } from "./runtime";
import { pythonCommand } from "./python";
import { recordCollector } from "./records";
import { effectiveSettings } from "./settings";
export { pythonCommand } from "./python";

type Settings = {
  runtime?: { workDirectory?: string; concurrency?: string };
  llm?: { apiKey?: string; baseUrl?: string; model?: string };
};

const state = runtime.orchestrator;
const { active, running, cancelling } = state;

function settings() { return store.getSettings() as Settings; }
function workDirectory() { return resolve(settings().runtime?.workDirectory || process.env.WEBUSE_WORK_DIR || "./executions"); }
function concurrency() { return Math.max(1, Number(settings().runtime?.concurrency || process.env.WEBUSE_CONCURRENCY || 1) || 1); }

export function crawlEnvironment() {
  const value = effectiveSettings();
  return {
    ...process.env,
    ...(value.llm.baseUrl ? { WEBUSE_LLM_API_KEY: value.llm.apiKey || "webuse-local" } : {}),
    ...(value.llm?.baseUrl ? { WEBUSE_LLM_BASE_URL: value.llm.baseUrl } : {}),
    ...(value.llm?.model ? { WEBUSE_LLM_MODEL: value.llm.model } : {}),
  };
}

async function runJob(job: NonNullable<ReturnType<typeof store.getJob>>) {
  const root = workDirectory();
  const jobDirectory = join(root, String(job.id));
  const projectDirectory = job.metadata.workspacePath as string;
  let child: ReturnType<typeof spawn> | undefined;
  let closed: Promise<void> | undefined;
  let sampleTimeout: ReturnType<typeof setTimeout> | undefined;
  let records: ReturnType<typeof recordCollector> | undefined;
  mkdirSync(jobDirectory, { recursive: true });
  try {
    const sample = job.metadata as { assistantSample?: { maxRequests: number; deadline: number } };
    if (sample.assistantSample) {
      if (sample.assistantSample.deadline <= Date.now()) {
        store.finishJob(job.id, "cancelled", { reason: "sample_timeout" }); return;
      }
    }
    const output = join(jobDirectory, "items.jsonl");
    const custom = store.getProject(job.projectId)?.crawlCommand;
    const python = pythonCommand();
    const command = custom ? (process.platform === "win32" ? process.env.ComSpec || "cmd.exe" : "/bin/sh") : python;
    const args = custom ? (process.platform === "win32" ? ["/d", "/s", "/c", custom] : ["-c", custom])
      : ["-m", "webuse.cli", "crawl", projectDirectory, "-o", output];
    if (!custom && sample.assistantSample) args.push("--max-requests", String(sample.assistantSample.maxRequests));
    const commandText = custom || [command, ...args].join(" ");
    store.updateJobCommand(job.id, commandText);
    store.appendLog(job.id, "stdout", commandText);
    const env = {
      ...crawlEnvironment(),
      PATH: [isAbsolute(python) ? dirname(python) : "", process.env.PATH].filter(Boolean).join(delimiter),
      WEBUSE_PYTHON_COMMAND: python,
      WEBUSE_OUTPUT_PATH: output,
      WEBUSE_PROJECT_ID: String(job.projectId),
      WEBUSE_EXECUTION_ID: String(job.id),
      WEBUSE_METRICS_ENABLED: process.env.WEBUSE_METRICS_ENABLED || "1",
      WEBUSE_METRICS_INSTANCE: store.monitoringInstance(),
      WEBUSE_METRICS_SUMMARY_PATH: join(jobDirectory, "metrics.json"),
      WEBUSE_MAX_REQUESTS: sample.assistantSample ? String(sample.assistantSample.maxRequests) : "",
    };
    records = recordCollector(job.id, output);
    child = spawn(command, args, { cwd: projectDirectory, env, detached: process.platform !== "win32", stdio: ["ignore", "pipe", "pipe"] });
    const worker = child;
    closed = new Promise(resolve => worker.once("close", () => resolve()));
    active.set(job.id, child);
    if (sample.assistantSample) sampleTimeout = setTimeout(() => cancelExecution(job.id), Math.max(1, sample.assistantSample.deadline - Date.now()));
    const pipe = (stream: NodeJS.ReadableStream, name: "stdout" | "stderr") => {
      const lines = createInterface({ input: stream, crlfDelay: Infinity });
      lines.on("line", line => store.appendLog(job.id, name, line));
    };
    pipe(child.stdout!, "stdout"); pipe(child.stderr!, "stderr");
    const result = await new Promise<{ code: number | null; signal: NodeJS.Signals | null }>((resolvePromise, reject) => {
      worker.once("error", reject);
      worker.once("exit", (code, signal) => resolvePromise({ code, signal }));
    });
    // A crawler may leave descendants or inherited log pipes behind on exit.
    await terminateProcess(child);
    await closed;
    await records.stop(); records = undefined;
    try { store.updateJobMetadata(job.id, { monitoring: JSON.parse(readFileSync(join(jobDirectory, "metrics.json"), "utf8")) }); } catch { /* Custom commands may not emit telemetry. */ }
    const itemCount = store.getJob(job.id)!.items;
    active.delete(job.id);
    const wasCancelled = cancelling.delete(job.id);
    if (wasCancelled || result.signal) { store.finishJob(job.id, "cancelled", { reason: wasCancelled ? "cancelled" : "signal", signal: result.signal, outputPath: output }); return; }
    if (result.code !== 0) { store.finishJob(job.id, "failed", { reason: "exit_code", code: result.code, outputPath: output }); return; }
    store.appendLog(job.id, "stdout", `imported ${itemCount} item${itemCount === 1 ? "" : "s"}`);
    store.finishJob(job.id, "succeeded", { outputPath: output, itemCount });
  } catch (error) {
    active.delete(job.id);
    const message = error instanceof Error ? error.message : String(error);
    store.appendLog(job.id, "stderr", message);
    store.finishJob(job.id, cancelling.delete(job.id) ? "cancelled" : "failed", { reason: "orchestrator_error" });
  } finally {
    if (sampleTimeout) clearTimeout(sampleTimeout);
    if (child) await terminateProcess(child);
    await closed;
    await records?.stop();
    active.delete(job.id);
    cancelling.delete(job.id);
  }
}

async function tick() {
  if (state.ticking || state.stopping) return;
  state.ticking = true;
  try {
    store.enqueueDueJobs();
    while (!state.stopping && running.size < concurrency()) {
      const job = store.claimJob();
      if (!job) break;
      const task = runJob(job).finally(() => { running.delete(job.id); void tick(); });
      running.set(job.id, task);
    }
  } finally { state.ticking = false; }
}

export function ensureOrchestrator() {
  if (state.stopping) return;
  if (!state.timer) {
    mkdirSync(workDirectory(), { recursive: true });
    store.reconcileRunningJobs();
    state.timer = setInterval(() => void tick(), Math.max(250, Number(process.env.WEBUSE_POLL_MS || 1000)));
    state.timer.unref();
  }
  void tick();
}

export function cancelExecution(id: number) {
  const child = active.get(id);
  if (child) { cancelling.add(id); void terminateProcess(child); return true; }
  return store.cancelQueuedJob(id);
}

export function stopOrchestrator(signal: NodeJS.Signals = "SIGTERM"): Promise<void> {
  if (state.shutdown) return state.shutdown;
  state.stopping = true;
  if (state.timer) clearInterval(state.timer);
  state.timer = undefined;
  const stops = [...active].map(([id, child]) => {
    cancelling.add(id);
    return terminateProcess(child, signal);
  });
  state.shutdown = Promise.all([...stops, ...running.values()]).then(() => {});
  return state.shutdown;
}

export function terminateProcess(child: ReturnType<typeof spawn>, signal: NodeJS.Signals = "SIGTERM"): Promise<void> {
  const pending = state.terminations.get(child);
  if (pending) return pending;
  const task = (async () => {
    if (!child.pid) return;
    const exited = child.exitCode !== null || child.signalCode !== null;
    const closed = exited ? Promise.resolve() : new Promise<void>(resolve => child.once("close", () => resolve()));
    if (process.platform === "win32") {
      // Windows has no POSIX process-group signals. Terminate the whole tree.
      if (!exited) await new Promise<void>(resolve => {
        const killer = spawn("taskkill", ["/PID", String(child.pid), "/T", "/F"], { stdio: "ignore" });
        killer.once("error", () => { child.kill(); resolve(); });
        killer.once("close", () => resolve());
      });
    } else {
      const send = (value: NodeJS.Signals | 0) => {
        try { process.kill(-child.pid!, value); return true; }
        catch (error) {
          if ((error as NodeJS.ErrnoException).code !== "ESRCH") throw error;
          return false;
        }
      };
      if (send(signal)) {
        const deadline = Date.now() + 1500;
        while (send(0) && Date.now() < deadline) await delay(25);
        // Do not cancel escalation when only the group leader has exited.
        if (send(0)) send("SIGKILL");
      }
    }
    await closed;
  })();
  state.terminations.set(child, task);
  return task;
}
