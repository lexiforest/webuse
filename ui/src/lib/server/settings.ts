import { resolve } from "node:path";
import { store } from "./store";
import { optionalTokens, type LimitOverrides } from "./model-limits";
import { prometheusUrl } from "../monitoring";

export type SettingsValue = {
  runtime: { databasePath: string; workDirectory: string; concurrency: string };
  llm: { apiKey: string; baseUrl: string; model: string } & LimitOverrides;
  harness: { maxToolCalls: string; turnTimeoutSeconds: string };
  monitoring: { prometheusUrl: string };
};

export const defaults: SettingsValue = {
  runtime: {
    databasePath: store.databasePath,
    workDirectory: resolve(process.env.WEBUSE_WORK_DIR || "./executions"),
    concurrency: process.env.WEBUSE_CONCURRENCY || "1",
  },
  llm: {
    apiKey: process.env.WEBUSE_LLM_API_KEY || process.env.OPENAI_API_KEY || "",
    baseUrl: process.env.WEBUSE_LLM_BASE_URL || process.env.OPENAI_BASE_URL || "",
    model: process.env.WEBUSE_LLM_MODEL || process.env.OPENAI_MODEL || "",
  },
  harness: { maxToolCalls: "", turnTimeoutSeconds: "" },
  monitoring: { prometheusUrl: "" },
};

function section(value: unknown) { return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {}; }
function text(value: unknown) { return typeof value === "string" ? value : ""; }
function optionalLimit(value: unknown, label: string, maximum = Number.MAX_SAFE_INTEGER) {
  if (value === undefined || value === "") return "";
  const number = typeof value === "string" || typeof value === "number" ? Number(value) : NaN;
  if (!Number.isSafeInteger(number) || number < 0 || number > maximum) throw new Error(`${label} must be a nonnegative integer no greater than ${maximum}, or blank for unlimited.`);
  return number ? String(number) : "";
}

export function normalizedSettings(value: unknown): SettingsValue {
  const root = section(value); const runtime = section(root.runtime); const llm = section(root.llm); const harness = section(root.harness);
  return {
    runtime: { databasePath: text(runtime.databasePath), workDirectory: text(runtime.workDirectory), concurrency: text(runtime.concurrency) },
    llm: { apiKey: text(llm.apiKey), baseUrl: text(llm.baseUrl), model: text(llm.model), contextWindow: optionalTokens(llm.contextWindow, "Context window"), maxOutputTokens: optionalTokens(llm.maxOutputTokens, "Maximum output tokens") },
    harness: { maxToolCalls: optionalLimit(harness.maxToolCalls, "Tool limit"), turnTimeoutSeconds: optionalLimit(harness.turnTimeoutSeconds, "Turn time limit", 2_147_483) },
    monitoring: { prometheusUrl: prometheusUrl(section(root.monitoring).prometheusUrl) },
  };
}

export function savedSettings() { return normalizedSettings(store.getSettings()); }
export function harnessLimits() {
  const settings = savedSettings().harness;
  return { maxToolCalls: Number(settings.maxToolCalls), turnTimeoutSeconds: Number(settings.turnTimeoutSeconds) };
}
export function hasModelSettings(llm: SettingsValue["llm"]) { return !!(llm.baseUrl || llm.model || llm.apiKey); }
export function modelDefaults(llm: SettingsValue["llm"]) {
  return {
    apiKey: llm.apiKey,
    baseUrl: llm.baseUrl || (llm.apiKey ? "https://api.openai.com/v1" : ""),
    model: llm.model || (llm.apiKey && !llm.baseUrl ? "gpt-4.1-mini" : ""),
    contextWindow: llm.contextWindow || "",
    maxOutputTokens: llm.maxOutputTokens || "",
  };
}
export function effectiveSettings() {
  const saved = savedSettings();
  const llm = hasModelSettings(saved.llm) ? saved.llm : defaults.llm;
  return {
    runtime: {
      databasePath: defaults.runtime.databasePath,
      workDirectory: saved.runtime.workDirectory || defaults.runtime.workDirectory,
      concurrency: saved.runtime.concurrency || defaults.runtime.concurrency,
    },
    llm: modelDefaults(llm),
    harness: saved.harness,
    monitoring: saved.monitoring,
  };
}
