import { For, Show, createMemo, type JSX } from "solid-js";

import Button from "~/components/Button";
import Layout from "~/layout/dashboard";

export type RunViewerRun = {
  id: number;
  project: string;
  status: "queued" | "running" | "succeeded" | "failed" | "cancelled";
  startedAt: string;
  duration: string;
  items: number;
};

type RunViewerLayoutProps = {
  currentTab: string;
  title: string;
  description: string;
  action?: JSX.Element;
  runs: () => RunViewerRun[];
  selectedRunId: () => string;
  selectedRun: () => RunViewerRun | undefined;
  emptySelectionText: string;
  emptyContentTitle: string;
  onSelectRun: (run: RunViewerRun) => void;
  onContentEnd?: () => void;
  children: JSX.Element;
};

export default function RunViewerLayout(props: RunViewerLayoutProps) {
  const groupedRuns = createMemo(() => {
    const groups = new Map<string, RunViewerRun[]>();
    for (const run of props.runs()) {
      const projectRuns = groups.get(run.project) ?? [];
      projectRuns.push(run);
      groups.set(run.project, projectRuns);
    }
    return Array.from(groups, ([project, runs]) => ({ project, runs }));
  });

  return (
    <Layout currentTab={props.currentTab}>
      <div class="mb-6 flex shrink-0 flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 class="text-3xl font-bold text-sky-400">{props.title}</h1>
          <p class="mt-1 text-sm text-gray-400">{props.description}</p>
        </div>
        {props.action}
      </div>

      <div class="grid min-h-0 flex-1 gap-4 overflow-hidden lg:grid-cols-[20rem_1fr]">
        <section class="flex min-h-0 flex-col overflow-hidden rounded-lg border border-gray-700 bg-gray-900 p-4">
          <h2 class="mb-3 text-sm font-semibold uppercase tracking-wide text-gray-400">
            Runs
          </h2>
          <div class="min-h-0 flex-1 space-y-4 overflow-auto pr-1">
            <For each={groupedRuns()} fallback={<div class="text-sm text-gray-500">No runs yet.</div>}>
              {group => (
                <div>
                  <div class="mb-2 truncate text-sm font-medium text-white">{group.project}</div>
                  <div class="space-y-2">
                    <For each={group.runs}>
                      {run => {
                        const active = () => String(run.id) === props.selectedRunId();
                        return (
                          <Button
                            class={`w-full justify-start text-left ${active() ? "border-sky-500 bg-sky-500/15 text-white" : ""}`}
                            size="compact"
                            type="button"
                            onClick={() => props.onSelectRun(run)}
                          >
                            <span class="flex min-w-0 flex-1 flex-col items-start gap-0.5">
                              <span class="w-full truncate">Run #{run.id}</span>
                              <span class="text-[0.7rem] font-normal text-gray-400">
                                {run.status} - {run.items} items
                              </span>
                            </span>
                          </Button>
                        );
                      }}
                    </For>
                  </div>
                </div>
              )}
            </For>
          </div>
        </section>

        <section class="flex min-h-0 min-w-0 flex-col overflow-hidden rounded-lg border border-gray-700 bg-gray-950 p-4">
          <div class="mb-3 flex min-h-7 shrink-0 items-center justify-between gap-3">
            <h2 class="text-sm font-semibold uppercase tracking-wide text-gray-400">
              <Show when={props.selectedRun()} fallback={props.emptyContentTitle}>
                {run => `Run #${run().id} - ${run().project}`}
              </Show>
            </h2>
            <Show when={props.selectedRun()}>
              {run => <div class="text-xs text-gray-500">{run().startedAt}</div>}
            </Show>
          </div>
          <Show
            when={props.selectedRunId()}
            fallback={<div class="text-sm text-gray-500">{props.emptySelectionText}</div>}
          >
            <div
              class="min-h-0 flex-1 overflow-auto pr-1"
              onScroll={event => {
                if (!props.onContentEnd) {
                  return;
                }
                const element = event.currentTarget;
                if (element.scrollTop + element.clientHeight >= element.scrollHeight - 80) {
                  props.onContentEnd();
                }
              }}
            >
              {props.children}
            </div>
          </Show>
        </section>
      </div>
    </Layout>
  );
}
