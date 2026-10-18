import { spawn } from "node:child_process";
import { pythonCommand } from "./python";

export function pythonJson<T>(module: string, value: unknown, signal?: AbortSignal): Promise<T> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) { reject(new Error("Request cancelled.")); return; }
    const child = spawn(pythonCommand(), ["-m", module], { stdio: ["pipe", "pipe", "pipe"] });
    let output = "";
    let failure: string | undefined;
    const stop = (message: string) => { failure = message; child.kill("SIGKILL"); };
    const abort = () => stop("Request cancelled.");
    const timer = setTimeout(() => stop("Monitoring request timed out."), 15_000);
    signal?.addEventListener("abort", abort, { once: true });
    const cleanup = () => { clearTimeout(timer); signal?.removeEventListener("abort", abort); };
    child.stdout.on("data", chunk => { output += chunk; if (output.length > 4_000_000) stop("Monitoring response is too large. Select a shorter interval."); });
    child.stderr.resume();
    child.stdin.on("error", () => {});
    child.on("error", () => { cleanup(); reject(new Error("Cannot start the configured Python interpreter.")); });
    child.on("close", code => {
      cleanup();
      if (failure || code !== 0) { reject(new Error(failure || "Monitoring adapter failed. Check the configured Python environment.")); return; }
      try { resolve(JSON.parse(output) as T); } catch { reject(new Error("Invalid monitoring adapter response.")); }
    });
    child.stdin.end(JSON.stringify(value));
  });
}
