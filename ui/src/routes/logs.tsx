import { For } from "solid-js";

import Layout from "~/layout/dashboard";
import { jobs, logs } from "~/lib/dashboard-data";

export default function Logs() {
  return (
    <Layout currentTab="logs">
      <div class="mb-6 flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 class="text-3xl font-bold text-sky-400">Logs</h1>
          <p class="mt-1 text-sm text-gray-400">Stdout and stderr from running jobs</p>
        </div>
        <select class="dark-select w-[220px]">
          <For each={jobs}>{job => <option value={job.id}>#{job.id} {job.project}</option>}</For>
        </select>
      </div>

      <section class="rounded-lg border border-gray-700 bg-gray-950 p-4">
        <div class="space-y-2">
          <For each={logs}>
            {line => (
              <div class="grid gap-3 rounded bg-gray-900 px-3 py-2 font-mono text-xs text-gray-300 md:grid-cols-[72px_72px_1fr]">
                <span class="text-gray-500">{line.time}</span>
                <span class={line.stream === "stderr" ? "text-red-300" : "text-emerald-300"}>{line.stream}</span>
                <span>{line.message}</span>
              </div>
            )}
          </For>
        </div>
      </section>
    </Layout>
  );
}
