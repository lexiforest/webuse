import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdtemp, mkdir, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { setTimeout as delay } from "node:timers/promises";

export async function testShutdown(entrypoint) {
  if (process.platform === "win32") return;
  for (const signal of ["SIGINT", "SIGTERM"]) {
    const directory = await mkdtemp(join(tmpdir(), "webuse-shutdown-"));
    const runs = join(directory, "runs");
    await mkdir(runs);
    const manager = spawn(process.execPath, [entrypoint], {
      env: { ...process.env, WEBUSE_DB_PATH: join(directory, "db.sqlite"), WEBUSE_WORK_DIR: runs, WEBUSE_WORKSPACE_DIR: join(directory, "workspaces"), WEBUSE_CONCURRENCY: "1" },
      stdio: ["ignore", "pipe", "pipe", "ipc"],
    });
    let output = "", pids;
    manager.stdout.on("data", chunk => output += chunk);
    manager.stderr.on("data", chunk => output += chunk);
    const exited = new Promise(resolve => manager.once("exit", (code, receivedSignal) => resolve({ code, signal: receivedSignal })));
    const timeout = setTimeout(() => manager.kill("SIGKILL"), 15_000);
    try {
      pids = await new Promise((resolve, reject) => {
        manager.once("message", resolve);
        manager.once("error", reject);
        manager.once("exit", () => reject(new Error(`Manager exited before starting workers: ${output}`)));
      });
      manager.kill(signal);
      assert.deepEqual(await exited, { code: 0, signal: null }, output);
      assert.equal(await readFile(join(runs, "stopped"), "utf8"), "clean");
      const signals = await readFile(join(runs, "signals"), "utf8");
      assert.ok(signals.includes(`worker:${signal}`), signals);
      assert.ok(signals.includes(`descendant:${signal}`), signals);
      for (const pid of Object.values(pids)) {
        let alive = true;
        for (let tries = 0; tries < 100 && alive; tries++) {
          try { process.kill(pid, 0); await delay(25); }
          catch (error) { assert.equal(error.code, "ESRCH"); alive = false; }
        }
        assert.equal(alive, false, `Worker ${pid} survived manager shutdown`);
      }
    } finally {
      clearTimeout(timeout);
      if (pids) { try { process.kill(-pids.worker, "SIGKILL"); } catch {} }
      if (manager.exitCode === null && manager.signalCode === null) manager.kill("SIGKILL");
      await exited;
      await rm(directory, { recursive: true, force: true });
    }
  }
  console.log("Shutdown passed: SIGINT/SIGTERM forwarding, descendant escalation, awaited cleanup, and no new work during shutdown.");
}
