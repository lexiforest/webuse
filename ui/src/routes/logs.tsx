import { For, createSignal, onCleanup, onMount } from "solid-js";

import Layout from "~/layout/dashboard";

type Job = {
  id: number;
  project: string;
};

type LogLine = {
  id: number;
  jobId: number;
  stream: "stdout" | "stderr";
  message: string;
  time: string;
};

export default function Logs() {
  const [jobs, setJobs] = createSignal<Job[]>([]);
  const [logs, setLogs] = createSignal<LogLine[]>([]);
  const [selectedJobId, setSelectedJobId] = createSignal("");

  const loadJobs = async () => {
    const response = await fetch("/api/jobs");
    if (!response.ok) {
      return;
    }
    const data = (await response.json()) as { jobs: Job[] };
    setJobs(data.jobs);
    if (!selectedJobId() && data.jobs.length > 0) {
      setSelectedJobId(String(data.jobs[0].id));
    }
  };

  const loadLogs = async (jobId = selectedJobId()) => {
    const query = jobId ? `?id=${jobId}` : "";
    const response = await fetch(`/api/logs${query}`);
    if (!response.ok) {
      return;
    }
    const data = (await response.json()) as { logs: LogLine[] };
    setLogs(data.logs);
  };

  onMount(() => {
    void loadJobs().then(loadLogs);
    const timer = window.setInterval(() => {
      void loadLogs();
    }, 2000);
    onCleanup(() => window.clearInterval(timer));
  });

  return (
    <Layout currentTab="logs">
      <div class="mb-6 flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 class="text-3xl font-bold text-sky-400">Logs</h1>
          <p class="mt-1 text-sm text-gray-400">Stdout and stderr from running jobs</p>
        </div>
        <select
          class="dark-select w-[220px]"
          value={selectedJobId()}
          onInput={event => {
            const jobId = event.currentTarget.value;
            setSelectedJobId(jobId);
            void loadLogs(jobId);
          }}
        >
          <For each={jobs()}>{job => <option value={job.id}>#{job.id} {job.project}</option>}</For>
        </select>
      </div>

      <section class="rounded-lg border border-gray-700 bg-gray-950 p-4">
        <div class="space-y-2">
          <For each={logs()} fallback={<div class="text-sm text-gray-500">No logs yet.</div>}>
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
