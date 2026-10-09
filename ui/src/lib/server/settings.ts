import { resolve } from "node:path";
import { store } from "./store";

export type SettingsValue = {
  runtime: { databasePath: string; workDirectory: string; concurrency: string };
  llm: { apiKey: string; baseUrl: string; model: string };
  smart: { selectorStore: string };
};

export const defaults: SettingsValue = {
  runtime: {
    databasePath: store.databasePath,
    workDirectory: resolve(process.env.WEBUSE_WORK_DIR || "./runs"),
    concurrency: process.env.WEBUSE_CONCURRENCY || "1",
  },
  llm: {
    apiKey: process.env.WEBUSE_LLM_API_KEY || process.env.OPENAI_API_KEY || "",
    baseUrl: process.env.WEBUSE_LLM_BASE_URL || process.env.OPENAI_BASE_URL || "https://api.openai.com/v1",
    model: process.env.WEBUSE_LLM_MODEL || process.env.OPENAI_MODEL || "gpt-4.1-mini",
  },
  smart: { selectorStore: process.env.WEBUSE_SELECTOR_STORE || ".webuse/selectors.json" },
};

function section(value: unknown) { return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {}; }
function text(value: unknown) { return typeof value === "string" ? value : ""; }

export function normalizedSettings(value: unknown): SettingsValue {
  const root = section(value); const runtime = section(root.runtime); const llm = section(root.llm); const smart = section(root.smart);
  return {
    runtime: { databasePath: text(runtime.databasePath), workDirectory: text(runtime.workDirectory), concurrency: text(runtime.concurrency) },
    llm: { apiKey: text(llm.apiKey), baseUrl: text(llm.baseUrl), model: text(llm.model) },
    smart: { selectorStore: text(smart.selectorStore) },
  };
}

export function savedSettings() { return normalizedSettings(store.getSettings()); }
export function effectiveSettings() {
  const saved = savedSettings();
  return {
    runtime: {
      databasePath: defaults.runtime.databasePath,
      workDirectory: saved.runtime.workDirectory || defaults.runtime.workDirectory,
      concurrency: saved.runtime.concurrency || defaults.runtime.concurrency,
    },
    llm: {
      apiKey: saved.llm.apiKey || defaults.llm.apiKey,
      baseUrl: saved.llm.baseUrl || defaults.llm.baseUrl,
      model: saved.llm.model || defaults.llm.model,
    },
    smart: { selectorStore: saved.smart.selectorStore || defaults.smart.selectorStore },
  };
}

export function settingsPayload() {
  return { settings: savedSettings(), effectiveSettings: effectiveSettings(), paths: { local: store.databasePath, user: "" } };
}
