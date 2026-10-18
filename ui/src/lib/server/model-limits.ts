export type LimitOverrides = { contextWindow?: string; maxOutputTokens?: string };
export type ServingLimits = { contextWindow?: number; maxOutputTokens?: number; source?: string; local?: boolean };
type CatalogEntry = { ids: string[]; contextWindow: number; maxOutputTokens?: number; source: string; servingRequired?: boolean };

// Reviewed 2026-10-18. Exact IDs only: aliases, quantizations and gateway names
// must not inherit limits from a guessed family prefix. Sources travel with data.
export const modelCatalog: CatalogEntry[] = [
  { ids: ["gpt-6.1-sol"], contextWindow: 1_050_000, maxOutputTokens: 128_000, source: "https://developers.openai.com/api/docs/models/gpt-6.1-sol" },
  { ids: ["gpt-5.4", "gpt-5.4-2026-03-05"], contextWindow: 1_050_000, maxOutputTokens: 128_000, source: "https://developers.openai.com/api/docs/models/gpt-5.4" },
  { ids: ["gpt-5.2"], contextWindow: 400_000, maxOutputTokens: 128_000, source: "https://developers.openai.com/api/docs/models/gpt-5.2" },
  { ids: ["gpt-5-mini", "gpt-5-mini-2025-08-07"], contextWindow: 400_000, maxOutputTokens: 128_000, source: "https://developers.openai.com/api/docs/models/gpt-5-mini" },
  { ids: ["gpt-4.1"], contextWindow: 1_047_576, maxOutputTokens: 32_768, source: "https://developers.openai.com/api/docs/models/gpt-4.1" },
  { ids: ["gpt-4.1-mini"], contextWindow: 1_047_576, maxOutputTokens: 32_768, source: "https://developers.openai.com/api/docs/models/gpt-4.1-mini" },
  { ids: ["gpt-4o"], contextWindow: 128_000, maxOutputTokens: 16_384, source: "https://developers.openai.com/api/docs/models/gpt-4o" },
  // Providers publish these as 1M / 384K and 1M / 128K. Use decimal
  // counts conservatively where the provider does not specify exact integers.
  { ids: ["deepseek-flash", "deepseek-v4-pro", "deepseek-v4-flash", "deepseek-v4-flash-vision-exp"], contextWindow: 1_000_000, maxOutputTokens: 384_000, source: "https://api-docs.deepseek.com/quick_start/pricing/" },
  { ids: ["claude-fable-5-1", "claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"], contextWindow: 1_000_000, maxOutputTokens: 128_000, source: "https://platform.claude.com/docs/en/models/overview" },
  { ids: ["claude-sonnet-4-6"], contextWindow: 1_000_000, maxOutputTokens: 128_000, source: "https://platform.claude.com/docs/en/models/sonnet-4-6/overview" },
  { ids: ["claude-opus-4-6"], contextWindow: 1_000_000, maxOutputTokens: 128_000, source: "https://platform.claude.com/docs/en/models/opus-4-6/overview" },
  // Gemini publishes an input limit separately. Using it as Pi's combined
  // budget is conservative: output is reserved inside that input limit.
  { ids: ["gemini-2.5-pro"], contextWindow: 1_048_576, maxOutputTokens: 65_536, source: "https://ai.google.dev/gemini-api/docs/models/gemini-2.5-pro" },
  { ids: ["gemini-2.5-flash"], contextWindow: 1_048_576, maxOutputTokens: 65_536, source: "https://ai.google.dev/gemini-api/docs/models/gemini-2.5-flash" },
  { ids: ["Qwen/Qwen3-Coder-30B-A3B-Instruct"], contextWindow: 262_144, servingRequired: true, source: "https://huggingface.co/Qwen/Qwen3-Coder-30B-A3B-Instruct" },
];

export function optionalTokens(value: unknown, label: string): string {
  if (value === undefined || value === "") return "";
  const number = typeof value === "string" || typeof value === "number" ? Number(value) : NaN;
  if (!Number.isSafeInteger(number) || number <= 0) throw new Error(`${label} must be a positive integer, or blank for automatic detection.`);
  return String(number);
}

function positive(value: unknown): number | undefined {
  return typeof value === "number" && Number.isSafeInteger(value) && value > 0 ? value : undefined;
}

export function resolveModelLimits(settings: LimitOverrides & { model: string; baseUrl: string }, live: ServingLimits = {}) {
  const catalog = modelCatalog.find(entry => entry.ids.includes(settings.model));
  let local = live.local;
  try {
    const url = new URL(settings.baseUrl);
    local ||= ["localhost", "127.0.0.1", "[::1]", "host.docker.internal"].includes(url.hostname) || ["1234", "11434"].includes(url.port);
  } catch { /* No endpoint selected. */ }
  const known = !local && !catalog?.servingRequired ? catalog : undefined;
  const explicitContext = Number(optionalTokens(settings.contextWindow, "Context window")) || undefined;
  const explicitOutput = Number(optionalTokens(settings.maxOutputTokens, "Maximum output tokens")) || undefined;
  const contextWindow = explicitContext ?? positive(live.contextWindow) ?? known?.contextWindow;
  const maxOutputTokens = explicitOutput ?? positive(live.maxOutputTokens) ?? known?.maxOutputTokens;
  return {
    contextWindow, maxOutputTokens,
    contextSource: explicitContext ? "configured" : positive(live.contextWindow) ? live.source || "endpoint" : known ? "catalog" : "unknown",
    outputSource: explicitOutput ? "configured" : positive(live.maxOutputTokens) ? live.source || "endpoint" : known?.maxOutputTokens ? "catalog" : "unknown",
    catalogSource: catalog?.source,
    advertisedContextWindow: catalog?.contextWindow,
    // A request budget is an application default, not an invented model limit.
    responseTokens: contextWindow ? Math.min(explicitOutput ?? 32_768, maxOutputTokens ?? 8192, Math.floor(contextWindow / 4)) : undefined,
  };
}

export function contextBudgets(limits: ReturnType<typeof resolveModelLimits>) {
  if (!limits.contextWindow || !limits.responseTokens) throw new Error("Model context window is unknown. Set Context window in Settings → Model, or llm.context_window in .webuserc.yaml.");
  const contextWindow = limits.contextWindow;
  const responseTokens = limits.responseTokens;
  const reserveTokens = responseTokens + 4096 + Math.min(16_384, Math.floor(contextWindow / 8));
  if (reserveTokens >= contextWindow) throw new Error("The loaded context window is too small for Harness. Increase the model server's context allocation and refresh Model settings.");
  return {
    contextWindow, responseTokens,
    maxTokens: limits.maxOutputTokens ?? responseTokens,
    summaryTokens: Math.min(8192, Math.floor(contextWindow / 16), limits.maxOutputTokens ?? 8192),
    compaction: { enabled: true, reserveTokens, keepRecentTokens: Math.min(20_000, Math.floor((contextWindow - reserveTokens) / 4)) },
  };
}
