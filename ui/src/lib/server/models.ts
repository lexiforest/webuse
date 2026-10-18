import { spawn } from "node:child_process";
import { pythonCommand } from "./python";
import { effectiveSettings, hasModelSettings, modelDefaults, savedSettings } from "./settings";
import { optionalTokens, resolveModelLimits, type LimitOverrides, type ServingLimits } from "./model-limits";
import { monitoringConnection } from "./monitoring";

export type ModelChoice = { model: string; baseUrl: string; provider: string };
type LlmSettings = { model: string; baseUrl: string; apiKey: string } & LimitOverrides;
type Probe = { localModels: ModelChoice[]; models: string[]; configured: LlmSettings; limits?: ServingLimits; error?: string; configError?: boolean };

// Keep HTTP and local-provider discovery in Python/curl_cffi. Credentials go over
// stdin, never command arguments, logs, or the public status response.
const script = `import json, os, sys
from pathlib import Path
from webuse.config import load_webuse_config
from webuse.llm import discover_local_openai_settings, openai_model_ids
from webuse.model_metadata import serving_model_limits
settings = json.load(sys.stdin)
if settings.pop("useConfig"):
    try:
        config = load_webuse_config(directory=Path(os.environ.get("WEBUSE_CONFIG_DIR") or os.getcwd())).get("llm") or {}
        settings = {key: config.get(field) or "" for key, field in {"model": "model", "baseUrl": "base_url", "apiKey": "api_key"}.items()}
        if not all(isinstance(value, str) for value in settings.values()):
            raise ValueError("Model settings must be strings")
        for key, field in {"contextWindow": "context_window", "maxOutputTokens": "max_output_tokens"}.items():
            value = config.get(field, "")
            if value != "" and (isinstance(value, bool) or not str(value).isdigit() or int(value) <= 0):
                raise ValueError("Model limits must be positive integers")
            settings[key] = str(value)
        if settings["apiKey"] and not settings["baseUrl"]:
            settings["baseUrl"] = "https://api.openai.com/v1"
            settings["model"] = settings["model"] or "gpt-4.1-mini"
    except Exception:
        print(json.dumps({"localModels": [], "models": [], "configured": {}, "configError": True, "error": "Cannot read Webuse model configuration. Check .webuserc.yaml and the user config file."}))
        sys.exit(0)
local = discover_local_openai_settings(timeout=0.5)
result = {"localModels": [{"model": s.model, "baseUrl": s.base_url, "provider": s.provider} for s in local], "models": [], "configured": settings}
if settings.get("baseUrl"):
    try:
        result["models"] = openai_model_ids(settings["baseUrl"], settings.get("apiKey", ""))
    except Exception:
        result["error"] = "Cannot list models at the configured endpoint. Check the URL, credentials, and server."
selected = settings if any(settings.get(key) for key in ("baseUrl", "model", "apiKey")) else ({"model": local[0].model, "baseUrl": local[0].base_url} if local else {})
if selected.get("baseUrl") and selected.get("model"):
    provider = next((s.provider for s in local if s.base_url == selected["baseUrl"] and s.model == selected["model"]), "")
    result["limits"] = serving_model_limits(selected["baseUrl"], selected["model"], selected.get("apiKey", ""), provider=provider)
print(json.dumps(result))
`;

let cached: { key: string; expires: number; promise: Promise<Probe> } | undefined;
export function clearModelCache() { cached = undefined; }

function probe(settings: LlmSettings): Promise<Probe> {
  const useConfig = !hasModelSettings(savedSettings().llm);
  const key = JSON.stringify([settings, useConfig, pythonCommand(), process.env.WEBUSE_LOCAL_MODEL_HOST, process.env.WEBUSE_CONFIG_DIR || process.cwd()]);
  if (cached?.key === key && cached.expires > Date.now()) return cached.promise;
  const promise = new Promise<Probe>(resolve => {
    const child = spawn(pythonCommand(), ["-c", script], { stdio: ["pipe", "pipe", "pipe"] });
    let output = "";
    const timeout = setTimeout(() => child.kill("SIGKILL"), 8000);
    const failed = () => ({ localModels: [], models: [], configured: settings, error: "Model discovery failed. Check the configured Python environment." });
    child.stdout.on("data", chunk => {
      output += chunk.toString();
      if (output.length > 1_000_000) child.kill("SIGKILL");
    });
    child.stderr.resume();
    child.stdin.on("error", () => {});
    child.on("error", () => { clearTimeout(timeout); resolve(failed()); });
    child.on("close", code => {
      clearTimeout(timeout);
      try { resolve(code === 0 ? JSON.parse(output) as Probe : failed()); }
      catch { resolve(failed()); }
    });
    child.stdin.end(JSON.stringify({ ...settings, useConfig }));
  });
  cached = { key, expires: Date.now() + 10_000, promise };
  return promise;
}

export async function resolvedLlm(): Promise<LlmSettings> {
  const settings = effectiveSettings().llm;
  if (hasModelSettings(savedSettings().llm)) return settings;
  const result = await probe(settings);
  if (result.configError) throw new Error(result.error);
  if (hasModelSettings(result.configured)) return modelDefaults(result.configured);
  const discovered = result.localModels[0];
  return discovered ? { ...discovered, apiKey: "" } : settings;
}

export async function resolvedModel() {
  const fallback = effectiveSettings().llm;
  const result = await probe(fallback);
  if (result.configError) throw new Error(result.error);
  // Resolve identity and metadata from the same probe, even if settings change
  // while discovery is in flight.
  const settings = hasModelSettings(result.configured) ? modelDefaults(result.configured)
    : result.localModels[0] ? { ...result.localModels[0], apiKey: "" } : fallback;
  return { settings, limits: resolveModelLimits(settings, result.limits) };
}

export async function modelStatus() {
  const result = await probe(effectiveSettings().llm);
  const configured = result.configured;
  const explicit = hasModelSettings(configured);
  const selected = explicit ? configured : result.localModels[0];
  const connected = !!selected?.model && (explicit
    ? result.models.includes(selected.model)
    : true);
  const limits = resolveModelLimits({ ...selected, model: selected?.model || "", baseUrl: selected?.baseUrl || "", contextWindow: optionalTokens(configured.contextWindow, "Context window"), maxOutputTokens: optionalTokens(configured.maxOutputTokens, "Maximum output tokens") }, result.limits);
  return {
    connected, model: selected?.model || "", baseUrl: selected?.baseUrl || "",
    source: explicit ? "configured" : "discovered", localModels: result.localModels,
    limits,
    message: connected ? (limits.contextWindow ? "Model available. Streaming and tool support depend on the model." : "Model available, but its context window is unknown. Configure it in Settings before using Harness.")
      : result.error || (explicit ? "The configured model was not found at this endpoint." : "No local model found. Start LM Studio or Ollama, or configure a provider."),
  };
}

export async function settingsPayload() {
  return { settings: savedSettings(), effectiveSettings: { ...effectiveSettings(), llm: await resolvedLlm(), monitoring: await monitoringConnection() } };
}
