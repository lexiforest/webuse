import { For } from "solid-js";

import Layout from "~/layout/dashboard";
import { jobs } from "~/lib/dashboard-data";

export default function Jobs() {
  return (
    <Layout currentTab="jobs">
      <div class="mb-6 flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 class="text-3xl font-bold text-sky-400">Jobs</h1>
          <p class="mt-1 text-sm text-gray-400">Run queue and execution history</p>
        </div>
        <button class="btn primary" type="button">Run job</button>
      </div>

      <section class="rounded-lg border border-gray-700 bg-gray-900 p-4">
        <div class="overflow-x-auto">
          <table class="data-table">
            <thead>
              <tr>
                <th>ID</th>
                <th>Project</th>
                <th>Status</th>
                <th>Started</th>
                <th>Duration</th>
                <th>Items</th>
              </tr>
            </thead>
            <tbody>
              <For each={jobs}>
                {job => (
                  <tr>
                    <td>#{job.id}</td>
                    <td class="font-medium text-white">{job.project}</td>
                    <td>{job.status}</td>
                    <td>{job.startedAt}</td>
                    <td>{job.duration}</td>
                    <td>{job.items}</td>
                  </tr>
                )}
              </For>
            </tbody>
          </table>
        </div>
      </section>
    </Layout>
  );
}
