import type { APIEvent } from "@solidjs/start/server";
import { isAbsolute, normalize, sep } from "node:path";
import { validCron } from "./cron";
import type { ProjectFile, ProjectInput } from "./store";

export function json(value: unknown, status = 200) {
  return new Response(JSON.stringify(value), { status, headers: { "content-type": "application/json", "cache-control": "no-store" } });
}
export function queryInt(event: APIEvent, name: string) {
  const raw = new URL(event.request.url).searchParams.get(name); const value = Number(raw);
  return raw && Number.isInteger(value) && value > 0 ? value : undefined;
}
export async function body(event: APIEvent) { try { return await event.request.json() as Record<string, unknown>; } catch { return undefined; } }
export function projectFiles(value: unknown): ProjectFile[] | undefined {
  if (!Array.isArray(value)) return [];
  const seen = new Set<string>(); const files: ProjectFile[] = [];
  for (const entry of value) {
    if (!entry || typeof entry !== "object") return undefined;
    const { path, content } = entry as Record<string, unknown>;
    if (typeof path !== "string" || typeof content !== "string" || !path || isAbsolute(path)) return undefined;
    const clean = normalize(path);
    if (clean === ".." || clean.startsWith(`..${sep}`) || seen.has(clean)) return undefined;
    seen.add(clean); files.push({ path: clean, content });
  }
  return files;
}
export function projectInput(value: Record<string, unknown> | undefined): { input?: ProjectInput; error?: string } {
  if (!value || typeof value.name !== "string" || !value.name.trim()) return { error: "Project name is required." };
  if (!(value.type === "yaml" || value.type === "python" || value.type === "git")) return { error: "Project type must be yaml, python, or git." };
  if (typeof value.target !== "string" || !value.target.trim()) return { error: "Project target is required." };
  const cron = typeof value.cron === "string" ? value.cron.trim() : "";
  if (cron && !validCron(cron)) return { error: "Project cron must be a valid five-field cron expression." };
  const files = projectFiles(value.files);
  if (!files) return { error: "Project files contain an invalid or duplicate path." };
  if (value.type !== "git" && files.length === 0) return { error: "A local project must contain at least one file." };
  return { input: { name: value.name.trim(), type: value.type, target: value.target.trim(), cron, config: value.config && typeof value.config === "object" && !Array.isArray(value.config) ? value.config as Record<string, unknown> : undefined, files } };
}
