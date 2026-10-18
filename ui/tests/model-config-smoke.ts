import assert from "node:assert/strict";
import { existsSync, mkdirSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { clearModelCache, modelStatus, resolvedLlm, settingsPayload } from "../src/lib/server/models";
import { store } from "../src/lib/server/store";

// Exercise the real framework config loader while replacing only model HTTP calls.
if (process.platform !== "win32") {
  const originalSettings = store.getSettings();
  const originalEnvironment = { ...process.env };
  const directory = join(process.env.WEBUSE_WORK_DIR!, "config-fixture");
  mkdirSync(directory, { recursive: true });
  const userConfig = join(directory, "user.yaml");
  const localConfig = join(directory, ".webuserc.yaml");
  const launchDirectory = join(directory, "project", "ui");
  mkdirSync(launchDirectory, { recursive: true });
  const executable = join(directory, "config-python");
  const python = resolve("../.venv/bin/python");
  assert.ok(existsSync(python), "Run uv sync --extra dev before the UI tests.");
  writeFileSync(userConfig, "llm:\n  api_key: file-key\n  model: user-model\n  base_url: http://user.invalid/v1\n");
  writeFileSync(localConfig, "llm:\n  model: file-model\n  base_url: http://file.invalid/v1\n  context_window: 65536\n  max_output_tokens: 4096\n");
  writeFileSync(executable, `#!${python}
import sys
from pathlib import Path
import webuse.config as config
import webuse.llm as llm
import webuse.model_metadata as metadata
metadata.serving_model_limits = lambda *args, **kwargs: {"contextWindow": 32768, "source": "fixture"}
config.USER_CONFIG_PATH = Path(${JSON.stringify(userConfig)})
llm.discover_local_openai_settings = lambda **kwargs: []
llm.openai_model_ids = lambda *args, **kwargs: ["file-model", "env-model", "saved-model"]
exec(sys.argv[2])
`, { mode: 0o755 });
  try {
    for (const key of Object.keys(process.env)) {
      if (key.startsWith("WEBUSE_LLM_") || key.startsWith("OPENAI_")) delete process.env[key];
    }
    process.env.WEBUSE_PYTHON_COMMAND = executable;
    process.env.WEBUSE_CONFIG_DIR = launchDirectory;
    store.saveSettings({ runtime: { concurrency: "2" } }); clearModelCache();
    assert.deepEqual(await resolvedLlm(), { model: "file-model", baseUrl: "http://file.invalid/v1", apiKey: "file-key", contextWindow: "65536", maxOutputTokens: "4096" });
    assert.equal((await settingsPayload()).effectiveSettings.llm.model, "file-model");
    const status = await modelStatus();
    assert.equal(status.connected, true);
    assert.equal(status.model, "file-model");
    assert.equal(status.limits.contextWindow, 65536);
    assert.equal(status.limits.contextSource, "configured");
    assert.equal(status.limits.maxOutputTokens, 4096);
    assert.ok(!JSON.stringify(status).includes("file-key"));
    process.env.WEBUSE_LLM_MODEL = "env-model"; clearModelCache();
    assert.equal((await resolvedLlm()).model, "env-model");
    assert.equal((await resolvedLlm()).baseUrl, "http://file.invalid/v1");
    store.saveSettings({ llm: { model: "saved-model", baseUrl: "http://saved.invalid/v1", apiKey: "saved-key" } });
    writeFileSync(localConfig, "llm: [invalid YAML"); clearModelCache();
    assert.equal((await resolvedLlm()).model, "saved-model", "Saved models must not read malformed fallback files");
    assert.equal((await modelStatus()).connected, true);
    store.saveSettings({}); clearModelCache();
    await assert.rejects(resolvedLlm(), /Cannot read Webuse model configuration/);
    assert.equal((await modelStatus()).connected, false);
  } finally {
    for (const key of Object.keys(process.env)) if (!(key in originalEnvironment)) delete process.env[key];
    Object.assign(process.env, originalEnvironment);
    store.saveSettings(originalSettings); clearModelCache();
  }
  console.log("Model config passed: .webuserc.yaml fallback, user config, environment and SQLite precedence, status, and invalid configuration.");
}
