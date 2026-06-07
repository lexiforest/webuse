import { For } from "solid-js";

import Layout from "~/layout/dashboard";
import { dataItems } from "~/lib/dashboard-data";

export default function Data() {
  return (
    <Layout currentTab="data">
      <div class="mb-6 flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 class="text-3xl font-bold text-sky-400">Data</h1>
          <p class="mt-1 text-sm text-gray-400">JSON items parsed from completed jobs</p>
        </div>
        <button class="btn" type="button">Export JSONL</button>
      </div>

      <section class="grid gap-4">
        <For each={dataItems}>
          {item => (
            <article class="rounded-lg border border-gray-700 bg-gray-900 p-4">
              <div class="mb-3 flex flex-wrap items-center justify-between gap-2 text-sm">
                <div class="text-gray-400">Job #{item.jobId}</div>
                <a class="text-sky-400 hover:text-sky-300" href={item.url}>{item.url}</a>
              </div>
              <pre class="output compact">{JSON.stringify(item.item, null, 2)}</pre>
            </article>
          )}
        </For>
      </section>
    </Layout>
  );
}
