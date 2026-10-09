import { spawn } from "node:child_process";
import { createReadStream, existsSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { dirname, isAbsolute, join, relative, resolve, sep } from "node:path";
import { createInterface } from "node:readline";

import { store, type ProjectFile } from "./store";

type Settings = {
  runtime?: { workDirectory?: string; concurrency?: string };
  llm?: { apiKey?: string; baseUrl?: string; model?: string };
  smart?: { selectorStore?: string };
};

const active = new Map<number, ReturnType<typeof spawn>>();
const running = new Set<number>();
const cancelling = new Set<number>();
let timer: ReturnType<typeof setInterval> | undefined;
let ticking = false;

function settings() { return store.getSettings() as Settings; }
function workDirectory() { return resolve(settings().runtime?.workDirectory || process.env.WEBUSE_WORK_DIR || "./runs"); }
function concurrency() { return Math.max(1, Number(settings().runtime?.concurrency || process.env.WEBUSE_CONCURRENCY || 1) || 1); }

function safeProjectPath(root: string, path: string) {
  const target = resolve(root, path);
  const inside = relative(root, target);
  if (!path || isAbsolute(path) || inside.startsWith(`..${sep}`) || inside === "..") throw new Error(`Unsafe project file path: ${path}`);
  return target;
}

function materializeFiles(files: ProjectFile[], directory: string) {
  mkdirSync(directory, { recursive: true });
  for (const file of files) {
    const target = safeProjectPath(directory, file.path);
    mkdirSync(dirname(target), { recursive: true });
    writeFileSync(target, file.content, "utf8");
  }
}

function runProcess(jobId: number, command: string, args: string[], cwd: string) {
  return new Promise<void>((resolvePromise, reject) => {
    const child = spawn(command, args, { cwd, env: process.env, stdio: ["ignore", "pipe", "pipe"] });
    active.set(jobId, child);
    let stderr = "";
    child.stderr.on("data", chunk => { stderr += String(chunk); });
    child.once("error", error => { active.delete(jobId); reject(error); });
    child.once("exit", code => { active.delete(jobId); code === 0 ? resolvePromise() : reject(new Error(stderr.trim() || `${command} exited with code ${code}`)); });
  });
}

async function checkoutProject(jobId: number, project: NonNullable<ReturnType<typeof store.getProject>>, directory: string) {
  if (!project.target) throw new Error("Git project is missing a repository URL.");
  if (existsSync(join(directory, ".git"))) {
    await runProcess(jobId, "git", ["remote", "set-url", "origin", project.target], directory);
    await runProcess(jobId, "git", ["pull", "--ff-only"], directory);
  } else {
    if (existsSync(directory)) rmSync(directory, { recursive: true });
    mkdirSync(dirname(directory), { recursive: true });
    await runProcess(jobId, "git", ["clone", project.target, directory], workDirectory());
  }
}

export function pythonCommand() {
  if (process.env.WEBUSE_PYTHON_COMMAND) return process.env.WEBUSE_PYTHON_COMMAND;
  const candidates = process.platform === "win32"
    ? [resolve("../.venv/Scripts/python.exe"), resolve(".venv/Scripts/python.exe")]
    : [resolve("../.venv/bin/python"), resolve(".venv/bin/python")];
  return candidates.find(existsSync) || (process.platform === "win32" ? "python" : "python3");
}

export function crawlEnvironment() {
  const value = settings();
  return {
    ...process.env,
    ...(value.llm?.apiKey ? { WEBUSE_LLM_API_KEY: value.llm.apiKey } : {}),
    ...(value.llm?.baseUrl ? { WEBUSE_LLM_BASE_URL: value.llm.baseUrl } : {}),
    ...(value.llm?.model ? { WEBUSE_LLM_MODEL: value.llm.model } : {}),
    ...(value.smart?.selectorStore ? { WEBUSE_SELECTOR_STORE: value.smart.selectorStore } : {}),
  };
}

async function importJsonl(jobId: number, path: string) {
  if (!existsSync(path)) return 0;
  store.clearDataItems(jobId);
  let count = 0;
  const lines = createInterface({ input: createReadStream(path), crlfDelay: Infinity });
  for await (const line of lines) {
    if (!line.trim()) continue;
    try {
      const item = JSON.parse(line) as Record<string, unknown>;
      if (item && typeof item === "object" && !Array.isArray(item)) { store.insertDataItem(jobId, item); count += 1; }
    } catch { store.appendLog(jobId, "stderr", "ignored malformed JSONL output line"); }
  }
  return count;
}

async function runJob(job: NonNullable<ReturnType<typeof store.getJob>>) {
  const project = store.getProject(job.projectId);
  if (!project) { store.finishJob(job.id, "failed", { reason: "project_not_found" }); return; }
  const root = workDirectory();
  const jobDirectory = join(root, String(job.id));
  let projectDirectory = join(jobDirectory, "project");
  let sampleTimeout: ReturnType<typeof setTimeout> | undefined;
  mkdirSync(jobDirectory, { recursive: true });
  try {
    const sample = job.metadata as { assistantSample?: { files: ProjectFile[]; maxRequests: number; deadline: number } };
    if (sample.assistantSample) {
      if (sample.assistantSample.deadline <= Date.now()) {
        store.finishJob(job.id, "cancelled", { reason: "sample_timeout" }); return;
      }
      materializeFiles(sample.assistantSample.files, projectDirectory);
    } else if (project.type === "git") {
      projectDirectory = join(root, "projects", String(project.id), "repo");
      await checkoutProject(job.id, project, projectDirectory);
    } else {
      materializeFiles(project.files, projectDirectory);
    }
    const config = ["webuse.toml", "webuse.yaml", "webuse.yml"].map(name => join(projectDirectory, name)).find(existsSync);
    const target = config || projectDirectory;
    const output = join(jobDirectory, "items.jsonl");
    const command = pythonCommand();
    const args = ["-m", "webuse.cli", "crawl", target, "-o", output];
    if (sample.assistantSample) args.push("--max-requests", String(sample.assistantSample.maxRequests));
    const commandText = [command, ...args].join(" ");
    store.updateJobCommand(job.id, commandText);
    store.appendLog(job.id, "stdout", commandText);
    const child = spawn(command, args, { cwd: projectDirectory, env: crawlEnvironment(), detached: process.platform !== "win32", stdio: ["ignore", "pipe", "pipe"] });
    active.set(job.id, child);
    if (sample.assistantSample) sampleTimeout = setTimeout(() => cancelRun(job.id), Math.max(1, sample.assistantSample.deadline - Date.now()));
    const pipe = (stream: NodeJS.ReadableStream, name: "stdout" | "stderr") => {
      const lines = createInterface({ input: stream, crlfDelay: Infinity });
      lines.on("line", line => store.appendLog(job.id, name, line));
    };
    pipe(child.stdout, "stdout"); pipe(child.stderr, "stderr");
    const result = await new Promise<{ code: number | null; signal: NodeJS.Signals | null }>((resolvePromise, reject) => {
      child.once("error", reject);
      child.once("exit", (code, signal) => resolvePromise({ code, signal }));
    });
    active.delete(job.id);
    const wasCancelled = cancelling.delete(job.id);
    if (wasCancelled || result.signal) { store.finishJob(job.id, "cancelled", { reason: wasCancelled ? "cancelled" : "signal", signal: result.signal, outputPath: output }); return; }
    if (result.code !== 0) { store.finishJob(job.id, "failed", { reason: "exit_code", code: result.code, outputPath: output }); return; }
    const itemCount = await importJsonl(job.id, output);
    store.appendLog(job.id, "stdout", `imported ${itemCount} item${itemCount === 1 ? "" : "s"}`);
    store.finishJob(job.id, "succeeded", { outputPath: output, itemCount });
  } catch (error) {
    active.delete(job.id);
    const message = error instanceof Error ? error.message : String(error);
    store.appendLog(job.id, "stderr", message);
    store.finishJob(job.id, cancelling.delete(job.id) ? "cancelled" : "failed", { reason: "orchestrator_error" });
  } finally { if (sampleTimeout) clearTimeout(sampleTimeout); }
}

async function tick() {
  if (ticking) return;
  ticking = true;
  try {
    store.enqueueDueJobs();
    while (running.size < concurrency()) {
      const job = store.claimJob();
      if (!job) break;
      running.add(job.id);
      void runJob(job).finally(() => { running.delete(job.id); void tick(); });
    }
  } finally { ticking = false; }
}

export function ensureOrchestrator() {
  if (!timer) {
    mkdirSync(workDirectory(), { recursive: true });
    store.reconcileRunningJobs();
    timer = setInterval(() => void tick(), Math.max(250, Number(process.env.WEBUSE_POLL_MS || 1000)));
    timer.unref();
  }
  void tick();
}

export function cancelRun(id: number) {
  const child = active.get(id);
  if (child) { cancelling.add(id); terminateProcess(child); return true; }
  return store.cancelQueuedJob(id);
}

export function stopOrchestrator() {
  if (timer) clearInterval(timer);
  timer = undefined;
  for (const child of active.values()) terminateProcess(child);
}

export function terminateProcess(child: ReturnType<typeof spawn>) {
  const kill = (signal: NodeJS.Signals) => {
    try {
      if (process.platform !== "win32" && child.pid) process.kill(-child.pid, signal);
      else child.kill(signal);
    } catch { child.kill(signal); }
  };
  kill("SIGTERM");
  const force = setTimeout(() => kill("SIGKILL"), 1500);
  force.unref();
  child.once("close", () => clearTimeout(force));
}
