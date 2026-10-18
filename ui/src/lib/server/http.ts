import type { APIEvent } from "@solidjs/start/server";
import { validFilePath } from "./workspace";
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
    if (typeof path !== "string" || typeof content !== "string" || !validFilePath(path) || seen.has(path)) return undefined;
    seen.add(path); files.push({ path, content });
  }
  return files;
}
export function projectInput(value: Record<string, unknown> | undefined): { input?: ProjectInput; error?: string } {
  if (!value || typeof value.name !== "string" || !value.name.trim()) return { error: "Project name is required." };
  if ("type" in value) return { error: "Project type is no longer supported. Provide project files and a crawl command instead." };
  if (typeof value.target !== "string" || !value.target.trim()) return { error: "Project target is required." };
  const cron = typeof value.cron === "string" ? value.cron.trim() : "";
  if (value.crawlCommand !== undefined && (typeof value.crawlCommand !== "string" || value.crawlCommand.length > 16_000 || value.crawlCommand.includes("\0"))) return { error: "Crawl command must be text under 16,000 characters without null bytes." };
  const crawlCommand = typeof value.crawlCommand === "string" ? value.crawlCommand.trim() : "";
  if (cron && !validCron(cron)) return { error: "Project cron must be a valid five-field cron expression." };
  if (!Array.isArray(value.files)) return { error: "Project files must be an array." };
  const files = projectFiles(value.files);
  if (!files) return { error: "Project files contain an invalid or duplicate path." };
  return { input: { name: value.name.trim(), target: value.target.trim(), cron, crawlCommand, config: value.config && typeof value.config === "object" && !Array.isArray(value.config) ? value.config as Record<string, unknown> : undefined, files, revision: typeof value.revision === "string" ? value.revision : undefined } };
}
