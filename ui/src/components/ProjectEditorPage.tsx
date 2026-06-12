import { useParams } from "@solidjs/router";
import { Show, createSignal, onMount } from "solid-js";

import { ButtonLink } from "~/components/Button";
import ProjectForm, { type ProjectFormValue } from "~/components/ProjectForm";
import Layout from "~/layout/dashboard";

type ProjectDetail = ProjectFormValue & {
  id: number;
};

type ProjectEditorPageProps = {
  defaultTab: "settings" | "files" | "visual";
};

export default function ProjectEditorPage(props: ProjectEditorPageProps) {
  const params = useParams();
  const [project, setProject] = createSignal<ProjectDetail>();
  const [loading, setLoading] = createSignal(true);
  const [error, setError] = createSignal<string>();

  onMount(() => {
    void (async () => {
      try {
        const response = await fetch(`/api/projects?id=${params.id}`);
        if (!response.ok) {
          const data = (await response.json().catch(() => ({}))) as { error?: string };
          throw new Error(data.error || `Failed to load project (${response.status})`);
        }

        const data = (await response.json()) as { project: ProjectDetail };
        setProject(data.project);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load project");
      } finally {
        setLoading(false);
      }
    })();
  });

  return (
    <Layout currentTab="projects">
      <div class="flex min-h-0 flex-1 flex-col">
        <div class="mb-3 flex shrink-0 flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <h1 class="text-3xl font-bold text-sky-400">Edit project</h1>
            <p class="mt-1 text-sm text-gray-400">Update project source files</p>
          </div>
          <ButtonLink href="/projects" size="compact">
            Back to projects
          </ButtonLink>
        </div>

        <Show
          when={project()}
          fallback={
            <div class="rounded-lg border border-gray-700 bg-gray-900 p-6 text-sm text-gray-400">
              {loading() ? "Loading project..." : error() || "Project not found."}
            </div>
          }
        >
          {value => (
            <ProjectForm
              defaultTab={value().type === "git" && props.defaultTab === "files" ? "visual" : props.defaultTab}
              endpoint={`/api/projects?id=${value().id}`}
              initialValue={value()}
              method="PUT"
              projectId={value().id}
              submitLabel="Save"
              tabBasePath={`/projects/${value().id}`}
            />
          )}
        </Show>
      </div>
    </Layout>
  );
}
