import { build } from "esbuild";
import { mkdir, rm } from "node:fs/promises";
import { resolve } from "node:path";
import { testShutdown } from "./shutdown-smoke.mjs";

const prefix = `/tmp/webuse-node-smoke-${process.pid}`;
const outputDir = resolve("node_modules/.cache/webuse");
const output = resolve(outputDir, "orchestrator-smoke.mjs");
const peerOutput = resolve(outputDir, "orchestrator-peer.mjs");
const assistantOutput = resolve(outputDir, "assistant-smoke.mjs");
const budgetOutput = resolve(outputDir, "assistant-budget-smoke.mjs");
const workspaceOutput = resolve(outputDir, "workspace-smoke.mjs");
const shutdownOutput = resolve(outputDir, "shutdown-worker.mjs");
const featuresOutput = resolve(outputDir, "features-smoke.mjs");
const modelConfigOutput = resolve(outputDir, "model-config-smoke.mjs");
const modelLimitsOutput = resolve(outputDir, "model-limits-smoke.mjs");
const projectModelOutput = resolve(outputDir, "project-model-smoke.mjs");
const monitoringOutput = resolve(outputDir, "monitoring-smoke.mjs");
process.env.WEBUSE_DB_PATH = `${prefix}.sqlite`;
process.env.WEBUSE_WORK_DIR = `${prefix}-executions`;
process.env.WEBUSE_WORKSPACE_DIR = `${prefix}-workspaces`;
process.env.WEBUSE_PYTHON_COMMAND = process.platform === "win32" ? "where" : "/usr/bin/false";

await mkdir(outputDir, { recursive: true });
try {
  await build({ entryPoints: ["tests/project-model-smoke.ts"], outfile: projectModelOutput, bundle: true, platform: "node", format: "esm", packages: "external" });
  await import(`${projectModelOutput}?run=${Date.now()}`);
  await build({ entryPoints: ["tests/monitoring-smoke.ts"], outfile: monitoringOutput, bundle: true, platform: "node", format: "esm", packages: "external" });
  await import(`${monitoringOutput}?run=${Date.now()}`);
  await build({ entryPoints: ["tests/workspace-smoke.ts"], outfile: workspaceOutput, bundle: true, platform: "node", format: "esm", packages: "external" });
  await import(`${workspaceOutput}?run=${Date.now()}`);
  await build({ entryPoints: ["src/lib/server/orchestrator.ts"], outfile: peerOutput, bundle: true, platform: "node", format: "esm", packages: "external" });
  await build({ entryPoints: ["tests/orchestrator-smoke.ts"], outfile: output, bundle: true, platform: "node", format: "esm", packages: "external" });
  await import(`${output}?run=${Date.now()}`);
  await build({ entryPoints: ["tests/features-smoke.ts"], outfile: featuresOutput, bundle: true, platform: "node", format: "esm", packages: "external" });
  await import(`${featuresOutput}?run=${Date.now()}`);
  await build({ entryPoints: ["tests/model-config-smoke.ts"], outfile: modelConfigOutput, bundle: true, platform: "node", format: "esm", packages: "external" });
  await import(`${modelConfigOutput}?run=${Date.now()}`);
  await build({ entryPoints: ["tests/model-limits-smoke.ts"], outfile: modelLimitsOutput, bundle: true, platform: "node", format: "esm", packages: "external", loader: { ".md": "text" } });
  await import(`${modelLimitsOutput}?run=${Date.now()}`);
  await build({ entryPoints: ["tests/assistant-smoke.ts"], outfile: assistantOutput, bundle: true, platform: "node", format: "esm", packages: "external", loader: { ".md": "text" } });
  await import(`${assistantOutput}?run=${Date.now()}`);
  await build({ entryPoints: ["tests/assistant-budget-smoke.ts"], outfile: budgetOutput, bundle: true, platform: "node", format: "esm", packages: "external", loader: { ".md": "text" } });
  await import(`${budgetOutput}?run=${Date.now()}`);
  await build({ entryPoints: ["tests/shutdown-worker.ts"], outfile: shutdownOutput, bundle: true, platform: "node", format: "esm", packages: "external", loader: { ".md": "text" } });
  await testShutdown(shutdownOutput);
} finally {
  await Promise.all([
    rm(`${prefix}.sqlite`, { force: true }),
    rm(`${prefix}.sqlite-shm`, { force: true }),
    rm(`${prefix}.sqlite-wal`, { force: true }),
    rm(`${prefix}-executions`, { force: true, recursive: true }),
    rm(`${prefix}-workspaces`, { force: true, recursive: true }),
    rm(output, { force: true }),
    rm(peerOutput, { force: true }),
    rm(assistantOutput, { force: true }),
    rm(budgetOutput, { force: true }),
    rm(workspaceOutput, { force: true }),
    rm(shutdownOutput, { force: true }),
    rm(featuresOutput, { force: true }),
    rm(modelConfigOutput, { force: true }),
    rm(modelLimitsOutput, { force: true }),
    rm(projectModelOutput, { force: true }),
    rm(monitoringOutput, { force: true }),
  ]);
}
