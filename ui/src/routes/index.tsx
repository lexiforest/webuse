import { For } from "solid-js";

import Layout from "~/layout/dashboard";
import { dataItems, jobs, logs, projects } from "~/lib/dashboard-data";

const stats = [
  { label: "Projects", value: projects.length },
  { label: "Running jobs", value: jobs.filter(job => job.status === "running").length },
  { label: "Items", value: dataItems.length },
  { label: "Log lines", value: logs.length },
];

export default function Overview() {
  return (
    <Layout currentTab="overview">
      <div class="mb-6 flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 class="text-3xl font-bold text-sky-400">Dashboard</h1>
          <p class="mt-1 text-sm text-gray-400">webuse crawling task control plane</p>
        </div>
        <a href="/projects" class="btn primary">New project</a>
      </div>

      <section class="grid gap-4 md:grid-cols-4">
        <For each={stats}>
          {stat => (
            <div class="rounded-lg border border-gray-700 bg-gray-900 p-4">
              <div class="text-sm text-gray-400">{stat.label}</div>
              <div class="mt-2 text-3xl font-semibold text-white">{stat.value}</div>
            </div>
          )}
        </For>
      </section>

      <section class="mt-6 grid gap-4 lg:grid-cols-[1fr_0.8fr]">
        <div class="rounded-lg border border-gray-700 bg-gray-900 p-4">
          <div class="mb-3 flex items-center justify-between">
            <h2 class="text-lg font-semibold text-white">Recent jobs</h2>
            <a href="/jobs" class="text-sm text-sky-400 hover:text-sky-300">View all</a>
          </div>
          <div class="overflow-x-auto">
            <table class="data-table">
              <thead>
                <tr><th>ID</th><th>Project</th><th>Status</th><th>Items</th></tr>
              </thead>
              <tbody>
                <For each={jobs.slice(0, 3)}>
                  {job => (
                    <tr>
                      <td>#{job.id}</td>
                      <td>{job.project}</td>
                      <td><Status value={job.status} /></td>
                      <td>{job.items}</td>
                    </tr>
                  )}
                </For>
              </tbody>
            </table>
          </div>
        </div>

        <div class="rounded-lg border border-gray-700 bg-gray-900 p-4">
          <div class="mb-3 flex items-center justify-between">
            <h2 class="text-lg font-semibold text-white">Live logs</h2>
            <a href="/logs" class="text-sm text-sky-400 hover:text-sky-300">Open logs</a>
          </div>
          <div class="space-y-2">
            <For each={logs}>
              {line => (
                <div class="rounded bg-gray-800 px-3 py-2 font-mono text-xs text-gray-300">
                  <span class="text-gray-500">{line.time}</span>{" "}
                  <span class={line.stream === "stderr" ? "text-red-300" : "text-emerald-300"}>{line.stream}</span>{" "}
                  {line.message}
                </div>
              )}
            </For>
          </div>
        </div>
      </section>
    </Layout>
  );
}

function Status(props: { value: string }) {
  const color = () =>
    props.value === "running"
      ? "bg-sky-500/20 text-sky-200"
      : props.value === "succeeded"
        ? "bg-emerald-500/20 text-emerald-200"
        : props.value === "failed"
          ? "bg-red-500/20 text-red-200"
          : "bg-gray-700 text-gray-200";
  return <span class={`rounded px-2 py-1 text-xs ${color()}`}>{props.value}</span>;
}
