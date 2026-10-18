import { pythonJson } from "./python-json";
import { pythonCommand } from "./python";
import { savedSettings } from "./settings";
import { store } from "./store";
import { sqlite } from "./db";
import { prometheusUrl, type MonitoringConnection, type PanelData, type PanelId, type MetricSeries } from "../monitoring";

let connectionCache: { key: string; expires: number; value: Promise<MonitoringConnection> } | undefined;
export function clearMonitoringCache() { connectionCache = undefined; }
export async function monitoringConnection(): Promise<MonitoringConnection> {
  const saved = savedSettings().monitoring.prometheusUrl;
  if (saved) return { prometheusUrl: saved, source: "database" };
  const key = JSON.stringify([pythonCommand(), process.env.WEBUSE_CONFIG_DIR || process.cwd(), process.env.WEBUSE_PROMETHEUS_URL]);
  if (connectionCache?.key === key && connectionCache.expires > Date.now()) return connectionCache.value;
  const value = pythonJson<MonitoringConnection>("webuse.monitoring", { action: "config" }).then(result => {
    const url = prometheusUrl(result.prometheusUrl);
    return { ...result, prometheusUrl: url, source: url || result.error ? result.source : "not configured" };
  }).catch(() => ({ prometheusUrl: "", source: "unavailable", error: "Cannot read monitoring configuration. Check the Python environment and .webuserc.yaml." }));
  connectionCache = { key, value, expires: Date.now() + 10_000 };
  return value;
}

type PromResult = { error?: string; warnings?: string[]; data?: { resultType: string; result: { metric: Record<string, string>; value?: [number, string]; values?: [number, string][] }[] } };
type Query = { query: string; start?: number; end?: number; step?: number; time?: number };
export async function testMonitoringConnection(signal?: AbortSignal) {
  const connection = await monitoringConnection();
  if (!connection.prometheusUrl) return { ...connection, connected: false, message: connection.error || "Prometheus is not configured." };
  const [result] = await pythonJson<PromResult[]>("webuse.monitoring", { url: connection.prometheusUrl, queries: [{ query: "vector(1)" }] }, signal);
  const connected = !result?.error && result?.data?.resultType === "vector";
  return { ...connection, connected, message: result?.error || (connected ? "Prometheus is reachable. Execution telemetry depends on crawler instrumentation." : "The endpoint did not return a valid Prometheus response.") };
}

export function executionRange(execution: NonNullable<ReturnType<typeof store.getJob>>, start?: number, end?: number, points = 600) {
  const lower = execution.startedAtMs / 1000;
  // Include two scrape intervals to collect final events from short executions.
  const upper = Math.max(lower, Math.min(Date.now() / 1000, execution.finishedAtMs ? execution.finishedAtMs / 1000 + 10 : Infinity));
  if ((start !== undefined && !Number.isFinite(start)) || (end !== undefined && !Number.isFinite(end)) || !Number.isFinite(points)) throw new Error("Invalid time range.");
  const from = Math.max(lower, start ?? lower);
  const to = Math.min(upper, end ?? upper);
  if (to < from) throw new Error("The selected interval is outside this execution.");
  return { start: from, end: to, step: Math.max(1, Math.ceil((to - from) / Math.max(50, Math.min(1000, points)))) };
}

export function normalizeSeries(result: PromResult, name: string, unit: string): MetricSeries[] {
  if (!result.data || !["matrix", "vector"].includes(result.data.resultType) || !Array.isArray(result.data.result)) return [];
  return result.data.result.slice(0, 50).map(series => ({
    name: [name, ...Object.entries(series.metric || {}).filter(([key]) => key !== "__name__").map(([key, value]) => `${key}=${value}`)].join(" · "), unit,
    values: (series.values || (series.value ? [series.value] : [])).map(([time, value]) => [time * 1000, Number.isFinite(Number(value)) ? Number(value) : null]),
  }));
}

type Job = NonNullable<ReturnType<typeof store.getJob>>;
function summary(job: Job) { return job.metadata.monitoring as { totals?: Record<string, number>; spiders?: string[]; lastActivity?: number } | undefined; }

export async function executionPanel(job: Job, panel: PanelId, range: ReturnType<typeof executionRange>, signal?: AbortSignal): Promise<PanelData> {
  const base: PanelData = { series: [], fetchedAt: Date.now() };
  const selector = `{webuse_instance=${JSON.stringify(store.monitoringInstance())},project_id="${job.projectId}",execution_id="${job.id}"}`;
  const rateWindow = Math.max(20, range.step * 4);
  const metric = (name: string) => `webuse_${name}${selector}`;
  const rate = (name: string) => `sum(rate(${metric(name)}[${rateWindow}s]))`;
  const total = (name: string) => `sum(${metric(name)})`;
  const definitions: { query: string; name: string; unit: string; instant?: boolean }[] = [];
  const add = (name: string, query: string, unit = "", instant = false) => definitions.push({ name, query, unit, instant });

  if (panel === "quality") {
    const samples = store.listDataItems(job.id, 100).map(row => row.item as Record<string, unknown>);
    const fields = [...new Set(samples.flatMap(item => Object.keys(item)))].slice(0, 30);
    const duplicates = samples.length - new Set(samples.map(item => JSON.stringify(Object.keys(item).sort().map(key => [key, item[key]])))).size;
    return { ...base, stats: [{ label: "Sampled items", value: samples.length }, { label: "Exact duplicates in sample", value: duplicates }], columns: ["Field", "Present", "Missing / empty"], rows: fields.map(field => {
      const present = samples.filter(item => item[field] !== null && item[field] !== undefined && item[field] !== "").length;
      return [field, present, samples.length - present];
    }), message: samples.length ? "Completeness of the first 100 saved items. Missing values are not necessarily schema violations." : "No saved items to inspect yet." };
  }
  if (panel === "errors") {
    const rows = sqlite.prepare("SELECT stream, message, created_at FROM logs WHERE job_id = ? AND created_at >= ? AND created_at <= ? ORDER BY id DESC LIMIT 100").all(job.id, range.start * 1000, range.end * 1000) as { stream: string; message: string; created_at: number }[];
    return { ...base, columns: ["Time", "Stream", "Message"], rows: rows.map(row => [new Date(row.created_at).toISOString(), row.stream, row.message]), message: "Latest 100 log lines in the selected interval. stderr is a stream, not an error classification." };
  }
  if (panel === "llm") return { ...base, message: "Crawler LLM usage is not instrumented yet. Harness conversation usage is separate from this execution." };
  if (panel === "insights") {
    const totals = summary(job)?.totals;
    const findings = [job.status === "failed" ? "Execution failed. Inspect the logs and exit details." : "", totals?.request_finished && !job.items ? "Requests completed but no items were saved. Check selectors and pipelines." : "", totals?.item_dropped ? `${totals.item_dropped} items were dropped by pipelines.` : ""].filter(Boolean);
    return { ...base, columns: ["Finding"], rows: findings.map(value => [value]), message: "Rule-based observations from execution evidence; no model calls. Absence of findings does not establish data quality." };
  }
  if (panel === "progress") {
    add("Requests completed", total("request_finished_total"), "", true);
    add("Queued", total("state_queue_size"), "", true);
    add("In flight", total("request_in_flight"), "", true);
    add("Last activity", `max(${metric("last_activity")})`, "timestamp", true);
    const snapshot = summary(job);
    if (job.finishedAtMs && snapshot?.totals) return { ...base, stats: [
      { label: "Requests completed", value: snapshot.totals.request_finished ?? null },
      { label: "Items saved", value: job.items },
      { label: "Request errors", value: snapshot.totals.request_error ?? null },
      { label: "Last activity", value: snapshot.lastActivity ? new Date(snapshot.lastActivity).toISOString() : null },
    ], message: `Final recorded counts. Spiders: ${snapshot.spiders?.join(", ") || "unavailable"}.` };
  }
  if (panel === "throughput") {
    add("Requests", rate("request_finished_total"), "/s");
    add("Items processed", rate("item_processed_total"), "/s");
  }
  if (panel === "http") {
    add("Responses", `sum by (status) (rate(${metric("response_received_total")}[${rateWindow}s]))`, "/s");
    add("Request errors", rate("request_error_total"), "/s");
    for (const quantile of [0.5, 0.95]) add(`Latency p${quantile * 100}`, `histogram_quantile(${quantile}, sum by (le) (rate(${metric("request_duration_bucket")}[${rateWindow}s])))`, "s");
  }
  if (panel === "extraction") {
    for (const [name, counter] of [["Extracted", "item_extracted"], ["Processed", "item_processed"], ["Dropped", "item_dropped"], ["Item errors", "item_error"], ["Parse errors", "parse_error"], ["Pipeline errors", "pipeline_error"]]) add(name, rate(`${counter}_total`), "/s");
    for (const name of ["parse", "pipeline"]) add(`${name} mean duration`, `sum(rate(${metric(`${name}_duration_sum`)}[${rateWindow}s])) / sum(rate(${metric(`${name}_duration_count`)}[${rateWindow}s]))`, "s");
  }
  if (panel === "resources") {
    add("CPU cores", `max(clamp_min(deriv(${metric("process_cpu_seconds")}[${rateWindow}s]), 0))`, "cores");
    add("Peak RSS", `max(${metric("process_peak_rss_bytes")})`, "bytes");
    add("Download", rate("downloaded_bytes_total"), "bytes/s");
  }
  const connection = await monitoringConnection();
  if (!connection.prometheusUrl) return { ...base, ...(panel === "progress" ? { stats: [{ label: "Items saved", value: job.items }] } : {}), message: connection.error || "Prometheus is not configured. Open Settings → Monitoring." };
  const queries: Query[] = definitions.map(def => def.instant ? { query: def.query, time: range.end } : { query: def.query, ...range });
  const results = await pythonJson<PromResult[]>("webuse.monitoring", { url: connection.prometheusUrl, queries }, signal);
  const errors = results.map(result => result.error).filter((error): error is string => !!error);
  const warnings = [...new Set([...errors, ...results.flatMap(result => result.warnings || [])])];
  const series = results.flatMap((result, index) => normalizeSeries(result, definitions[index].name, definitions[index].unit));
  if (panel === "progress") return { ...base, warnings, stats: [
    ...definitions.map((def, i) => { const value = normalizeSeries(results[i] || {}, def.name, def.unit)[0]?.values.at(-1)?.[1] ?? null; return { label: def.name, value: def.unit === "timestamp" && value !== null ? new Date(value * 1000).toISOString() : value }; }),
    { label: "Items saved", value: job.items },
  ], message: "Live counts from the execution's telemetry; items saved comes from SQLite." };
  return { ...base, series, warnings, message: series.some(item => item.values.some(([, value]) => value !== null)) ? undefined : "No telemetry in this interval. This may be an older or uninstrumented execution, expired history, or too few scrapes for a rate." };
}
