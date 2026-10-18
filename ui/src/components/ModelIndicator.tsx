import { A } from "@solidjs/router";
import { createContext, createSignal, onCleanup, onMount, useContext, type Accessor, type ParentProps } from "solid-js";

export type ModelStatus = {
  connected: boolean;
  model: string;
  baseUrl: string;
  source: string;
  message: string;
  localModels: { model: string; baseUrl: string; provider: string }[];
  limits?: { contextWindow?: number; maxOutputTokens?: number; contextSource: string; outputSource: string; responseTokens?: number };
};

const ModelStatusContext = createContext<{ status: Accessor<ModelStatus | undefined>; loading: Accessor<boolean> }>();

export function ModelStatusProvider(props: ParentProps) {
  const [status, setStatus] = createSignal<ModelStatus>();
  const [loading, setLoading] = createSignal(true);
  onMount(() => {
    let disposed = false;
    let pending: AbortController | undefined;
    const refresh = async (force = false) => {
      if (pending && !force) return;
      pending?.abort();
      const request = new AbortController();
      pending = request;
      try {
        const response = await fetch(`/api/models${force ? "?refresh=1" : ""}`, { signal: request.signal });
        if (!response.ok) throw new Error("Model status unavailable");
        const value = await response.json() as ModelStatus;
        if (!disposed && !request.signal.aborted) setStatus(value);
      } catch {
        if (!disposed && !request.signal.aborted) setStatus(undefined);
      } finally {
        if (pending === request) pending = undefined;
        if (!disposed && !request.signal.aborted) setLoading(false);
      }
    };
    void refresh();
    const timer = setInterval(() => void refresh(), 15_000);
    const modelChanged = () => void refresh(true);
    window.addEventListener("webuse:model-changed", modelChanged);
    onCleanup(() => { disposed = true; pending?.abort(); clearInterval(timer); window.removeEventListener("webuse:model-changed", modelChanged); });
  });
  return <ModelStatusContext.Provider value={{ status, loading }}>{props.children}</ModelStatusContext.Provider>;
}

export default function ModelIndicator() {
  const { status, loading } = useContext(ModelStatusContext)!;
  return (
    <A href="/settings#model" aria-label="Configure model" title={status()?.message || "Configure model access"}
      class="inline-flex max-w-full items-center gap-2 rounded border border-gray-600 bg-gray-900 px-3 py-1.5 text-xs text-gray-200 hover:border-sky-500">
      <span aria-hidden="true" class={`h-2 w-2 shrink-0 rounded-full ${status()?.connected ? status()?.limits?.contextWindow ? "bg-emerald-400" : "bg-amber-400" : "bg-gray-500"}`} />
      <span class="truncate" aria-live="polite">
        {loading() ? "Checking models…" : status()?.connected ? status()!.model : `Disconnected${status()?.model ? ` · ${status()!.model}` : ""}`}
      </span>
    </A>
  );
}
