import { A, useSearchParams } from "@solidjs/router";
import { Show, createSignal, onCleanup, onMount } from "solid-js";
import { FiDatabase, FiFileText } from "solid-icons/fi";

import { Button } from "~/components/ui/button";
import TableView from "~/components/TableView";
import ValidationBadge from "~/components/ValidationBadge";
import Layout from "~/layout/dashboard";

type Execution = {
  id: number;
  project: string;
  status: "queued" | "running" | "succeeded" | "failed" | "cancelled";
  startedAt: string;
  duration: string;
  items: number;
  metadata?: Record<string, unknown>;
};

export default function Executions() {
  const [searchParams] = useSearchParams();
  const [executions, setExecutions] = createSignal<Execution[]>([]);
  const [loading, setLoading] = createSignal(true);
  const [error, setError] = createSignal<string>();
  const projectId = () => String(searchParams.project_id ?? "");
  const executionsUrl = () => {
    const params = new URLSearchParams();
    if (projectId()) {
      params.set("project_id", projectId());
    }
    const query = params.toString();
    return query ? `/api/executions?${query}` : "/api/executions";
  };

  const loadExecutions = async () => {
    try {
      const response = await fetch(executionsUrl());
      if (!response.ok) {
        throw new Error(`Failed to load executions (${response.status})`);
      }
      const data = (await response.json()) as { executions: Execution[] };
      setExecutions(data.executions);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load executions");
    } finally {
      setLoading(false);
    }
  };

  const cancelExecution = (id: number) => {
    void (async () => {
      try {
        const response = await fetch(`/api/executions?id=${id}`, { method: "DELETE" });
        if (!response.ok) {
          throw new Error(`Failed to cancel execution (${response.status})`);
        }
        await loadExecutions();
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to cancel execution");
      }
    })();
  };

  onMount(() => {
    void loadExecutions();
    const timer = window.setInterval(() => {
      void loadExecutions();
    }, 2000);
    onCleanup(() => window.clearInterval(timer));
  });

  return (
    <Layout currentTab="executions">
      <div class="mb-6 flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 class="text-3xl font-bold text-sky-400">Executions</h1>
          <p class="mt-1 text-sm text-gray-400">
            {projectId()
              ? `Execution queue and history for project #${projectId()}`
              : "Execution queue and history"}
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
          items={executions()}
          columns={["ID", "Project", "Status", "Started", "Duration", "Items", "Actions"]}
          loading={loading()}
          loadingText="Loading executions..."
          emptyText="No executions yet."
          itemLabel="executions"
          renderRow={execution => (
            <tr>
              <td><span class="inline-flex items-center gap-2">#{execution.id}<ValidationBadge metadata={execution.metadata} /></span></td>
              <td class="font-medium text-white">{execution.project}</td>
              <td>{execution.status}</td>
              <td>{execution.startedAt}</td>
              <td>{execution.duration}</td>
              <td>{execution.items}</td>
              <td class="flex gap-2">
                <Button variant="outline" as={A} href={`/monitoring?execution_id=${execution.id}`} size="sm">Monitor</Button>
                <Button variant="outline" as={A} class="gap-1.5" href={`/logs?execution_id=${execution.id}`} size="sm">
                  <FiFileText size={13} stroke-width={2} aria-hidden="true" />
                  Logs
                </Button>
                <Button variant="outline" as={A} class="gap-1.5" href={`/data?execution_id=${execution.id}`} size="sm">
                  <FiDatabase size={13} stroke-width={2} aria-hidden="true" />
                  Data
                </Button>
                <Show when={execution.status === "queued" || execution.status === "running"}>
                  <Button size="sm" variant="destructive" type="button" onClick={() => cancelExecution(execution.id)}>
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
