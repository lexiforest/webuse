import { For, Show, createSignal, onCleanup, onMount } from "solid-js";

import Button from "~/components/Button";
import Layout from "~/layout/dashboard";

type Job = {
  id: number;
  project: string;
  status: "queued" | "running" | "succeeded" | "failed" | "cancelled";
  startedAt: string;
  duration: string;
  items: number;
};

export default function Jobs() {
  const [jobs, setJobs] = createSignal<Job[]>([]);
  const [loading, setLoading] = createSignal(true);
  const [error, setError] = createSignal<string>();

  const loadJobs = async () => {
    try {
      const response = await fetch("/api/jobs");
      if (!response.ok) {
        throw new Error(`Failed to load jobs (${response.status})`);
      }
      const data = (await response.json()) as { jobs: Job[] };
      setJobs(data.jobs);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load jobs");
    } finally {
      setLoading(false);
    }
  };

  const cancelJob = (id: number) => {
    void (async () => {
      try {
        const response = await fetch(`/api/jobs?id=${id}`, { method: "DELETE" });
        if (!response.ok) {
          throw new Error(`Failed to cancel job (${response.status})`);
        }
        await loadJobs();
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to cancel job");
      }
    })();
  };

  onMount(() => {
    void loadJobs();
    const timer = window.setInterval(() => {
      void loadJobs();
    }, 2000);
    onCleanup(() => window.clearInterval(timer));
  });

  return (
    <Layout currentTab="jobs">
      <div class="mb-6 flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 class="text-3xl font-bold text-sky-400">Jobs</h1>
          <p class="mt-1 text-sm text-gray-400">Run queue and execution history</p>
        </div>
      </div>

      <section class="rounded-lg border border-gray-700 bg-gray-900 p-4">
        <Show when={error()}>
          {message => (
            <div class="mb-4 rounded border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-200">
              {message()}
            </div>
          )}
        </Show>
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
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              <For
                each={jobs()}
                fallback={
                  <tr>
                    <td class="py-10 text-center text-gray-500" colspan="7">
                      {loading() ? "Loading jobs..." : "No jobs yet."}
                    </td>
                  </tr>
                }
              >
                {job => (
                  <tr>
                    <td>#{job.id}</td>
                    <td class="font-medium text-white">{job.project}</td>
                    <td>{job.status}</td>
                    <td>{job.startedAt}</td>
                    <td>{job.duration}</td>
                    <td>{job.items}</td>
                    <td>
                      <Show when={job.status === "queued" || job.status === "running"}>
                        <Button size="compact" variant="danger" type="button" onClick={() => cancelJob(job.id)}>
                          Cancel
                        </Button>
                      </Show>
                    </td>
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
