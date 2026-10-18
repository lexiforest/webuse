import { TextField, TextFieldInput, TextFieldLabel } from "~/components/ui/text-field";
import { Show, createMemo, createSignal, onMount } from "solid-js";
import { Select, SelectContent, SelectItem, SelectLabel, SelectTrigger, SelectValue } from "~/components/ui/select";
import type { ModelStatus } from "~/components/ModelIndicator";
import { HarnessNotificationSettings } from "~/components/HarnessNotifications";

import { Button } from "~/components/ui/button";
import Layout from "~/layout/dashboard";

type SettingsValue = {
  runtime: {
    databasePath: string;
    workDirectory: string;
    concurrency: string;
  };
  llm: {
    apiKey: string;
    baseUrl: string;
    model: string;
    contextWindow?: string;
    maxOutputTokens?: string;
  };
  harness: { maxToolCalls: string; turnTimeoutSeconds: string };
  monitoring: { prometheusUrl: string; source?: string };
};

const defaultSettings: SettingsValue = {
  runtime: {
    databasePath: "",
    workDirectory: "/tmp/webuse",
    concurrency: "5",
  },
  llm: {
    apiKey: "",
    baseUrl: "",
    model: "",
  },
  harness: { maxToolCalls: "", turnTimeoutSeconds: "" },
  monitoring: { prometheusUrl: "" },
};

async function readSettingsResponse(response: Response, action: "load" | "save") {
  const contentType = response.headers.get("content-type") ?? "";
  const body = await response.text();
  if (!response.ok) {
    let message = `Failed to ${action} settings (${response.status})`;
    if (contentType.includes("application/json")) {
      const payload = JSON.parse(body) as { error?: unknown };
      if (typeof payload.error === "string" && payload.error) message = payload.error;
    }
    throw new Error(message);
  }
  if (!contentType.includes("application/json")) {
    throw new Error(
      "Settings API returned HTML instead of JSON. Restart the Node UI server.",
    );
  }
  return JSON.parse(body) as {
    settings: SettingsValue;
    effectiveSettings: SettingsValue;
  };
}

export default function Settings() {
  const [settings, setSettings] = createSignal<SettingsValue>(defaultSettings);
  const [effectiveSettings, setEffectiveSettings] = createSignal<SettingsValue>(defaultSettings);
  const [loading, setLoading] = createSignal(true);
  const [saving, setSaving] = createSignal(false);
  const [error, setError] = createSignal<string>();
  const [saved, setSaved] = createSignal(false);
  const [testingMonitoring, setTestingMonitoring] = createSignal(false);
  const [monitoringStatus, setMonitoringStatus] = createSignal("");
  const testMonitoring = async () => {
    setTestingMonitoring(true); setMonitoringStatus("");
    try {
      const response = await fetch("/api/monitoring?connection=1");
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "Connection test failed.");
      setMonitoringStatus(data.message);
    } catch (error) { setMonitoringStatus(error instanceof Error ? error.message : String(error)); }
    finally { setTestingMonitoring(false); }
  };
  const [models, setModels] = createSignal<ModelStatus>();
  const modelOptions = createMemo(() => models()?.localModels.map(choice => ({
    ...choice, id: `${choice.baseUrl}#${choice.model}`, label: `${choice.provider} · ${choice.model}`,
  })) ?? []);
  const [discovering, setDiscovering] = createSignal(false);
  const discover = async () => {
    setDiscovering(true);
    try {
      const response = await fetch("/api/models?refresh=1");
      if (!response.ok) throw new Error("Could not discover models.");
      setModels(await response.json());
    } catch (err) { setError(err instanceof Error ? err.message : String(err)); }
    finally { setDiscovering(false); }
  };

  const updateRuntime = (patch: Partial<SettingsValue["runtime"]>) => {
    setSettings(current => ({ ...current, runtime: { ...current.runtime, ...patch } }));
  };
  const updateLlm = (patch: Partial<SettingsValue["llm"]>) => {
    setSettings(current => {
      const changedModel = (patch.model !== undefined && patch.model !== current.llm.model) || (patch.baseUrl !== undefined && patch.baseUrl !== current.llm.baseUrl);
      // An override belongs to this endpoint/model, never the next selection.
      const base = !current.llm.model && !current.llm.baseUrl && (patch.contextWindow || patch.maxOutputTokens) ? effectiveSettings().llm : current.llm;
      return { ...current, llm: { ...base, ...(changedModel ? { contextWindow: "", maxOutputTokens: "" } : {}), ...patch } };
    });
  };
  const updateHarness = (patch: Partial<SettingsValue["harness"]>) => {
    setSettings(current => ({ ...current, harness: { ...current.harness, ...patch } }));
  };

  const load = async () => {
    setError(undefined);
    try {
      const response = await fetch("/api/settings");
      const data = await readSettingsResponse(response, "load");
      setSettings(data.settings);
      setEffectiveSettings(data.effectiveSettings);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load settings");
    } finally {
      setLoading(false);
    }
  };

  const save = async (event: SubmitEvent) => {
    event.preventDefault();
    setSaving(true);
    setError(undefined);
    setSaved(false);

    try {
      const response = await fetch("/api/settings", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ settings: settings() }),
      });
      const data = await readSettingsResponse(response, "save");
      setSettings(data.settings);
      setEffectiveSettings(data.effectiveSettings);
      setSaved(true);
      setMonitoringStatus("");
      window.dispatchEvent(new Event("webuse:model-changed"));
      void discover();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save settings");
    } finally {
      setSaving(false);
    }
  };

  onMount(() => {
    void load();
    void discover();
  });

  return (
    <Layout currentTab="settings">
      <div class="mb-6">
        <h1 class="text-3xl font-bold text-sky-400">Settings</h1>
        <p class="mt-1 text-sm text-gray-400">Runtime, monitoring, and model configuration</p>
        <p class="mt-2 text-xs text-gray-500">
          Settings database: <span class="font-mono text-gray-300">{effectiveSettings().runtime.databasePath}</span>
        </p>
      </div>

      <Show when={error()}>
        {message => (
          <div class="mb-4 rounded border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-200">
            {message()}
          </div>
        )}
      </Show>
      <Show when={saved()}>
        <div class="mb-4 rounded border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-200">
          Saved in {effectiveSettings().runtime.databasePath} and applied to the orchestrator.
        </div>
      </Show>

      <HarnessNotificationSettings />
      <form onSubmit={save}>
        <div class="divide-y divide-gray-800 border-y border-gray-800">
          <section class="grid gap-6 py-6 lg:grid-cols-[14rem_minmax(0,1fr)]">
            <div><h2 id="monitoring" class="text-lg font-semibold text-white">Monitoring</h2><p class="mt-1 text-sm text-gray-400">Prometheus time series for execution dashboards.</p></div>
            <div class="grid max-w-2xl gap-3">
              <TextField value={settings().monitoring.prometheusUrl} disabled={loading()} onChange={value => setSettings(current => ({ ...current, monitoring: { prometheusUrl: value } }))}>
                <TextFieldLabel>Prometheus URL</TextFieldLabel><TextFieldInput placeholder="http://localhost:9090" />
                <span class="text-xs text-gray-400">Effective: {effectiveSettings().monitoring.prometheusUrl || "Not configured"} · {effectiveSettings().monitoring.source || "automatic"}</span>
              </TextField>
              <p class="text-xs text-gray-400">Saved in SQLite. Leave blank to use WEBUSE_PROMETHEUS_URL, then monitoring.prometheus_url in .webuserc.yaml. Webuse queries Prometheus from the server.</p>
              <div><Button type="button" variant="outline" size="sm" disabled={loading() || testingMonitoring()} onClick={() => void testMonitoring()}>{testingMonitoring() ? "Testing…" : "Test saved connection"}</Button></div>
              <Show when={monitoringStatus()}><p class="text-sm text-gray-300" role="status">{monitoringStatus()}</p></Show>
            </div>
          </section>
          <section class="grid gap-6 py-6 lg:grid-cols-[14rem_minmax(0,1fr)]">
            <div>
              <h2 class="text-lg font-semibold text-white">Runtime</h2>
              <p class="mt-1 text-sm text-gray-400">Node orchestration and crawler process defaults.</p>
            </div>
            <div class="grid max-w-2xl gap-3">
              <TextField value={settings().runtime.databasePath} disabled onChange={value => updateRuntime({ databasePath: value })}>
                <TextFieldLabel>Database path</TextFieldLabel>
                <TextFieldInput placeholder="Not set locally" />
                <span class="text-xs text-gray-400">
                  Fixed at server startup: {effectiveSettings().runtime.databasePath}
                </span>
              </TextField>
              <TextField value={settings().runtime.workDirectory} disabled={loading()} onChange={value => updateRuntime({ workDirectory: value })}>
                <TextFieldLabel>Work directory</TextFieldLabel>
                <TextFieldInput placeholder="Not set locally" />
                <span class="text-xs text-gray-400">
                  Effective: {effectiveSettings().runtime.workDirectory}
                </span>
              </TextField>
              <TextField value={settings().runtime.concurrency} disabled={loading()} onChange={value => updateRuntime({ concurrency: value })}>
                <TextFieldLabel>Concurrency</TextFieldLabel>
                <TextFieldInput placeholder="Not set locally" />
                <span class="text-xs text-gray-400">
                  Effective: {effectiveSettings().runtime.concurrency}
                </span>
              </TextField>
            </div>
          </section>

          <section class="grid gap-6 py-6 lg:grid-cols-[14rem_minmax(0,1fr)]">
            <div>
              <h2 class="text-lg font-semibold text-white">Harness</h2>
              <p class="mt-1 text-sm text-gray-400">Optional limits for each assistant turn. Changes apply to the next turn.</p>
            </div>
            <div class="grid max-w-2xl gap-3">
              <TextField value={settings().harness.maxToolCalls} disabled={loading()} onChange={value => updateHarness({ maxToolCalls: value })}>
                <TextFieldLabel>Maximum tool calls per turn</TextFieldLabel>
                <TextFieldInput type="number" min="0" step="1" placeholder="Unlimited" />
              </TextField>
              <TextField value={settings().harness.turnTimeoutSeconds} disabled={loading()} onChange={value => updateHarness({ turnTimeoutSeconds: value })}>
                <TextFieldLabel>Turn time limit (seconds)</TextFieldLabel>
                <TextFieldInput type="number" min="0" max="2147483" step="1" placeholder="Unlimited" />
              </TextField>
              <p class="text-xs text-gray-400">Blank or 0 means unlimited. When a limit is reached, the current tool finishes before the assistant stops. Stop still cancels immediately. Individual tool timeouts remain in effect.</p>
            </div>
          </section>

          <section class="grid gap-6 py-6 lg:grid-cols-[14rem_minmax(0,1fr)]">
            <div>
              <h2 id="model" class="text-lg font-semibold text-white">Model</h2>
              <p class="mt-1 text-sm text-gray-400">OpenAI-compatible model access for extraction and code generation.</p>
            </div>
            <div class="grid max-w-2xl gap-3">
              <div class="flex flex-wrap items-center gap-2">
                <Button variant="outline" type="button" size="sm" disabled={discovering()} onClick={() => void discover()}>
                  {discovering() ? "Discovering…" : "Refresh local models"}
                </Button>
                <Button variant="outline" type="button" size="sm" onClick={() => updateLlm({ apiKey: "", baseUrl: "", model: "" })}>Use automatic discovery</Button>
              </div>
              <p class="text-xs text-gray-400">{models()?.message} Empty model settings use environment variables and .webuserc.yaml, then LM Studio or Ollama. Save to apply your selection.</p>
              <Show when={models()?.localModels.length}>
                <Select
                  class="flex flex-col gap-1.5"
                  options={modelOptions()}
                  value={modelOptions().find(choice => choice.model === settings().llm.model && choice.baseUrl === settings().llm.baseUrl) ?? null}
                  optionValue="id"
                  optionTextValue="label"
                  placeholder="Choose a local model"
                  onChange={choice => {
                    if (choice) updateLlm({ apiKey: "", baseUrl: choice.baseUrl, model: choice.model });
                  }}
                  itemComponent={props => <SelectItem item={props.item}>{props.item.rawValue.label}</SelectItem>}
                >
                  <SelectLabel>Local models</SelectLabel>
                  <SelectTrigger><SelectValue<{ label: string }>>{state => state.selectedOption().label}</SelectValue></SelectTrigger>
                  <SelectContent />
                </Select>
              </Show>
              <TextField value={settings().llm.apiKey} disabled={loading()} onChange={value => updateLlm({ apiKey: value })}>
                <TextFieldLabel>API key</TextFieldLabel>
                <TextFieldInput type="password" placeholder="Not set locally" autocomplete="off" />
                <span class="text-xs text-gray-400">
                  Effective: {effectiveSettings().llm.apiKey ? "Configured" : "Not configured"}
                </span>
              </TextField>
              <TextField value={settings().llm.baseUrl} disabled={loading()} onChange={value => updateLlm({ baseUrl: value })}>
                <TextFieldLabel>Base URL</TextFieldLabel>
                <TextFieldInput placeholder="Not set locally" />
                <span class="text-xs text-gray-400">
                  Effective: {effectiveSettings().llm.baseUrl}
                </span>
              </TextField>
              <TextField value={settings().llm.model} disabled={loading()} onChange={value => updateLlm({ model: value })}>
                <TextFieldLabel>Model</TextFieldLabel>
                <TextFieldInput placeholder="Not set locally" />
                <span class="text-xs text-gray-400">
                  Effective: {effectiveSettings().llm.model}
                </span>
              </TextField>
              <TextField value={settings().llm.contextWindow || ""} disabled={loading()} onChange={value => updateLlm({ contextWindow: value })}>
                <TextFieldLabel>Context window (tokens)</TextFieldLabel>
                <TextFieldInput type="number" min="1" step="1" placeholder="Automatic" />
                <span class="text-xs text-gray-400">Active: {models()?.limits?.contextWindow?.toLocaleString() || "Unknown — configure before using Harness"} · {models()?.limits?.contextSource || "unknown"}</span>
              </TextField>
              <TextField value={settings().llm.maxOutputTokens || ""} disabled={loading()} onChange={value => updateLlm({ maxOutputTokens: value })}>
                <TextFieldLabel>Maximum output tokens</TextFieldLabel>
                <TextFieldInput type="number" min="1" step="1" placeholder="Automatic" />
                <span class="text-xs text-gray-400">Active ceiling: {models()?.limits?.maxOutputTokens?.toLocaleString() || "Not reported"} · {models()?.limits?.outputSource || "unknown"}. Response budget: {models()?.limits?.responseTokens?.toLocaleString() || "Unknown"}.</span>
              </TextField>
              <p class="text-xs text-gray-400">Blank limits use the serving endpoint, then the built-in catalog. Local models use their loaded context allocation. Overrides apply to the selected endpoint and model; changing either clears them. Save and refresh to see active limits.</p>
            </div>
          </section>

        </div>

        <div class="mt-6 flex justify-end">
          <Button variant="default" type="submit" disabled={loading() || saving()}>
            {saving() ? "Applying..." : "Save & Apply"}
          </Button>
        </div>
      </form>
    </Layout>
  );
}
