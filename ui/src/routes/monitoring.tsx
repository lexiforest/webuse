import { A, useSearchParams } from "@solidjs/router";
import { useQuery, useQueryClient } from "@tanstack/solid-query";
import { For, Show, Suspense, createEffect, createMemo, createSignal, on, onMount } from "solid-js";
import Layout from "~/layout/dashboard";
import { Button } from "~/components/ui/button";
import { Select, SelectContent, SelectItem, SelectLabel, SelectTrigger, SelectValue } from "~/components/ui/select";
import ValidationBadge from "~/components/ValidationBadge";
import MetricChart from "~/components/MetricChart";
import { panels, defaultPanels, type PanelData, type PanelId, type MonitoringConnection } from "~/lib/monitoring";

type Execution = { id: number; projectId: number; project: string; status: string; duration: string; startedAt: string; startedAtMs: number; finishedAtMs: number | null; items: number; metadata: Record<string, unknown> };
type Overview = { execution: Execution; enabledPanels: PanelId[]; connection: MonitoringConnection };
function TimeSelect(props: { label: string; value: number; options: { value: number; label: string }[]; onChange: (value: number) => void }) {
  return <Select class="flex items-center gap-2" options={props.options} value={props.options.find(option => option.value === props.value)} optionValue="value" optionTextValue="label" onChange={option => option && props.onChange(option.value)} itemComponent={item => <SelectItem item={item.item}>{item.item.rawValue.label}</SelectItem>}>
    <SelectLabel class="text-xs text-gray-400">{props.label}</SelectLabel><SelectTrigger class="w-40"><SelectValue<{ label: string }>>{state => state.selectedOption().label}</SelectValue></SelectTrigger><SelectContent />
  </Select>;
}
async function read<T>(url: string, signal?: AbortSignal, body?: unknown): Promise<T> {
  const response = await fetch(url, { signal, ...(body === undefined ? {} : { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }) });
  if (!response.ok) { const data = await response.json(); throw new Error(data.error || "Monitoring request failed."); }
  return response.json();
}

function Panel(props: { id: PanelId; execution: number; range: string; refresh: number; onRange: (start: number, end: number) => void }) {
  const query = useQuery(() => ({
    queryKey: ["monitoring-panel", props.execution, props.id, props.range],
    queryFn: ({ signal }) => read<PanelData>(`/api/monitoring?execution_id=${props.execution}&panel=${props.id}${props.range}`, signal),
    refetchInterval: props.refresh || false,
    placeholderData: (previous, query) => query?.queryKey[1] === props.execution ? previous : undefined,
  }));
  const groups = createMemo(() => [...new Set(query.data?.series.map(series => series.unit) || [])]);
  return <section class="min-w-0 rounded-lg border border-gray-800 bg-gray-900/40 p-4" aria-label={panels.find(panel => panel.id === props.id)?.title}>
    <div class="mb-4 flex items-center justify-between gap-2"><h2 class="font-semibold text-gray-100">{panels.find(panel => panel.id === props.id)?.title}</h2><span class="text-xs text-gray-500">{query.isFetching ? "Updating…" : query.data ? `Updated ${new Date(query.dataUpdatedAt).toLocaleTimeString()}` : ""}</span></div>
    <Show when={query.isError}><p class="mb-3 text-sm text-red-300">{query.error?.message} <button class="underline" onClick={() => void query.refetch()}>Retry</button></p></Show>
    <Suspense fallback={<p class="text-sm text-gray-400">Loading panel…</p>}>
      <Show when={query.data}>{data => <>
        <Show when={data().stats?.length}><div class="mb-4 grid grid-cols-2 gap-4"><For each={data().stats}>{stat => <div><div class="text-xs text-gray-400">{stat.label}</div><div class="mt-1 text-lg text-white">{stat.value === null ? "Unavailable" : typeof stat.value === "number" ? stat.value.toLocaleString() : stat.value}</div></div>}</For></div></Show>
        <For each={groups()}>{unit => <MetricChart group={`execution-${props.execution}`} series={data().series.filter(series => series.unit === unit)} onRange={props.onRange} />}</For>
        <Show when={data().rows?.length}><div class="max-h-96 overflow-auto"><table class="w-full text-left text-xs"><thead class="sticky top-0 bg-gray-900 text-gray-400"><tr><For each={data().columns}>{column => <th class="p-2 font-medium">{column}</th>}</For></tr></thead><tbody><For each={data().rows}>{row => <tr class="border-t border-gray-800"><For each={row}>{cell => <td class="max-w-lg break-words p-2 align-top whitespace-pre-wrap">{cell ?? "Unavailable"}</td>}</For></tr>}</For></tbody></table></div></Show>
        <Show when={data().message}><p class="mt-3 break-words text-xs text-gray-400">{data().message}</p></Show>
        <For each={data().warnings}>{warning => <p class="mt-2 text-xs text-amber-300">{warning}</p>}</For>
      </>}</Show>
    </Suspense>
  </section>;
}

export default function Monitoring() {
  const [params] = useSearchParams();
  const id = () => Number(params.execution_id);
  const [ready, setReady] = createSignal(false);
  const [refresh, setRefresh] = createSignal(15000);
  const [period, setPeriod] = createSignal(0);
  const [selection, setSelection] = createSignal<[number, number]>();
  createEffect(on(id, () => setSelection(undefined)));
  const [saving, setSaving] = createSignal(false);
  const [error, setError] = createSignal("");
  const client = useQueryClient();
  const overview = useQuery(() => ({ queryKey: ["monitoring", id()], queryFn: ({ signal }) => read<Overview>(`/api/monitoring?execution_id=${id()}`, signal), enabled: ready() && Number.isSafeInteger(id()) && id() > 0, refetchInterval: refresh() || false }));
  onMount(() => setReady(true));
  const range = createMemo(() => {
    const job = overview.data?.execution;
    if (!job) return "";
    const chosen = selection();
    if (chosen) return `&start=${chosen[0]}&end=${chosen[1]}`;
    if (!period()) return "";
    const end = Math.min(Date.now(), job.finishedAtMs ? job.finishedAtMs + 10000 : Infinity) / 1000;
    return `&start=${Math.max(job.startedAtMs / 1000, end - period())}&end=${end}`;
  });
  const savePanels = async (enabledPanels: PanelId[]) => {
    const data = overview.data;
    if (!data) return;
    setSaving(true); setError("");
    try {
      await read(`/api/monitoring-panels?project_id=${data.execution.projectId}`, undefined, { enabledPanels });
      client.setQueryData(["monitoring", id()], { ...data, enabledPanels });
      await client.invalidateQueries({ queryKey: ["monitoring"] });
    } catch (error) { setError(error instanceof Error ? error.message : String(error)); }
    finally { setSaving(false); }
  };
  const selectRange = (start: number, end: number) => { if (end > start) setSelection([start, end]); };
  const selectClass = "rounded border border-gray-700 bg-gray-900 px-2 py-1.5 text-sm text-gray-200";
  return <Layout currentTab="executions">
    <Show when={Number.isSafeInteger(id()) && id() > 0} fallback={<p>Select an execution from <A href="/executions" class="text-sky-400">Executions</A>.</p>}>
      <Show when={overview.isError}><p class="text-red-300">{overview.error?.message} <button class="underline" onClick={() => void overview.refetch()}>Retry</button></p></Show>
      <Suspense fallback={<p class="text-gray-400">Loading execution…</p>}>
        <Show when={overview.data}>{data => <>
          <header class="mb-6 border-b border-gray-800 pb-5">
            <div class="flex flex-wrap items-start justify-between gap-3">
              <div class="pr-40"><div class="mb-1 text-xs text-gray-400">Execution #{data().execution.id}</div><h1 class="break-words text-2xl font-semibold text-white">{data().execution.project}</h1>
                <div class="mt-2 flex flex-wrap items-center gap-3 text-sm text-gray-400"><span class="text-sky-300">{data().execution.status}</span><span>{data().execution.duration}</span><span>{data().execution.items.toLocaleString()} items saved</span><span>{data().execution.metadata.scheduled ? "Scheduled" : data().execution.metadata.assistantSample ? "Harness validation" : "Manual"}</span><ValidationBadge metadata={data().execution.metadata} /></div>
                <p class="mt-2 text-xs text-gray-500">Started {new Date(data().execution.startedAtMs).toLocaleString()}{data().execution.metadata.reason ? ` · ${String(data().execution.metadata.reason)}` : ""}</p>
              </div>
            </div>
            <div class="mt-5 flex flex-wrap items-center gap-3">
              <TimeSelect label="Range" value={period()} options={[{ value: 0, label: "Full execution" }, { value: 300, label: "Last 5 minutes" }, { value: 900, label: "Last 15 minutes" }, { value: 3600, label: "Last hour" }]} onChange={value => { setPeriod(value); setSelection(undefined); }} />
              <TimeSelect label="Refresh" value={refresh()} options={[{ value: 0, label: "Off" }, { value: 5000, label: "5 seconds" }, { value: 15000, label: "15 seconds" }, { value: 30000, label: "30 seconds" }]} onChange={setRefresh} />
              <Button variant="outline" size="sm" onClick={() => { void client.invalidateQueries({ queryKey: ["monitoring", id()] }); void client.invalidateQueries({ queryKey: ["monitoring-panel", id()] }); }}>Refresh now</Button>
              <Button as={A} href={`/logs?execution_id=${id()}`} variant="outline" size="sm">Logs</Button><Button as={A} href={`/data?execution_id=${id()}`} variant="outline" size="sm">Data</Button>
              <details class="relative"><summary class={`${selectClass} cursor-pointer`}>Panels</summary><div class="absolute right-0 z-20 mt-2 w-60 rounded-lg border border-gray-700 bg-gray-950 p-3 shadow-xl"><For each={panels}>{panel => <label class="flex cursor-pointer items-center gap-2 py-2 text-sm"><input type="checkbox" checked={data().enabledPanels.includes(panel.id)} disabled={saving()} onChange={event => void savePanels(event.currentTarget.checked ? panels.filter(item => item.id === panel.id || data().enabledPanels.includes(item.id)).map(item => item.id) : data().enabledPanels.filter(id => id !== panel.id))} />{panel.title}</label>}</For><Button size="sm" variant="outline" disabled={saving()} onClick={() => void savePanels(defaultPanels)}>Restore defaults</Button><p class="mt-2 text-xs text-gray-500">Saved for this project.</p></div></details>
              <Show when={selection()}><Button variant="outline" size="sm" onClick={() => setSelection(undefined)}>Reset zoom</Button><span class="text-xs text-gray-400">{new Date(selection()![0] * 1000).toLocaleTimeString()} – {new Date(selection()![1] * 1000).toLocaleTimeString()}</span></Show>
            </div>
            <p class="mt-3 text-xs text-gray-500">Prometheus: {data().connection.prometheusUrl ? `${data().connection.prometheusUrl} · ${data().connection.source}` : "not configured"} · <A href="/settings#monitoring" class="text-sky-400">Configure</A></p>
            <p class="mt-1 text-xs text-gray-500">Drag a chart's time slider to filter charts and logs. Gaps mean unavailable telemetry.</p>
            <Show when={error()}><p class="mt-3 text-sm text-red-300">{error()}</p></Show>
          </header>
          <div class="grid items-start gap-4 xl:grid-cols-2"><For each={panels.filter(panel => data().enabledPanels.includes(panel.id))}>{panel => <Suspense fallback={<section class="rounded-lg border border-gray-800 p-4 text-sm text-gray-400">Loading {panel.title}…</section>}><Panel id={panel.id} execution={id()} range={range()} refresh={refresh()} onRange={selectRange} /></Suspense>}</For></div>
          <Show when={!data().enabledPanels.length}><p class="text-sm text-gray-400">All panels are hidden. Enable panels from the Panels menu.</p></Show>
        </>}</Show>
      </Suspense>
    </Show>
  </Layout>;
}
