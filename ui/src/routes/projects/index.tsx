import { For, Show, createSignal, onMount } from "solid-js";
import { useNavigate } from "@solidjs/router";

import Button, { ButtonLink } from "~/components/Button";
import Layout from "~/layout/dashboard";

type ProjectRow = {
  id: number;
  name: string;
  type: "source" | "git";
  target: string;
  status: string;
  updatedAt: string;
};

export default function Projects() {
  const navigate = useNavigate();
  const [projects, setProjects] = createSignal<ProjectRow[]>([]);
  const [loading, setLoading] = createSignal(true);
  const [error, setError] = createSignal<string>();

  const loadProjects = async () => {
    setError(undefined);

    try {
      const response = await fetch("/api/projects");
      if (!response.ok) {
        throw new Error(`Failed to load projects (${response.status})`);
      }

      const data = (await response.json()) as { projects: ProjectRow[] };
      setProjects(data.projects);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load projects");
    } finally {
      setLoading(false);
    }
  };

  const generateExample = () => {
    setError(undefined);

    void (async () => {
      try {
        const response = await fetch("/api/projects", { method: "POST" });
        if (!response.ok) {
          throw new Error(`Failed to create project (${response.status})`);
        }

        const data = (await response.json()) as { project: ProjectRow };
        setProjects(current => [data.project, ...current]);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to create project");
      }
    })();
  };

  const deleteProject = (id: number) => {
    if (!window.confirm("Delete this project? This cannot be undone.")) {
      return;
    }

    setError(undefined);

    void (async () => {
      try {
        const response = await fetch(`/api/projects?id=${id}`, { method: "DELETE" });
        if (!response.ok) {
          throw new Error(`Failed to delete project (${response.status})`);
        }

        setProjects(current => current.filter(project => project.id !== id));
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to delete project");
      }
    })();
  };

  onMount(() => {
    void loadProjects();
  });

  return (
    <Layout currentTab="projects">
      <div class="mb-6 flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 class="text-3xl font-bold text-sky-400">Projects</h1>
          <p class="mt-1 text-sm text-gray-400">Source tarballs and git-backed crawl tasks</p>
        </div>
        <ButtonLink href="/projects/create" variant="primary">
          Create project
        </ButtonLink>
      </div>

      <section class="rounded-lg border border-gray-700 bg-gray-900 p-4">
        <Show when={error()}>
          {message => (
            <div class="mb-4 rounded border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-200">
              {message()}
            </div>
          )}
        </Show>
        <div class="overflow-x-auto">
          <table class="data-table">
            <thead>
              <tr>
                <th>ID</th>
                <th>Name</th>
                <th>Type</th>
                <th>Source</th>
                <th>Status</th>
                <th>Updated</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              <For
                each={projects()}
                fallback={
                  <tr>
                    <td class="py-10 text-center text-gray-500" colspan="7">
                      {loading() ? "Loading projects..." : "No projects yet."}
                    </td>
                  </tr>
                }
              >
                {project => (
                      <tr
                        class="cursor-pointer transition-colors hover:bg-gray-800/70"
                        onClick={() => navigate(`/projects/${project.id}`)}
                      >
                        <td>#{project.id}</td>
                        <td class="font-medium text-white">{project.name}</td>
                    <td>{project.type}</td>
                    <td class="max-w-[420px] truncate">{project.target}</td>
                    <td>{project.status}</td>
                    <td>{project.updatedAt}</td>
                    <td>
                      <Button
                        size="compact"
                        variant="danger"
                        type="button"
                        onClick={event => {
                          event.stopPropagation();
                          deleteProject(project.id);
                        }}
                      >
                        Delete
                      </Button>
                    </td>
                  </tr>
                )}
              </For>
            </tbody>
          </table>
        </div>
        <Show when={!loading() && projects().length === 0}>
          <div class="mt-4 flex justify-center border-t border-gray-800 pt-4">
            <Button variant="primary" type="button" onClick={generateExample}>
              Generate example project
            </Button>
          </div>
        </Show>
      </section>
    </Layout>
  );
}
