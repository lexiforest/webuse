import { existsSync } from "node:fs";
import { resolve } from "node:path";

export function pythonCommand() {
  if (process.env.WEBUSE_PYTHON_COMMAND) return process.env.WEBUSE_PYTHON_COMMAND;
  const candidates = process.platform === "win32"
    ? [resolve("../.venv/Scripts/python.exe"), resolve(".venv/Scripts/python.exe")]
    : [resolve("../.venv/bin/python"), resolve(".venv/bin/python")];
  return candidates.find(existsSync) || (process.platform === "win32" ? "python" : "python3");
}
