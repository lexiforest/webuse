import { useSearchParams } from "@solidjs/router";
import { Show, createSignal, onCleanup, onMount } from "solid-js";
import { FiDatabase, FiFileText } from "solid-icons/fi";

import Button, { ButtonLink } from "~/components/Button";
import TableView from "~/components/TableView";
import Layout from "~/layout/dashboard";

type Run = {
  id: number;
  project: string;
  status: "queued" | "running" | "succeeded" | "failed" | "cancelled";
  startedAt: string;
  duration: string;
  items: number;
};

export default function Runs() {
  const [searchParams] = useSearchParams();
  const [runs, setRuns] = createSignal<Run[]>([]);
  const [loading, setLoading] = createSignal(true);
  const [error, setError] = createSignal<string>();
  const projectId = () => String(searchParams.project_id ?? "");
  const runsUrl = () => {
    const params = new URLSearchParams();
    if (projectId()) {
      params.set("project_id", projectId());
    }
    const query = params.toString();
    return query ? `/api/runs?${query}` : "/api/runs";
  };

  const loadRuns = async () => {
    try {
      const response = await fetch(runsUrl());
      if (!response.ok) {
        throw new Error(`Failed to load runs (${response.status})`);
      }
      const data = (await response.json()) as { runs: Run[] };
      setRuns(data.runs);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load runs");
    } finally {
      setLoading(false);
    }
  };

  const cancelRun = (id: number) => {
    void (async () => {
      try {
        const response = await fetch(`/api/runs?id=${id}`, { method: "DELETE" });
        if (!response.ok) {
          throw new Error(`Failed to cancel run (${response.status})`);
        }
        await loadRuns();
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to cancel run");
      }
    })();
  };

  onMount(() => {
    void loadRuns();
    const timer = window.setInterval(() => {
      void loadRuns();
    }, 2000);
    onCleanup(() => window.clearInterval(timer));
  });

  return (
    <Layout currentTab="runs">
      <div class="mb-6 flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 class="text-3xl font-bold text-sky-400">Runs</h1>
          <p class="mt-1 text-sm text-gray-400">
            {projectId()
              ? `Run queue and execution history for project #${projectId()}`
              : "Run queue and execution history"}
          </p>
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
        <TableView
          items={runs()}
          columns={["ID", "Project", "Status", "Started", "Duration", "Items", "Actions"]}
          loading={loading()}
          loadingText="Loading runs..."
          emptyText="No runs yet."
          itemLabel="runs"
          renderRow={run => (
            <tr>
              <td>#{run.id}</td>
              <td class="font-medium text-white">{run.project}</td>
              <td>{run.status}</td>
              <td>{run.startedAt}</td>
              <td>{run.duration}</td>
              <td>{run.items}</td>
              <td class="flex gap-2">
                <ButtonLink class="gap-1.5" href={`/logs?run_id=${run.id}`} size="compact">
                  <FiFileText size={13} stroke-width={2} aria-hidden="true" />
                  Logs
                </ButtonLink>
                <ButtonLink class="gap-1.5" href={`/data?run_id=${run.id}`} size="compact">
                  <FiDatabase size={13} stroke-width={2} aria-hidden="true" />
                  Data
                </ButtonLink>
                <Show when={run.status === "queued" || run.status === "running"}>
                  <Button size="compact" variant="danger" type="button" onClick={() => cancelRun(run.id)}>
                    Cancel
                  </Button>
                </Show>
              </td>
            </tr>
          )}
        />
      </section>
    </Layout>
  );
}
