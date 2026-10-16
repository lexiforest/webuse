import { createHash, randomUUID } from "node:crypto";
import { chmodSync, existsSync, lstatSync, mkdirSync, readdirSync, readFileSync, renameSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { spawn } from "node:child_process";
import { databasePath } from "./db";
import { runtime } from "./runtime";

export type ProjectFile = { path: string; content: string };
type Entry = { path: string; hash: string; mode: number; size: number };
export const workspaceRoot = resolve(process.env.WEBUSE_WORKSPACE_DIR || join(dirname(databasePath), "workspaces"));
const omittedNames = new Set([".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache", ".DS_Store"]);
const locks = runtime.workspaceLocks;
const hash = (value: string | Buffer) => createHash("sha256").update(value).digest("hex");

export class WorkspaceConflict extends Error {}
export function assertWorkspaceIdle(id: number) {
  if (locks.has(id)) throw new WorkspaceConflict("This project's workspace is busy. Wait for the assistant or import to finish.");
}
export function lockWorkspace(id: number) {
  assertWorkspaceIdle(id); locks.add(id);
  return () => locks.delete(id);
}
export function projectDirectory(id: number) { return join(workspaceRoot, String(id), "working"); }
export function includedPath(path: string) {
  return !path.split("/").some(part => omittedNames.has(part) || part === ".env" || (part.startsWith(".env.") && part !== ".env.example"))
    && path !== ".webuse/selectors.json";
}
export function validFilePath(path: string) {
  return !!path && !path.includes("\\") && !path.includes(":") && !path.includes("\0")
    && path.split("/").every(part => !!part && part !== "." && part !== "..") && includedPath(path);
}
function safePath(root: string, path: string) {
  if (!validFilePath(path)) throw new Error(`Invalid or excluded project path: ${path}`);
  if (lstatSync(root).isSymbolicLink()) throw new Error("Workspace root must not be a symlink.");
  let target = root;
  const parts = path.split("/");
  for (const [index, part] of parts.entries()) {
    target = join(target, part);
    try {
      const stat = lstatSync(target);
      if (stat.isSymbolicLink()) throw new Error(`Symlinks are not supported in project files: ${path}`);
      if (index < parts.length - 1 && !stat.isDirectory()) throw new Error(`File conflicts with a directory: ${path}`);
    }
    catch (error) { if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error; }
  }
  return target;
}
function entries(root: string): Entry[] {
  if (lstatSync(root).isSymbolicLink()) throw new Error("Workspace root must not be a symlink.");
  const result: Entry[] = [];
  let bytes = 0;
  function visit(relative: string) {
    for (const name of readdirSync(join(root, relative)).sort()) {
      const path = relative ? `${relative}/${name}` : name;
      if (!includedPath(path)) continue;
      const full = safePath(root, path);
      const stat = lstatSync(full);
      if (stat.isDirectory()) { visit(path); continue; }
      if (!stat.isFile()) throw new Error(`Unsupported project file: ${path}`);
      bytes += stat.size;
      if (bytes > 100_000_000 || result.length >= 10_000) throw new Error("Workspace editor supports up to 100 MB and 10,000 files, excluding environments, caches, and .git.");
      result.push({ path, hash: hash(readFileSync(full)), mode: stat.mode & 0o777, size: stat.size });
    }
  }
  visit("");
  return result;
}
function revisionOf(files: Entry[]) { return hash(JSON.stringify(files)); }
function textFile(root: string, entry: Entry): string | undefined {
  if (entry.size > 256_000) return undefined;
  const data = readFileSync(safePath(root, entry.path));
  if (data.includes(0)) return undefined;
  try { return new TextDecoder("utf-8", { fatal: true }).decode(data); } catch { return undefined; }
}
export function readWorkspace(root: string) {
  const manifest = entries(root);
  const files: ProjectFile[] = [];
  const omitted: string[] = [];
  let bytes = 0;
  for (const entry of manifest) {
    const content = textFile(root, entry);
    if (content === undefined || bytes + entry.size > 2_000_000 || files.length >= 100) { omitted.push(entry.path); continue; }
    bytes += entry.size;
    files.push({ path: entry.path, content });
  }
  return { files, omitted, revision: revisionOf(manifest) };
}
export function checkRevision(root: string, expected: string | undefined) {
  if (!expected || revisionOf(entries(root)) !== expected) throw new WorkspaceConflict("Workspace changed on disk. Reload files and review your edits before saving again.");
}
export function writeWorkspace(root: string, files: ProjectFile[], expected: string) {
  checkRevision(root, expected);
  const current = readWorkspace(root);
  if (current.revision !== expected) throw new WorkspaceConflict("Workspace changed during save. Reload before trying again.");
  const editable = new Set(current.files.map(file => file.path));
  const seen = new Set<string>();
  let bytes = 0;
  for (const file of files) {
    safePath(root, file.path);
    if (seen.has(file.path)) throw new Error(`Duplicate project path: ${file.path}`);
    if (current.omitted.includes(file.path)) throw new Error(`Edit this file with a local editor: ${file.path}`);
    seen.add(file.path);
    bytes += Buffer.byteLength(file.content);
    if (Buffer.byteLength(file.content) > 256_000 || bytes > 2_000_000 || files.length > 100) throw new Error("Editor supports 100 text files, 256 KB per file and 2 MB total. Use a local editor for larger files.");
  }
  for (const path of seen) {
    if ([...seen].some(other => other.startsWith(`${path}/`))) throw new Error(`File conflicts with a directory: ${path}`);
    const full = safePath(root, path);
    if (existsSync(full) && lstatSync(full).isDirectory()) throw new Error(`Path is a directory: ${path}`);
  }
  // Preserve binary/large files and excluded directories absent from the editor view.
  for (const file of files) {
    if (current.files.find(previous => previous.path === file.path)?.content === file.content) continue;
    const target = safePath(root, file.path);
    mkdirSync(dirname(target), { recursive: true });
    const temporary = join(dirname(target), `.webuse-write-${randomUUID()}`);
    try {
      writeFileSync(temporary, file.content, { mode: existsSync(target) ? lstatSync(target).mode & 0o777 : 0o644 });
      if (existsSync(target)) chmodSync(temporary, lstatSync(target).mode & 0o777);
      renameSync(temporary, target);
    } finally { rmSync(temporary, { force: true }); }
  }
  for (const path of editable) if (!seen.has(path)) rmSync(safePath(root, path));
  return readWorkspace(root);
}
export function initializeWorkspace(id: number, files: ProjectFile[]) {
  const root = projectDirectory(id);
  mkdirSync(dirname(root), { recursive: true });
  mkdirSync(root);
  try { writeWorkspace(root, files, readWorkspace(root).revision); }
  catch (error) { rmSync(root, { recursive: true, force: true }); throw error; }
  return root;
}
export async function cloneWorkspace(id: number, url: string) {
  const release = lockWorkspace(id);
  const root = projectDirectory(id);
  try {
    await new Promise<void>((resolvePromise, reject) => {
      const child = spawn("git", ["clone", "--", url, root], { env: { ...process.env, GIT_TERMINAL_PROMPT: "0" }, stdio: ["ignore", "ignore", "pipe"] });
      let error = "";
      child.stderr.on("data", data => { error = (error + String(data)).slice(-4000); });
      const timeout = setTimeout(() => child.kill("SIGKILL"), 120_000);
      child.once("error", cause => { clearTimeout(timeout); reject(cause); });
      child.once("close", code => { clearTimeout(timeout); code === 0 ? resolvePromise() : reject(new Error(error || "Git clone failed.")); });
    });
  } finally { release(); }
}
