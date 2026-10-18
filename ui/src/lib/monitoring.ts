export const panels = [
  { id: "progress", title: "Crawl progress", default: true },
  { id: "throughput", title: "Throughput", default: true },
  { id: "http", title: "HTTP health", default: true },
  { id: "extraction", title: "Extraction & pipelines", default: true },
  { id: "quality", title: "Data quality", default: true },
  { id: "errors", title: "Errors & logs", default: true },
  { id: "resources", title: "Resources", default: false },
  { id: "llm", title: "LLM usage", default: false },
  { id: "insights", title: "Insights", default: false },
] as const;
export type PanelId = typeof panels[number]["id"];
export const defaultPanels = panels.filter(panel => panel.default).map(panel => panel.id);
export function panelSelection(value: unknown): PanelId[] {
  if (!Array.isArray(value) || value.some(id => !panels.some(panel => panel.id === id))) throw new Error("Unknown monitoring panel.");
  return panels.filter(panel => value.includes(panel.id)).map(panel => panel.id);
}
export type MetricSeries = { name: string; unit: string; values: [number, number | null][] };
export type PanelData = {
  series: MetricSeries[];
  stats?: { label: string; value: number | string | null; unit?: string }[];
  columns?: string[];
  rows?: (string | number | null)[][];
  message?: string;
  warnings?: string[];
  fetchedAt: number;
};
export type MonitoringConnection = { prometheusUrl: string; source: string; error?: string };

export function prometheusUrl(value: unknown) {
  if (value === undefined || value === "") return "";
  if (typeof value !== "string") throw new Error("Prometheus URL must be text.");
  const text = value.trim().replace(/\/+$/, "");
  if (!text) return "";
  try {
    const url = new URL(text);
    if (!["http:", "https:"].includes(url.protocol) || url.username || url.password || url.search || url.hash) throw new Error();
  } catch { throw new Error("Prometheus URL must be an HTTP(S) URL without embedded credentials, a query, or a fragment."); }
  return text;
}
