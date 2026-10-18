import { Show, createSignal, onMount } from "solid-js";
import { A, useNavigate } from "@solidjs/router";
import { FiBarChart2, FiEdit3, FiPlay } from "solid-icons/fi";

import { Button } from "~/components/ui/button";
import TableView from "~/components/TableView";
import Layout from "~/layout/dashboard";

type ProjectRow = {
  id: number;
  name: string;
  target: string;
  cron: string;
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
        window.dispatchEvent(new Event("webuse:projects-changed"));
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to delete project");
      }
    })();
  };

  const runProject = (id: number) => {
    setError(undefined);

    void (async () => {
      try {
        const response = await fetch("/api/executions", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ projectId: id }),
        });
        if (!response.ok) {
          const data = (await response.json().catch(() => ({}))) as { error?: string };
          throw new Error(data.error || `Failed to queue execution (${response.status})`);
        }

        navigate("/executions");
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to queue execution");
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
          <p class="mt-1 text-sm text-gray-400">Project source files and local crawl executions</p>
        </div>
        <Button as={A} href="/projects/create" variant="default">
          Create project
        </Button>
      </div>

      <section class="rounded-lg border border-gray-700 bg-gray-900 p-4">
        <Show when={error()}>
          {message => (
            <div class="mb-4 rounded border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-200">
              {message()}
            </div>
          )}
        </Show>
        <TableView
          items={projects()}
          columns={["ID", "Name", "Target", "Schedule", "Status", "Updated", "Actions"]}
          loading={loading()}
          loadingText="Loading projects..."
          emptyText="No projects yet."
          itemLabel="projects"
          renderRow={project => (
            <tr class="transition-colors hover:bg-gray-800/70">
              <td>#{project.id}</td>
              <td class="font-medium text-white">{project.name}</td>
              <td class="max-w-[420px] truncate">{project.target}</td>
              <td>{project.cron || "Manual"}</td>
              <td>{project.status}</td>
              <td>{project.updatedAt}</td>
              <td class="flex gap-2">
                <Button
                  class="gap-1.5"
                  size="sm"
                  variant="success"
                  type="button"
                  onClick={() => runProject(project.id)}
                >
                  <FiPlay size={13} stroke-width={2} aria-hidden="true" />
                  Run
                </Button>
                <Button variant="outline"
                  class="gap-1.5"
                  size="sm"
                  type="button"
                  onClick={() => navigate(`/executions?project_id=${project.id}`)}
                >
                  <FiBarChart2 size={13} stroke-width={2} aria-hidden="true" />
                  Executions
                </Button>
                <Button variant="outline"
                  class="gap-1.5"
                  size="sm"
                  type="button"
                  onClick={() => navigate(`/projects/${project.id}/files`)}
                >
                  <FiEdit3 size={13} stroke-width={2} aria-hidden="true" />
                  Edit
                </Button>
                <Button
                  size="sm"
                  variant="destructive"
                  type="button"
                  onClick={() => deleteProject(project.id)}
                >
                  Delete
                </Button>
              </td>
            </tr>
          )}
        />
      </section>
    </Layout>
  );
}
