import { spawn } from "node:child_process";
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { setTimeout as delay } from "node:timers/promises";
import { defineTool } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";
import { cancelExecution, crawlEnvironment, ensureOrchestrator, pythonCommand, terminateProcess } from "./orchestrator";
import { store } from "./store";
import { workspaceRoot } from "./workspace";
import { harnessLimits } from "./settings";
import skill from "../../../skills/webuse-crawlers/SKILL.md?raw";

const MAX_OUTPUT = 24_000;
export const skillPath = join(workspaceRoot, "skills", "webuse-crawlers", "SKILL.md");
export function installSkill() {
  mkdirSync(dirname(skillPath), { recursive: true });
  writeFileSync(skillPath, skill);
}
const textResult = (value: unknown) => ({ content: [{ type: "text" as const, text: typeof value === "string" ? value : JSON.stringify(value) }], details: {} });

async function runPython(directory: string, code: string, signal?: AbortSignal) {
  signal?.throwIfAborted();
  return await new Promise<{ output: string; exitCode: number | null; stopped: boolean }>((resolve, reject) => {
    const child = spawn(pythonCommand(), ["-u", "-c", code], { cwd: directory, env: crawlEnvironment(), detached: process.platform !== "win32", stdio: ["ignore", "pipe", "pipe"] });
    let output = "";
    let stopped = false;
    const stop = () => { if (!stopped) { stopped = true; terminateProcess(child); } };
    const append = (chunk: Buffer) => {
      output += chunk.toString();
      if (output.length > MAX_OUTPUT) { output = output.slice(0, MAX_OUTPUT); stop(); }
    };
    child.stdout.on("data", append); child.stderr.on("data", append);
    const timeout = setTimeout(stop, 30_000);
    signal?.addEventListener("abort", stop, { once: true });
    if (signal?.aborted) stop();
    const cleanup = () => { clearTimeout(timeout); signal?.removeEventListener("abort", stop); };
    child.once("error", error => { cleanup(); reject(error); });
    child.once("close", exitCode => { cleanup(); resolve({ output, exitCode, stopped }); });
  });
}

export function createWebuseTools(projectId: number, directory: string, limits = harnessLimits()) {
  let samples = 0;
  let framework: unknown;
  function inspectExecution(id: number) {
    const job = store.getJob(id);
    if (!job || job.projectId !== projectId) throw new Error("Execution not found in this project.");
    const offset = Math.max(0, store.countLogs(id) - 30);
    return { id, status: job.status, workspacePath: job.metadata.workspacePath, items: job.items, logs: store.listLogs(id, 30, offset).map(log => ({ stream: log.stream, message: String(log.message).slice(0, 1000) })), records: store.listDataItems(id, 5).map(row => row.item) };
  }
  return [
    defineTool({ name: "workspace_info", label: "Workspace", description: "Discover workspace files, Python runtime, Webuse version, local documentation index and source paths, capabilities, and limits. Read the relevant docs before inspecting framework source.", parameters: Type.Object({}), async execute(_id, _args, signal) {
      const project = store.getProject(projectId)!;
      if (!framework) {
        try {
          const result = await runPython(directory, "import json\nfrom webuse.resources import framework_info\nprint(json.dumps(framework_info()))", signal);
          if (result.stopped || result.exitCode !== 0) throw new Error(result.output || "Python discovery failed.");
          framework = JSON.parse(result.output);
        } catch (error) {
          signal?.throwIfAborted();
          framework = { error: `Could not discover the configured Webuse installation: ${error instanceof Error ? error.message : String(error)}` };
        }
      }
      const execution = { command: project.crawlCommand || "Default Webuse crawl", output: "Write JSONL to WEBUSE_OUTPUT_PATH", sampleLimit: "Custom commands must honor WEBUSE_MAX_REQUESTS; only the 60-second timeout is enforced externally." };
      return textResult({ projectId, directory, crawl: execution, files: project.files.map(file => file.path), omittedFromEditor: project.omitted, skill: skillPath, python: pythonCommand(), framework, execution: "Trusted local filesystem and subprocess access, not a sandbox", limits: { toolCallsPerTurn: limits.maxToolCalls || null, turnSeconds: limits.turnTimeoutSeconds || null, unlimited: "null means no turn limit; configured limits stop after the current tool finishes", pythonSeconds: 30, sampleSeconds: 60, sampleRequests: 10, samplesPerTurn: 3 }, capabilities: ["native filesystem tools", "shell execution", "HTTP inspection via curl_cffi", "persistent Python execution", "Webuse sample crawls", "execution logs and records"], unavailable: ["web search", "cloud deployment", "managed proxies", "hosted browsers", "CAPTCHA solving", "hosted extraction API"] });
    } }),
    defineTool({ name: "fetch_page", label: "Inspect page", description: "Fetch an HTTP(S) page with curl_cffi and return status, final URL, and bounded HTML. No JavaScript rendering.", parameters: Type.Object({ url: Type.String() }), async execute(_id, args, signal) {
      const url = new URL(args.url);
      if (!["https:", "http:"].includes(url.protocol)) throw new Error("Only HTTP(S) URLs are supported.");
      // Bound serialized output as well as raw HTML so escaping cannot cut JSON in half.
      const result = await runPython(directory, `import json\nfrom curl_cffi import requests\nresponse = requests.get(${JSON.stringify(url.href)}, timeout=20, stream=True)\ntry:\n    data = bytearray()\n    for chunk in response.iter_content():\n        data.extend(chunk)\n        if len(data) >= 20000: break\n    html = bytes(data[:20000]).decode("utf-8", "replace")\n    truncated = len(data) >= 20000\n    while True:\n        output = json.dumps({"status": response.status_code, "url": response.url, "html": html, "truncated": truncated})\n        if len(output) <= 22000: break\n        html = html[:len(html)//2]\n        truncated = True\n        if not html: raise ValueError("Response metadata exceeds output limit")\n    print(output)\nfinally:\n    response.close()`, signal);
      if (result.stopped || result.exitCode !== 0) throw new Error(result.output || "Page fetch stopped or failed.");
      return textResult(JSON.parse(result.output));
    } }),
    defineTool({ name: "run_python", label: "Run Python", description: "Run Python in the persistent project workspace for selector checks, validation, and debugging. Use workspace_info and read the relevant local docs before API source inspection. File changes persist. Trusted local execution, 30 seconds, bounded output.", parameters: Type.Object({ code: Type.String({ maxLength: 256_000 }) }), async execute(_id, args, signal) {
      const result = await runPython(directory, args.code, signal);
      if (result.stopped || result.exitCode !== 0) throw new Error(result.output || "Python stopped or failed.");
      return textResult(result);
    } }),
    defineTool({ name: "run_crawl", label: "Sample crawl", description: "Run the project's configured command or default Webuse crawl. 60 seconds including queue time. Webuse enforces up to 10 requests; custom commands must honor WEBUSE_MAX_REQUESTS themselves and write JSONL to WEBUSE_OUTPUT_PATH.", parameters: Type.Object({ maxRequests: Type.Optional(Type.Integer({ minimum: 1, maximum: 10 })) }), async execute(_id, args, signal) {
      signal?.throwIfAborted();
      if (++samples > 3) throw new Error("Sample crawl limit reached for this turn.");
      const job = store.createJob(projectId, { assistantSample: { maxRequests: args.maxRequests ?? 3, deadline: Date.now() + 60_000 } });
      if (!job) throw new Error("Project not found.");
      const stop = () => cancelExecution(job.id);
      const timeout = setTimeout(stop, 60_000);
      signal?.addEventListener("abort", stop, { once: true });
      if (signal?.aborted) stop();
      ensureOrchestrator();
      try {
        while (["queued", "running"].includes(store.getJob(job.id)?.status ?? "")) await delay(100);
        return textResult(JSON.stringify(inspectExecution(job.id)).slice(0, MAX_OUTPUT));
      } finally { clearTimeout(timeout); signal?.removeEventListener("abort", stop); }
    } }),
    defineTool({ name: "inspect_execution", label: "Inspect execution", description: "Read execution status, recent logs, and a few output records for this project.", parameters: Type.Object({ executionId: Type.Integer({ minimum: 1 }) }), async execute(_id, args) {
      return textResult(JSON.stringify(inspectExecution(args.executionId)).slice(0, MAX_OUTPUT));
    } }),
  ];
}
