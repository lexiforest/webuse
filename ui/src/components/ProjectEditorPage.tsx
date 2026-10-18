import { useParams } from "@solidjs/router";
import { Show, createEffect, createSignal, onCleanup } from "solid-js";

import ProjectForm, { type ProjectFormValue } from "~/components/ProjectForm";
import Layout from "~/layout/dashboard";

type ProjectDetail = ProjectFormValue & {
  id: number;
};

type ProjectEditorPageProps = {
  defaultTab: "harness" | "settings" | "files" | "visual";
};

export default function ProjectEditorPage(props: ProjectEditorPageProps) {
  const params = useParams();
  const [project, setProject] = createSignal<ProjectDetail>();
  const [loading, setLoading] = createSignal(true);
  const [error, setError] = createSignal<string>();

  createEffect(() => {
    const id = params.id;
    const controller = new AbortController();
    onCleanup(() => controller.abort());
    setProject(undefined);
    setLoading(true);
    setError(undefined);
    void (async () => {
      try {
        const response = await fetch(`/api/projects?id=${id}`, { signal: controller.signal });
        if (!response.ok) {
          const data = (await response.json().catch(() => ({}))) as { error?: string };
          throw new Error(data.error || `Failed to load project (${response.status})`);
        }

        const data = (await response.json()) as { project: ProjectDetail };
        if (!controller.signal.aborted) setProject(data.project);
      } catch (err) {
        if (!controller.signal.aborted) setError(err instanceof Error ? err.message : "Failed to load project");
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    })();
  });

  return (
    <Layout currentTab="projects">
      <div class="flex min-h-0 flex-1 flex-col">
        <Show
          when={project()}
          keyed
          fallback={
            <div class="rounded-lg border border-gray-700 bg-gray-900 p-6 text-sm text-gray-400">
              {loading() ? "Loading project..." : error() || "Project not found."}
            </div>
          }
        >
          {value => (
            <ProjectForm
              defaultTab={props.defaultTab}
              endpoint={`/api/projects?id=${value.id}`}
              initialValue={value}
              method="PUT"
              projectId={value.id}
              submitLabel="Save project"
              tabBasePath={`/projects/${value.id}`}
            />
          )}
        </Show>
      </div>
    </Layout>
  );
}
