import { useNavigate, useSearchParams } from "@solidjs/router";
import { For, createSignal, onCleanup, onMount } from "solid-js";

import ExecutionViewerLayout, { type ExecutionSummary } from "~/components/ExecutionViewerLayout";

type Execution = ExecutionSummary;

type LogLine = {
  id: number;
  jobId: number;
  stream: "stdout" | "stderr";
  message: string;
  time: string;
};

const LOG_CHUNK_SIZE = 100;
const MAX_LOADED_LOGS = 1000;

export default function Logs() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [executions, setExecutions] = createSignal<Execution[]>([]);
  const [logs, setLogs] = createSignal<LogLine[]>([]);
  const [nextLogOffset, setNextLogOffset] = createSignal(0);
  const [totalLogs, setTotalLogs] = createSignal(0);
  const [loadingLogs, setLoadingLogs] = createSignal(false);
  const selectedExecutionId = () => String(searchParams.execution_id ?? "");
  const selectedExecution = () => executions().find(execution => String(execution.id) === selectedExecutionId());
  const hasMoreLogs = () => nextLogOffset() < totalLogs();
  let logRequestSeq = 0;

  const loadExecutions = async () => {
    const response = await fetch("/api/executions");
    if (!response.ok) {
      return;
    }
    const data = (await response.json()) as { executions: Execution[] };
    setExecutions(data.executions);
  };

  const loadLogs = async (
    executionId = selectedExecutionId(),
    { reset = false }: { reset?: boolean } = {},
  ) => {
    if (!executionId) {
      setLogs([]);
      setNextLogOffset(0);
      setTotalLogs(0);
      return;
    }
    if (loadingLogs() && !reset) {
      return;
    }
    const offset = reset ? 0 : nextLogOffset();
    const requestSeq = reset ? ++logRequestSeq : logRequestSeq;
    setLoadingLogs(true);
    try {
      const response = await fetch(`/api/logs?execution_id=${executionId}&limit=${LOG_CHUNK_SIZE}&offset=${offset}`);
      if (!response.ok || requestSeq !== logRequestSeq) {
        return;
      }
      const data = (await response.json()) as { logs: LogLine[]; total: number };
      if (requestSeq !== logRequestSeq) {
        return;
      }
      setTotalLogs(data.total);
      setNextLogOffset(offset + data.logs.length);
      setLogs(current => {
        const next = reset ? data.logs : [...current, ...data.logs];
        return next.length > MAX_LOADED_LOGS ? next.slice(next.length - MAX_LOADED_LOGS) : next;
      });
    } finally {
      if (requestSeq === logRequestSeq) {
        setLoadingLogs(false);
      }
    }
  };

  const loadNextLogs = () => {
    if (!hasMoreLogs()) {
      return;
    }
    void loadLogs();
  };

  onMount(() => {
    void loadExecutions().then(() => loadLogs(selectedExecutionId(), { reset: true }));
    const timer = window.setInterval(() => {
      void loadExecutions();
    }, 2000);
    onCleanup(() => window.clearInterval(timer));
  });

  return (
    <ExecutionViewerLayout
      currentTab="logs"
      title="Logs"
      description="Stdout and stderr from active executions"
      executions={executions}
      selectedExecutionId={selectedExecutionId}
      selectedExecution={selectedExecution}
      emptyContentTitle="Log output"
      emptySelectionText="Select an execution to view logs."
      onSelectExecution={execution => {
        navigate(`/logs?execution_id=${execution.id}`);
        void loadLogs(String(execution.id), { reset: true });
      }}
      onContentEnd={loadNextLogs}
    >
      <div class="space-y-2">
        <For each={logs()} fallback={<div class="text-sm text-gray-500">No logs yet.</div>}>
          {line => (
            <div class="grid gap-3 rounded bg-gray-900 px-3 py-2 font-mono text-xs text-gray-300 md:grid-cols-[72px_72px_1fr]">
              <span class="text-gray-500">{line.time}</span>
              <span class={line.stream === "stderr" ? "text-sky-300" : "text-emerald-300"}>{line.stream}</span>
              <span>{line.message}</span>
            </div>
          )}
        </For>
        {loadingLogs() && <div class="text-sm text-gray-500">Loading logs...</div>}
        {!loadingLogs() && hasMoreLogs() && <div class="text-sm text-gray-500">Scroll to load more logs.</div>}
      </div>
    </ExecutionViewerLayout>
  );
}
