import { useNavigate, useSearchParams } from "@solidjs/router";
import { For, createSignal, onCleanup, onMount } from "solid-js";

import RunViewerLayout, { type RunViewerRun } from "~/components/RunViewerLayout";

type Run = RunViewerRun;

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
  const [runs, setRuns] = createSignal<Run[]>([]);
  const [logs, setLogs] = createSignal<LogLine[]>([]);
  const [nextLogOffset, setNextLogOffset] = createSignal(0);
  const [totalLogs, setTotalLogs] = createSignal(0);
  const [loadingLogs, setLoadingLogs] = createSignal(false);
  const selectedRunId = () => String(searchParams.run_id ?? "");
  const selectedRun = () => runs().find(run => String(run.id) === selectedRunId());
  const hasMoreLogs = () => nextLogOffset() < totalLogs();
  let logRequestSeq = 0;

  const loadRuns = async () => {
    const response = await fetch("/api/runs");
    if (!response.ok) {
      return;
    }
    const data = (await response.json()) as { runs: Run[] };
    setRuns(data.runs);
  };

  const loadLogs = async (
    runId = selectedRunId(),
    { reset = false }: { reset?: boolean } = {},
  ) => {
    if (!runId) {
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
      const response = await fetch(`/api/logs?run_id=${runId}&limit=${LOG_CHUNK_SIZE}&offset=${offset}`);
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
    void loadRuns().then(() => loadLogs(selectedRunId(), { reset: true }));
    const timer = window.setInterval(() => {
      void loadRuns();
    }, 2000);
    onCleanup(() => window.clearInterval(timer));
  });

  return (
    <RunViewerLayout
      currentTab="logs"
      title="Logs"
      description="Stdout and stderr from active runs"
      runs={runs}
      selectedRunId={selectedRunId}
      selectedRun={selectedRun}
      emptyContentTitle="Log output"
      emptySelectionText="Select a run to view logs."
      onSelectRun={run => {
        navigate(`/logs?run_id=${run.id}`);
        void loadLogs(String(run.id), { reset: true });
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
    </RunViewerLayout>
  );
}
