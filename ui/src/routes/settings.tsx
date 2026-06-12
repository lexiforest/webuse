import { Show, createSignal, onMount } from "solid-js";

import Button from "~/components/Button";
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
  };
  smart: {
    selectorStore: string;
  };
};

const defaultSettings: SettingsValue = {
  runtime: {
    databasePath: "./webuse.sqlite",
    workDirectory: "/tmp/webuse",
    concurrency: "5",
  },
  llm: {
    apiKey: "",
    baseUrl: "https://api.openai.com/v1",
    model: "gpt-4.1-mini",
  },
  smart: {
    selectorStore: "selectors.json",
  },
};

async function readSettingsResponse(response: Response, action: "load" | "save") {
  const contentType = response.headers.get("content-type") ?? "";
  const body = await response.text();
  if (!response.ok) {
    let message = `Failed to ${action} settings (${response.status})`;
    if (contentType.includes("application/json")) {
      const payload = JSON.parse(body) as { error?: string };
      message = payload.error || message;
    }
    throw new Error(message);
  }
  if (!contentType.includes("application/json")) {
    throw new Error(
      "Settings API returned HTML instead of JSON. Restart the UI worker so the /settings endpoint is available.",
    );
  }
  return JSON.parse(body) as {
    settings: SettingsValue;
    effectiveSettings: SettingsValue;
    paths: { local: string; user: string };
  };
}

export default function Settings() {
  const [settings, setSettings] = createSignal<SettingsValue>(defaultSettings);
  const [effectiveSettings, setEffectiveSettings] = createSignal<SettingsValue>(defaultSettings);
  const [localPath, setLocalPath] = createSignal(".webuserc.yaml");
  const [loading, setLoading] = createSignal(true);
  const [saving, setSaving] = createSignal(false);
  const [error, setError] = createSignal<string>();
  const [saved, setSaved] = createSignal(false);

  const updateRuntime = (patch: Partial<SettingsValue["runtime"]>) => {
    setSettings(current => ({ ...current, runtime: { ...current.runtime, ...patch } }));
  };
  const updateLlm = (patch: Partial<SettingsValue["llm"]>) => {
    setSettings(current => ({ ...current, llm: { ...current.llm, ...patch } }));
  };
  const updateSmart = (patch: Partial<SettingsValue["smart"]>) => {
    setSettings(current => ({ ...current, smart: { ...current.smart, ...patch } }));
  };

  const load = async () => {
    setError(undefined);
    try {
      const response = await fetch("/api/settings");
      const data = await readSettingsResponse(response, "load");
      setSettings(data.settings);
      setEffectiveSettings(data.effectiveSettings);
      setLocalPath(data.paths.local);
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
      setLocalPath(data.paths.local);
      setSaved(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save settings");
    } finally {
      setSaving(false);
    }
  };

  onMount(() => {
    void load();
  });

  return (
    <Layout currentTab="settings">
      <div class="mb-6">
        <h1 class="text-3xl font-bold text-sky-400">Settings</h1>
        <p class="mt-1 text-sm text-gray-400">Global runtime, LLM, and selector configuration</p>
        <p class="mt-2 text-xs text-gray-500">
          Editing local config: <span class="font-mono text-gray-300">{localPath()}</span>
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
          Saved to {localPath()} and applied to the worker.
        </div>
      </Show>

      <form onSubmit={save}>
        <div class="divide-y divide-gray-800 border-y border-gray-800">
          <section class="grid gap-6 py-6 lg:grid-cols-[14rem_minmax(0,1fr)]">
            <div>
              <h2 class="text-lg font-semibold text-white">Runtime</h2>
              <p class="mt-1 text-sm text-gray-400">Local worker storage and execution defaults.</p>
            </div>
            <div class="grid max-w-2xl gap-3">
              <label class="field dark-field">
                <span>Database path</span>
                <input
                  value={settings().runtime.databasePath}
                  placeholder="Not set locally"
                  disabled={loading()}
                  onInput={event => updateRuntime({ databasePath: event.currentTarget.value })}
                />
                <span class="text-xs text-gray-400">
                  Effective: {effectiveSettings().runtime.databasePath}
                </span>
              </label>
              <label class="field dark-field">
                <span>Work directory</span>
                <input
                  value={settings().runtime.workDirectory}
                  placeholder="Not set locally"
                  disabled={loading()}
                  onInput={event => updateRuntime({ workDirectory: event.currentTarget.value })}
                />
                <span class="text-xs text-gray-400">
                  Effective: {effectiveSettings().runtime.workDirectory}
                </span>
              </label>
              <label class="field dark-field">
                <span>Concurrency</span>
                <input
                  value={settings().runtime.concurrency}
                  placeholder="Not set locally"
                  disabled={loading()}
                  onInput={event => updateRuntime({ concurrency: event.currentTarget.value })}
                />
                <span class="text-xs text-gray-400">
                  Effective: {effectiveSettings().runtime.concurrency}
                </span>
              </label>
            </div>
          </section>

          <section class="grid gap-6 py-6 lg:grid-cols-[14rem_minmax(0,1fr)]">
            <div>
              <h2 class="text-lg font-semibold text-white">LLM</h2>
              <p class="mt-1 text-sm text-gray-400">OpenAI-compatible API keys for smart extraction and generation.</p>
            </div>
            <div class="grid max-w-2xl gap-3">
              <label class="field dark-field">
                <span>API key</span>
                <input
                  type="password"
                  value={settings().llm.apiKey}
                  placeholder="Not set locally"
                  autocomplete="off"
                  disabled={loading()}
                  onInput={event => updateLlm({ apiKey: event.currentTarget.value })}
                />
                <span class="text-xs text-gray-400">
                  Effective: {effectiveSettings().llm.apiKey ? "Configured" : "Not configured"}
                </span>
              </label>
              <label class="field dark-field">
                <span>Base URL</span>
                <input
                  value={settings().llm.baseUrl}
                  placeholder="Not set locally"
                  disabled={loading()}
                  onInput={event => updateLlm({ baseUrl: event.currentTarget.value })}
                />
                <span class="text-xs text-gray-400">
                  Effective: {effectiveSettings().llm.baseUrl}
                </span>
              </label>
              <label class="field dark-field">
                <span>Model</span>
                <input
                  value={settings().llm.model}
                  placeholder="Not set locally"
                  disabled={loading()}
                  onInput={event => updateLlm({ model: event.currentTarget.value })}
                />
                <span class="text-xs text-gray-400">
                  Effective: {effectiveSettings().llm.model}
                </span>
              </label>
            </div>
          </section>

          <section class="grid gap-6 py-6 lg:grid-cols-[14rem_minmax(0,1fr)]">
            <div>
              <h2 class="text-lg font-semibold text-white">Smart selectors</h2>
              <p class="mt-1 text-sm text-gray-400">Local storage for resolved selector state.</p>
            </div>
            <div class="grid max-w-2xl gap-3">
              <label class="field dark-field">
                <span>Selector store</span>
                <input
                  value={settings().smart.selectorStore}
                  placeholder="Not set locally"
                  disabled={loading()}
                  onInput={event => updateSmart({ selectorStore: event.currentTarget.value })}
                />
                <span class="text-xs text-gray-400">
                  Effective: {effectiveSettings().smart.selectorStore}
                </span>
              </label>
            </div>
          </section>
        </div>

        <div class="mt-6 flex justify-end">
          <Button variant="primary" type="submit" disabled={loading() || saving()}>
            {saving() ? "Applying..." : "Save & Apply"}
          </Button>
        </div>
      </form>
    </Layout>
  );
}
