import { For, Show, createMemo, type JSX } from "solid-js";

import { Button } from "~/components/ui/button";
import Layout from "~/layout/dashboard";
import ValidationBadge from "~/components/ValidationBadge";

export type ExecutionSummary = {
  id: number;
  project: string;
  status: "queued" | "running" | "succeeded" | "failed" | "cancelled";
  startedAt: string;
  duration: string;
  items: number;
  metadata?: Record<string, unknown>;
};

type ExecutionViewerLayoutProps = {
  currentTab: string;
  title: string;
  description: string;
  action?: JSX.Element;
  executions: () => ExecutionSummary[];
  selectedExecutionId: () => string;
  selectedExecution: () => ExecutionSummary | undefined;
  emptySelectionText: string;
  emptyContentTitle: string;
  onSelectExecution: (execution: ExecutionSummary) => void;
  onContentEnd?: () => void;
  children: JSX.Element;
};

export default function ExecutionViewerLayout(props: ExecutionViewerLayoutProps) {
  const groupedExecutions = createMemo(() => {
    const groups = new Map<string, ExecutionSummary[]>();
    for (const execution of props.executions()) {
      const projectExecutions = groups.get(execution.project) ?? [];
      projectExecutions.push(execution);
      groups.set(execution.project, projectExecutions);
    }
    return Array.from(groups, ([project, executions]) => ({ project, executions }));
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
            Executions
          </h2>
          <div class="min-h-0 flex-1 space-y-4 overflow-auto pr-1">
            <For each={groupedExecutions()} fallback={<div class="text-sm text-gray-500">No executions yet.</div>}>
              {group => (
                <div>
                  <div class="mb-2 truncate text-sm font-medium text-white">{group.project}</div>
                  <div class="space-y-2">
                    <For each={group.executions}>
                      {execution => {
                        const active = () => String(execution.id) === props.selectedExecutionId();
                        return (
                          <Button variant="outline"
                            class={`w-full justify-start text-left ${active() ? "border-sky-500 bg-sky-500/15 text-white" : ""}`}
                            size="sm"
                            type="button"
                            onClick={() => props.onSelectExecution(execution)}
                          >
                            <span class="flex min-w-0 flex-1 flex-col items-start gap-0.5">
                              <span class="flex w-full items-center gap-2"><span class="truncate">Execution #{execution.id}</span><ValidationBadge metadata={execution.metadata} /></span>
                              <span class="text-[0.7rem] font-normal text-gray-400">
                                {execution.status} - {execution.items} items
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
              <Show when={props.selectedExecution()} fallback={props.emptyContentTitle}>
                {execution => <span class="flex flex-wrap items-center gap-2">Execution #{execution().id} - {execution().project}<ValidationBadge metadata={execution().metadata} /></span>}
              </Show>
            </h2>
            <Show when={props.selectedExecution()}>
              {execution => <div class="text-xs text-gray-500">{execution().startedAt}</div>}
            </Show>
          </div>
          <Show
            when={props.selectedExecutionId()}
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
