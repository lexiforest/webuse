import { createEffect, createSignal, onCleanup, onMount } from "solid-js";
import type { EChartsType } from "echarts/core";
import type { MetricSeries } from "~/lib/monitoring";

export default function MetricChart(props: { series: MetricSeries[]; group: string; onRange: (start: number, end: number) => void }) {
  let element!: HTMLDivElement;
  const [chart, setChart] = createSignal<EChartsType>();
  const [error, setError] = createSignal("");
  onMount(() => {
    let disposed = false;
    let observer: ResizeObserver | undefined;
    let instance: EChartsType | undefined;
    void import("~/lib/charts").then(ec => {
      if (disposed) return;
      instance = ec.init(element, undefined, { renderer: "canvas" });
      instance.group = props.group;
      ec.connect(props.group);
      instance.on("datazoom", (event: unknown) => {
        const data = event as { start?: number; end?: number; batch?: { start?: number; end?: number }[] };
        const zoom = data.batch?.[0] || data;
        const times = props.series.flatMap(series => series.values.map(([time]) => time));
        const first = times.reduce((a, b) => Math.min(a, b), Infinity); const last = times.reduce((a, b) => Math.max(a, b), -Infinity);
        if (last > first && zoom.start !== undefined && zoom.end !== undefined) {
          props.onRange((first + (last - first) * zoom.start / 100) / 1000, (first + (last - first) * zoom.end / 100) / 1000);
        }
      });
      observer = new ResizeObserver(() => instance?.resize());
      observer.observe(element);
      setChart(instance);
    }).catch(() => setError("Unable to load the chart. Reload to retry."));
    onCleanup(() => { disposed = true; observer?.disconnect(); instance?.dispose(); });
  });
  createEffect(() => {
    const instance = chart();
    const series = props.series;
    instance?.setOption({
      animation: false, backgroundColor: "transparent", aria: { enabled: true },
      color: ["#38bdf8", "#34d399", "#a78bfa", "#fb923c", "#fb7185", "#facc15"],
      textStyle: { color: "#9ca3af", fontFamily: "inherit" },
      tooltip: { trigger: "axis", renderMode: "richText", axisPointer: { type: "line" } },
      legend: { type: "scroll", textStyle: { color: "#cbd5e1" }, top: 0 },
      grid: { left: 60, right: 15, top: 50, bottom: 65 },
      xAxis: { type: "time", axisLine: { lineStyle: { color: "#374151" } } },
      yAxis: { type: "value", name: series[0]?.unit || "", splitLine: { lineStyle: { color: "#1f2937" } } },
      dataZoom: [{ type: "slider", bottom: 5, height: 20, start: 0, end: 100, brushSelect: false, realtime: false, textStyle: { color: "#9ca3af" } }],
      series: series.map(item => ({ name: item.name, type: "line", showSymbol: false, connectNulls: false, data: item.values })),
    }, { notMerge: true, silent: true });
  });
  return <div><div ref={element} class="h-64 w-full" role="img" aria-label={`Time series: ${props.series.map(item => item.name).join(", ")}`} /><span class="text-sm text-red-300">{error()}</span></div>;
}
