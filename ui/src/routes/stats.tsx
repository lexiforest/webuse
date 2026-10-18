import { For, Show, createSignal, onCleanup, onMount } from "solid-js";

import Layout from "~/layout/dashboard";
import ValidationBadge from "~/components/ValidationBadge";

type Execution = {
  id: number;
  project: string;
  status: "queued" | "running" | "succeeded" | "failed" | "cancelled";
  items: number;
  metadata?: Record<string, unknown>;
};

type LogLine = {
  id: number;
  stream: "stdout" | "stderr";
  message: string;
  time: string;
};

export default function Stats() {
  const [projectCount, setProjectCount] = createSignal(0);
  const [executions, setExecutions] = createSignal<Execution[]>([]);
  const [logs, setLogs] = createSignal<LogLine[]>([]);
  const [logCount, setLogCount] = createSignal(0);
  const [error, setError] = createSignal("");
  const itemCount = () => executions().reduce((total, execution) => total + execution.items, 0);

  const stats = () => [
    { label: "Projects", value: projectCount() },
    {
      label: "Executions",
      value: `${executions().filter(execution => execution.status === "queued" || execution.status === "running").length}/${executions().length}`,
    },
    { label: "Items", value: itemCount() },
    { label: "Log lines", value: logCount() },
  ];

  const loadLogs = async () => {
    const response = await fetch("/api/logs");
    if (!response.ok) throw new Error("Could not load logs");
    const data = (await response.json()) as { logs: LogLine[]; total?: number };
    setLogs(data.logs.slice(0, 6));
    setLogCount(data.total ?? data.logs.length);
  };

  onMount(() => {
    let pending = false;
    const refresh = async () => {
      if (pending) return;
      pending = true;
      try {
        const [projectsResponse, executionsResponse] = await Promise.all([
          fetch("/api/projects"),
          fetch("/api/executions"),
        ]);
        if (!projectsResponse.ok || !executionsResponse.ok) throw new Error();
        const projects = await projectsResponse.json() as { projects: unknown[] };
        const jobs = await executionsResponse.json() as { executions: Execution[] };
        setProjectCount(projects.projects.length);
        setExecutions(jobs.executions);
        await loadLogs();
        setError("");
      } catch { setError("Could not refresh stats. Retrying…"); }
      finally { pending = false; }
    };
    void refresh();
    const timer = window.setInterval(() => void refresh(), 2000);
    onCleanup(() => window.clearInterval(timer));
  });

  return (
    <Layout currentTab="stats">
      <div class="mb-6 flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 class="text-3xl font-bold text-sky-400">Stats</h1>
          <p class="mt-1 text-sm text-gray-400">webuse crawling task control plane</p>
        </div>
      </div>

      <Show when={error()}><p role="status" class="mb-3 text-sm text-amber-300">{error()}</p></Show>
      <section class="grid gap-4 md:grid-cols-4">
        <For each={stats()}>
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
            <h2 class="text-lg font-semibold text-white">Recent executions</h2>
            <a href="/executions" class="text-sm text-sky-400 hover:text-sky-300">View all</a>
          </div>
          <div class="overflow-x-auto">
            <table class="data-table">
              <thead><tr><th>ID</th><th>Project</th><th>Status</th><th>Items</th></tr></thead>
              <tbody>
                <For each={executions().slice(0, 3)} fallback={<tr><td colspan="4" class="py-6 text-center text-gray-500">No executions yet.</td></tr>}>
                  {execution => (
                    <tr>
                      <td><span class="inline-flex items-center gap-2">#{execution.id}<ValidationBadge metadata={execution.metadata} /></span></td>
                      <td>{execution.project}</td>
                      <td><Status value={execution.status} /></td>
                      <td>{execution.items}</td>
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
            <For each={logs()} fallback={<div class="text-sm text-gray-500">No logs yet.</div>}>
              {line => (
                <div class="rounded bg-gray-800 px-3 py-2 font-mono text-xs text-gray-300">
                  <span class="text-gray-500">{line.time}</span>{" "}
                  <span class={line.stream === "stderr" ? "text-sky-300" : "text-emerald-300"}>{line.stream}</span>{" "}
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
