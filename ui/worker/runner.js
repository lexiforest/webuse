import { createReadStream, existsSync } from "node:fs";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { spawn } from "node:child_process";
import { createInterface } from "node:readline";
import YAML from "yaml";

import {
  appendLog,
  claimJob,
  clearDataItems,
  finishJob,
  getProject,
  insertDataItem,
  reconcileRunningJobs,
  updateJobCommand,
} from "./store.js";

const activeChildren = new Map();

function dataRoot() {
  if (process.env.WEBUSE_WORK_DIR) {
    return process.env.WEBUSE_WORK_DIR;
  }
  const dbPath = process.env.WEBUSE_DB_PATH || "./webuse.sqlite";
  return path.join(path.dirname(path.resolve(dbPath)), "jobs");
}

function crawlCommand(args) {
  if (process.env.WEBUSE_WORKER_COMMAND) {
    const prefix = process.env.WEBUSE_WORKER_COMMAND_ARGS
      ? JSON.parse(process.env.WEBUSE_WORKER_COMMAND_ARGS)
      : [];
    return {
      command: process.env.WEBUSE_WORKER_COMMAND,
      args: [...prefix, ...args],
      cwd: process.cwd(),
    };
  }

  const repoRoot = path.resolve(process.cwd(), "..");
  if (existsSync(path.join(repoRoot, "pyproject.toml")) && existsSync(path.join(repoRoot, "src", "webuse"))) {
    return {
      command: "uv",
      args: ["run", "webuse", ...args],
      cwd: repoRoot,
    };
  }

  return {
    command: "webuse",
    args,
    cwd: process.cwd(),
  };
}

function normalizeConfig(project) {
  const config = project.config && typeof project.config === "object" ? structuredClone(project.config) : {};

  if (Array.isArray(config.start_urls)) {
    return config;
  }

  if (config.crawl && typeof config.crawl === "object") {
    const crawl = config.crawl;
    const normalized = { ...crawl };
    if (Array.isArray(crawl.seeds) && !Array.isArray(crawl.start_urls)) {
      normalized.start_urls = crawl.seeds;
      delete normalized.seeds;
    }
    return normalized;
  }

  return {
    start_urls: [project.target],
    extract: {
      fields: {
        title: "title",
      },
    },
  };
}

function splitLines(stream, callback) {
  let buffer = "";
  stream.setEncoding("utf8");
  stream.on("data", chunk => {
    buffer += chunk;
    const lines = buffer.split(/\r?\n/);
    buffer = lines.pop() || "";
    for (const line of lines) {
      if (line.length > 0) {
        callback(line);
      }
    }
  });
  stream.on("end", () => {
    if (buffer.length > 0) {
      callback(buffer);
    }
  });
}

async function importJsonl(jobId, outputPath) {
  clearDataItems(jobId);
  const stream = createReadStream(outputPath, { encoding: "utf8" });
  const lines = createInterface({ input: stream, crlfDelay: Infinity });
  let count = 0;

  for await (const line of lines) {
    if (!line.trim()) {
      continue;
    }
    insertDataItem(jobId, JSON.parse(line));
    count += 1;
  }

  return count;
}

async function runJob(job) {
  const project = getProject(job.projectId);
  if (!project) {
    appendLog(job.id, "stderr", `project not found: ${job.projectId}`);
    finishJob(job.id, "failed", { reason: "project_not_found" });
    return;
  }

  const jobDir = path.join(dataRoot(), String(job.id));
  await mkdir(jobDir, { recursive: true });

  const configPath = path.join(jobDir, "spider.yaml");
  const outputPath = path.join(jobDir, "items.jsonl");
  await writeFile(configPath, YAML.stringify(normalizeConfig(project)), "utf8");

  const crawlArgs = ["crawl", configPath, "-o", outputPath];
  const command = crawlCommand(crawlArgs);
  const commandText = [command.command, ...command.args].join(" ");
  updateJobCommand(job.id, commandText);
  appendLog(job.id, "stdout", commandText);

  const child = spawn(command.command, command.args, {
    cwd: command.cwd,
    env: process.env,
    stdio: ["ignore", "pipe", "pipe"],
  });
  activeChildren.set(job.id, child);

  splitLines(child.stdout, line => appendLog(job.id, "stdout", line));
  splitLines(child.stderr, line => appendLog(job.id, "stderr", line));

  const exit = await new Promise(resolve => {
    child.on("error", error => resolve({ code: 1, signal: null, error }));
    child.on("exit", (code, signal) => resolve({ code, signal, error: null }));
  });
  activeChildren.delete(job.id);

  if (exit.error) {
    appendLog(job.id, "stderr", exit.error.message);
    finishJob(job.id, "failed", { reason: "spawn_error", outputPath });
    return;
  }

  if (exit.signal) {
    appendLog(job.id, "stderr", `crawl terminated by ${exit.signal}`);
    finishJob(job.id, "cancelled", { reason: "signal", signal: exit.signal, outputPath });
    return;
  }

  if (exit.code !== 0) {
    appendLog(job.id, "stderr", `crawl exited with code ${exit.code}`);
    finishJob(job.id, "failed", { reason: "exit_code", code: exit.code, outputPath });
    return;
  }

  const itemCount = existsSync(outputPath) ? await importJsonl(job.id, outputPath) : 0;
  appendLog(job.id, "stdout", `imported ${itemCount} item${itemCount === 1 ? "" : "s"}`);
  finishJob(job.id, "succeeded", { outputPath, itemCount });
}

export function cancelRunningJob(jobId) {
  const child = activeChildren.get(jobId);
  if (!child) {
    return false;
  }
  child.kill("SIGTERM");
  return true;
}

export function startRunner() {
  const concurrency = Math.max(1, Number(process.env.WEBUSE_WORKER_CONCURRENCY || "1"));
  const pollMs = Math.max(250, Number(process.env.WEBUSE_WORKER_POLL_MS || "1000"));
  let running = 0;

  reconcileRunningJobs();

  const tick = () => {
    while (running < concurrency) {
      const job = claimJob();
      if (!job) {
        break;
      }
      running += 1;
      void runJob(job)
        .catch(error => {
          appendLog(job.id, "stderr", error instanceof Error ? error.message : String(error));
          finishJob(job.id, "failed", { reason: "worker_error" });
        })
        .finally(() => {
          running -= 1;
        });
    }
  };

  tick();
  return setInterval(tick, pollMs);
}
