import { build } from "esbuild";
import { mkdir, rm } from "node:fs/promises";
import { resolve } from "node:path";

const prefix = `/tmp/webuse-node-smoke-${process.pid}`;
const outputDir = resolve("node_modules/.cache/webuse");
const output = resolve(outputDir, "orchestrator-smoke.mjs");
const assistantOutput = resolve(outputDir, "assistant-smoke.mjs");
process.env.WEBUSE_DB_PATH = `${prefix}.sqlite`;
process.env.WEBUSE_WORK_DIR = `${prefix}-runs`;
process.env.WEBUSE_PYTHON_COMMAND = process.platform === "win32" ? "where" : "/usr/bin/false";

await mkdir(outputDir, { recursive: true });
try {
  await build({ entryPoints: ["tests/orchestrator-smoke.ts"], outfile: output, bundle: true, platform: "node", format: "esm", packages: "external" });
  await import(`${output}?run=${Date.now()}`);
  await build({ entryPoints: ["tests/assistant-smoke.ts"], outfile: assistantOutput, bundle: true, platform: "node", format: "esm", packages: "external", loader: { ".md": "text" } });
  await import(`${assistantOutput}?run=${Date.now()}`);
} finally {
  await Promise.all([
    rm(`${prefix}.sqlite`, { force: true }),
    rm(`${prefix}.sqlite-shm`, { force: true }),
    rm(`${prefix}.sqlite-wal`, { force: true }),
    rm(`${prefix}-runs`, { force: true, recursive: true }),
    rm(output, { force: true }),
    rm(assistantOutput, { force: true }),
  ]);
}
