import { spawn } from "node:child_process";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { setTimeout as delay } from "node:timers/promises";
import { defineTool } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";
import { cancelRun, crawlEnvironment, ensureOrchestrator, pythonCommand, terminateProcess } from "./orchestrator";
import { store, type ProjectFile } from "./store";
import skill from "../../../skills/webuse-crawlers/SKILL.md?raw";

const MAX_FILE_BYTES = 256_000;
const MAX_PROJECT_BYTES = 2_000_000;
const MAX_OUTPUT = 24_000;
export const skillPath = ".webuse/skills/webuse-crawlers/SKILL.md";
const pathSchema = Type.String({ description: "Relative project file path using forward slashes." });
const textResult = (value: unknown) => ({ content: [{ type: "text" as const, text: typeof value === "string" ? value : JSON.stringify(value) }], details: {} });

function validPath(path: string) {
  return !!path && !path.startsWith("/") && !path.includes("\\") && !path.includes(":") && !path.includes("\0") && path.split("/").every(part => !!part && part !== "." && part !== "..");
}

export class DraftFiles {
  private values = new Map<string, string>();
  constructor(files: ProjectFile[]) { for (const file of files) this.write(file.path, file.content); }
  list() { return [...this.values].map(([path, content]) => ({ path, content })); }
  read(path: string) {
    if (path === skillPath) return skill;
    const content = this.values.get(path);
    if (content === undefined) throw new Error(`File not found: ${path}`);
    return content;
  }
  write(path: string, content: string) {
    if (!validPath(path) || path === skillPath) throw new Error(`Invalid or reserved project path: ${path}`);
    if (Buffer.byteLength(content) > MAX_FILE_BYTES) throw new Error("File exceeds the 256 KB Chat limit.");
    const total = this.list().reduce((size, file) => size + (file.path === path ? 0 : Buffer.byteLength(file.content)), Buffer.byteLength(content));
    if (total > MAX_PROJECT_BYTES || (!this.values.has(path) && this.values.size >= 100)) throw new Error("Chat supports at most 100 files and 2 MB per project.");
    this.values.set(path, content);
  }
  delete(path: string) { if (!this.values.delete(path)) throw new Error(`File not found: ${path}`); }
}

async function runPython(drafts: DraftFiles, code: string, signal?: AbortSignal) {
  signal?.throwIfAborted();
  const directory = await mkdtemp(join(tmpdir(), "webuse-assistant-"));
  try {
    for (const file of drafts.list()) {
      const path = join(directory, file.path);
      await mkdir(dirname(path), { recursive: true });
      await writeFile(path, file.content);
    }
    return await new Promise<{ output: string; exitCode: number | null; stopped: boolean }>((resolve, reject) => {
      const child = spawn(pythonCommand(), ["-u", "-c", code], { cwd: directory, env: crawlEnvironment(), detached: process.platform !== "win32", stdio: ["ignore", "pipe", "pipe"] });
      let output = "";
      let stopped = false;
      const stop = () => { if (!stopped) { stopped = true; terminateProcess(child); } };
      const append = (chunk: Buffer) => {
        output += chunk.toString();
        if (output.length > MAX_OUTPUT) { output = output.slice(0, MAX_OUTPUT) + "\n[Output limit reached]"; stop(); }
      };
      child.stdout.on("data", append); child.stderr.on("data", append);
      const timeout = setTimeout(stop, 30_000);
      signal?.addEventListener("abort", stop, { once: true });
      if (signal?.aborted) stop();
      const cleanup = () => { clearTimeout(timeout); signal?.removeEventListener("abort", stop); };
      child.once("error", error => { cleanup(); reject(error); });
      child.once("close", exitCode => { cleanup(); resolve({ output, exitCode, stopped }); });
    });
  } finally { await rm(directory, { recursive: true, force: true }); }
}

export function createWebuseTools(projectId: number, drafts: DraftFiles) {
  let samples = 0;
  function inspectRun(id: number) {
    const job = store.getJob(id);
    if (!job || job.projectId !== projectId) throw new Error("Run not found in this project.");
    const offset = Math.max(0, store.countLogs(id) - 30);
    return { id, status: job.status, items: job.items, logs: store.listLogs(id, 30, offset).map(log => ({ stream: log.stream, message: String(log.message).slice(0, 1000) })), records: store.listDataItems(id, 5).map(row => row.item) };
  }
  return [
    defineTool({ name: "workspace_info", label: "Workspace", description: "Discover project files, runtime capabilities, limits, and the Webuse skill path.", parameters: Type.Object({}), async execute() {
      return textResult({ projectId, files: drafts.list().map(file => file.path), skill: skillPath, execution: "Trusted local Python subprocesses, not a sandbox", limits: { toolCallsPerTurn: 30, turnSeconds: 300, pythonSeconds: 30, sampleSeconds: 60, sampleRequests: 10, samplesPerTurn: 3 }, capabilities: ["draft file editing", "HTTP inspection via curl_cffi", "Python execution", "Webuse sample crawls", "run logs and records"], unavailable: ["cloud deployment", "managed proxies", "hosted browsers", "CAPTCHA solving", "hosted extraction API"] });
    } }),
    defineTool({ name: "read_file", label: "Read file", description: "Read a project draft or the bundled Webuse skill. Supports line ranges.", parameters: Type.Object({ path: pathSchema, startLine: Type.Optional(Type.Integer({ minimum: 1 })), limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 300 })) }), async execute(_id, args) {
      const lines = drafts.read(args.path).split("\n"); const start = (args.startLine ?? 1) - 1;
      return textResult({ path: args.path, totalLines: lines.length, content: lines.slice(start, start + (args.limit ?? 200)).join("\n").slice(0, MAX_OUTPUT) });
    } }),
    defineTool({ name: "write_file", label: "Write file", description: "Create or replace a project draft file. Read existing files before replacing them.", parameters: Type.Object({ path: pathSchema, content: Type.String() }), async execute(_id, args) {
      drafts.write(args.path, args.content); return textResult({ written: args.path });
    } }),
    defineTool({ name: "edit_file", label: "Edit file", description: "Replace one exact, unique string in a project draft file.", parameters: Type.Object({ path: pathSchema, oldText: Type.String({ minLength: 1 }), newText: Type.String() }), async execute(_id, args) {
      const content = drafts.read(args.path);
      if (content.split(args.oldText).length !== 2) throw new Error("oldText must match exactly once. Read the file and include more surrounding text.");
      drafts.write(args.path, content.replace(args.oldText, () => args.newText)); return textResult({ edited: args.path });
    } }),
    defineTool({ name: "delete_file", label: "Delete file", description: "Remove a project draft file.", parameters: Type.Object({ path: pathSchema }), async execute(_id, args) {
      drafts.delete(args.path); return textResult({ deleted: args.path });
    } }),
    defineTool({ name: "fetch_page", label: "Inspect page", description: "Fetch an HTTP(S) page with curl_cffi and return status, final URL, and up to 20 KB of HTML. No JavaScript rendering.", parameters: Type.Object({ url: Type.String() }), async execute(_id, args, signal) {
      const url = new URL(args.url);
      if (!["https:", "http:"].includes(url.protocol)) throw new Error("Only HTTP(S) URLs are supported.");
      return textResult(await runPython(new DraftFiles([]), `import json\nfrom curl_cffi import requests\nresponse = requests.get(${JSON.stringify(url.href)}, timeout=20, stream=True)\ntry:\n    data = bytearray()\n    for chunk in response.iter_content():\n        data.extend(chunk)\n        if len(data) >= 20000: break\n    print(json.dumps({"status": response.status_code, "url": response.url, "html": bytes(data[:20000]).decode("utf-8", "replace"), "truncated": len(data) >= 20000}))\nfinally:\n    response.close()`, signal));
    } }),
    defineTool({ name: "run_python", label: "Run Python", description: "Run Python against a temporary snapshot of project drafts for API discovery, selector checks, and debugging. Trusted local execution, 30 seconds, bounded output. Changes on disk are temporary; retain edits with file tools.", parameters: Type.Object({ code: Type.String({ maxLength: MAX_FILE_BYTES }) }), async execute(_id, args, signal) {
      return textResult(await runPython(drafts, args.code, signal));
    } }),
    defineTool({ name: "run_crawl", label: "Sample crawl", description: "Run current drafts through the Webuse queue; return a dashboard run ID, logs, and sample records. Does not save the project. Up to 10 requests and 60 seconds including queue time.", parameters: Type.Object({ maxRequests: Type.Optional(Type.Integer({ minimum: 1, maximum: 10 })) }), async execute(_id, args, signal) {
      signal?.throwIfAborted();
      if (++samples > 3) throw new Error("Sample crawl limit reached for this turn.");
      const job = store.createJob(projectId, { assistantSample: { files: drafts.list(), maxRequests: args.maxRequests ?? 3, deadline: Date.now() + 60_000 } });
      if (!job) throw new Error("Project not found.");
      const stop = () => cancelRun(job.id);
      const timeout = setTimeout(stop, 60_000);
      signal?.addEventListener("abort", stop, { once: true });
      if (signal?.aborted) stop();
      ensureOrchestrator();
      try {
        while (["queued", "running"].includes(store.getJob(job.id)?.status ?? "")) await delay(100);
        return textResult(JSON.stringify(inspectRun(job.id)).slice(0, MAX_OUTPUT));
      } finally { clearTimeout(timeout); signal?.removeEventListener("abort", stop); }
    } }),
    defineTool({ name: "inspect_run", label: "Inspect run", description: "Read run status, recent logs, and a few output records for this project.", parameters: Type.Object({ runId: Type.Integer({ minimum: 1 }) }), async execute(_id, args) {
      return textResult(JSON.stringify(inspectRun(args.runId)).slice(0, MAX_OUTPUT));
    } }),
  ];
}
