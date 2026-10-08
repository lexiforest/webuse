import { effectiveSettings } from "./settings";
import type { ProjectFile } from "./store";
import { isAbsolute, normalize, sep } from "node:path";

type Message = { role: string; content: string };

function parseResult(content: string, files: ProjectFile[], selectedPath?: string) {
  const candidate = content.replace(/^```(?:json)?\s*/i, "").replace(/\s*```$/, "");
  try {
    const value = JSON.parse(candidate) as { content?: unknown; files?: unknown; selectedPath?: unknown };
    const resultFiles = Array.isArray(value.files) ? value.files.filter(file => {
      if (!file || typeof file.path !== "string" || typeof file.content !== "string" || isAbsolute(file.path)) return false;
      const path = normalize(file.path); return path !== ".." && !path.startsWith(`..${sep}`);
    }) as ProjectFile[] : files;
    const changedFiles = resultFiles.filter(file => files.find(old => old.path === file.path)?.content !== file.content || !files.some(old => old.path === file.path)).map(file => file.path);
    return { content: typeof value.content === "string" ? value.content : "Project files updated.", files: resultFiles, selectedPath: typeof value.selectedPath === "string" ? value.selectedPath : selectedPath, changedFiles };
  } catch {
    return { content, files, selectedPath, changedFiles: [] as string[] };
  }
}

export async function runAssistant(files: ProjectFile[], selectedPath: string | undefined, history: Message[], userMessage: string) {
  const settings = effectiveSettings().llm;
  if (!settings.apiKey && settings.baseUrl === "https://api.openai.com/v1") throw new Error("Configure an LLM API key in Settings first.");
  const system = `You edit webuse crawler projects. Return only one JSON object with keys content, files, and selectedPath. content is a short Markdown explanation. files is the complete array of {path, content} project files after your edits. Preserve files that do not need changes. Never use absolute paths or paths containing '..'. Current files:\n${JSON.stringify(files)}`;
  const messages = [
    { role: "system", content: system },
    ...history.slice(-12).map(message => ({ role: message.role, content: message.content })),
    { role: "user", content: userMessage },
  ];
  const response = await fetch(`${settings.baseUrl.replace(/\/$/, "")}/chat/completions`, {
    method: "POST",
    headers: { "content-type": "application/json", ...(settings.apiKey ? { authorization: `Bearer ${settings.apiKey}` } : {}) },
    body: JSON.stringify({ model: settings.model, messages, temperature: 0 }),
  });
  if (!response.ok) throw new Error(`LLM request failed (${response.status}): ${(await response.text()).slice(0, 500)}`);
  const payload = await response.json() as { choices?: { message?: { content?: string } }[] };
  const content = payload.choices?.[0]?.message?.content;
  if (!content) throw new Error("LLM response did not contain a message.");
  return parseResult(content, files, selectedPath);
}
