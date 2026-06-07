import Layout from "~/layout/dashboard";

export default function Settings() {
  return (
    <Layout currentTab="settings">
      <div class="mb-6">
        <h1 class="text-3xl font-bold text-sky-400">Settings</h1>
        <p class="mt-1 text-sm text-gray-400">Global runtime and selector configuration</p>
      </div>

      <section class="grid gap-4 lg:grid-cols-2">
        <form class="rounded-lg border border-gray-700 bg-gray-900 p-4">
          <h2 class="mb-4 text-lg font-semibold text-white">Runtime</h2>
          <div class="grid gap-3">
            <label class="field dark-field">
              <span>Database path</span>
              <input value="./webuse.sqlite" />
            </label>
            <label class="field dark-field">
              <span>Work directory</span>
              <input value="/tmp/webuse" />
            </label>
            <label class="field dark-field">
              <span>Concurrency</span>
              <input value="5" />
            </label>
            <button class="btn primary" type="button">Save runtime</button>
          </div>
        </form>

        <form class="rounded-lg border border-gray-700 bg-gray-900 p-4">
          <h2 class="mb-4 text-lg font-semibold text-white">Smart selectors</h2>
          <div class="grid gap-3">
            <label class="field dark-field">
              <span>Selector store</span>
              <input value=".webuse/selectors.json" />
            </label>
            <label class="field dark-field">
              <span>LLM base URL</span>
              <input value="https://api.openai.com/v1" />
            </label>
            <label class="field dark-field">
              <span>Model</span>
              <input value="gpt-4.1-mini" />
            </label>
            <button class="btn primary" type="button">Save selectors</button>
          </div>
        </form>
      </section>
    </Layout>
  );
}
