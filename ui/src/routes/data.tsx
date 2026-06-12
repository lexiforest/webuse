import { useNavigate, useSearchParams } from "@solidjs/router";
import { For, createMemo, createSignal, onCleanup, onMount, type JSX } from "solid-js";

import Button from "~/components/Button";
import Pagination from "~/components/Pagination";
import RunViewerLayout, { type RunViewerRun } from "~/components/RunViewerLayout";

type DataItem = {
  id: number;
  jobId: number;
  url: string;
  item: Record<string, unknown>;
};

type Run = RunViewerRun;

const jsonTokenPattern =
  /("(?:\\u[a-fA-F0-9]{4}|\\[^u]|[^\\"])*"(?=\s*:)|"(?:\\u[a-fA-F0-9]{4}|\\[^u]|[^\\"])*"|true|false|null|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?|[{}\[\],:])/g;

function tokenClass(token: string, isKey = false) {
  if (token.startsWith('"')) {
    return isKey ? "json-key" : "json-string";
  }
  if (token === "true" || token === "false") {
    return "json-boolean";
  }
  if (token === "null") {
    return "json-null";
  }
  if (/^-?\d/.test(token)) {
    return "json-number";
  }
  return "json-punctuation";
}

function highlightJson(value: Record<string, unknown>): JSX.Element[] {
  const text = JSON.stringify(value, null, 2);
  const parts: JSX.Element[] = [];
  let index = 0;

  for (const match of text.matchAll(jsonTokenPattern)) {
    const token = match[0];
    const start = match.index ?? 0;
    const isKey = token.startsWith('"') && /^\s*:/.test(text.slice(start + token.length));
    if (start > index) {
      parts.push(text.slice(index, start));
    }
    parts.push(<span class={tokenClass(token, isKey)}>{token}</span>);
    index = start + token.length;
  }

  if (index < text.length) {
    parts.push(text.slice(index));
  }

  return parts;
}

export default function Data() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [runs, setRuns] = createSignal<Run[]>([]);
  const [dataItems, setDataItems] = createSignal<DataItem[]>([]);
  const pageSize = 20;
  const [page, setPage] = createSignal(1);
  const selectedRunId = () => String(searchParams.run_id ?? "");
  const selectedRun = () => runs().find(run => String(run.id) === selectedRunId());
  const totalPages = () => Math.max(1, Math.ceil(dataItems().length / pageSize));
  const currentPage = () => Math.min(page(), totalPages());
  const pageDataItems = createMemo(() => {
    const start = (currentPage() - 1) * pageSize;
    return dataItems().slice(start, start + pageSize);
  });

  const loadRuns = async () => {
    const response = await fetch("/api/runs");
    if (!response.ok) {
      return;
    }
    const data = (await response.json()) as { runs: Run[] };
    setRuns(data.runs);
  };

  const loadData = async (runId = selectedRunId()) => {
    if (!runId) {
      setDataItems([]);
      return;
    }
    const response = await fetch(`/api/data?run_id=${runId}`);
    if (!response.ok) {
      return;
    }
    const data = (await response.json()) as { dataItems: DataItem[] };
    setDataItems(data.dataItems);
  };

  onMount(() => {
    void loadRuns().then(() => loadData());
    const timer = window.setInterval(() => {
      void loadRuns();
      void loadData();
    }, 2000);
    onCleanup(() => window.clearInterval(timer));
  });

  return (
    <RunViewerLayout
      currentTab="data"
      title="Data"
      description="Items emitted by crawler runs"
      action={<Button type="button" disabled={!selectedRunId()}>Export JSONL</Button>}
      runs={runs}
      selectedRunId={selectedRunId}
      selectedRun={selectedRun}
      emptyContentTitle="Data items"
      emptySelectionText="Select a run to view data."
      onSelectRun={run => {
        navigate(`/data?run_id=${run.id}`);
        setPage(1);
        void loadData(String(run.id));
      }}
    >
      <div class="grid min-w-0 gap-3">
        <For each={pageDataItems()} fallback={<div class="text-sm text-gray-500">No data items yet.</div>}>
          {item => (
            <article class="min-w-0 overflow-hidden rounded-lg border border-gray-700 bg-gray-900 p-2">
              <div class="mb-1.5 flex min-w-0 flex-wrap items-center justify-between gap-2 text-xs">
                <a class="min-w-0 truncate text-sky-400 hover:text-sky-300" href={item.url} title={item.url}>
                  {item.url}
                </a>
              </div>
              <pre class="json-output">{highlightJson(item.item)}</pre>
            </article>
          )}
        </For>
      </div>
      <Pagination
        page={currentPage()}
        pageSize={pageSize}
        totalItems={dataItems().length}
        itemLabel="items"
        onPageChange={setPage}
      />
    </RunViewerLayout>
  );
}
