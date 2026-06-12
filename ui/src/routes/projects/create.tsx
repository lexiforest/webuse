import { useNavigate } from "@solidjs/router";
import { Show, createSignal } from "solid-js";
import { FiCode, FiFileText, FiGitBranch } from "solid-icons/fi";

import Button, { ButtonLink } from "~/components/Button";
import Layout from "~/layout/dashboard";

type ProjectType = "yaml" | "python" | "git";

type ProjectResponse = {
  project?: {
    id: number;
    type: ProjectType;
  };
  error?: string;
};

const defaultStartUrl = "https://books.toscrape.com/";

function slugify(value: string) {
  const slug = value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
  return slug || "crawler";
}

function yamlContent(name: string, startUrl: string) {
  return `name: ${name}
spiders:
  ${slugify(name)}:
    start_urls:
      - ${startUrl}
    max_depth: 1
    pages:
      default:
        extract:
          page:
            fields:
              title: title
`;
}

function pythonProjectContent(name: string) {
  return `name: ${name}
spiders:
  ${slugify(name)}:
    path: spiders/${slugify(name)}.py
`;
}

function pythonContent(name: string, startUrl: string) {
  const className = `${slugify(name)
    .split("_")
    .filter(Boolean)
    .map(part => part[0].toUpperCase() + part.slice(1))
    .join("") || "Crawler"}Spider`;

  return `import webuse


class ${className}(webuse.Spider):
    name = "${slugify(name)}"
    start_urls = ["${startUrl}"]

    def parse(self, response):
        title = response.css_first("title")
        yield {
            "url": response.url,
            "title": title.text.strip() if title else "",
        }
`;
}

export default function CreateProject() {
  const navigate = useNavigate();
  const [name, setName] = createSignal("Books to Scrape");
  const [startUrl, setStartUrl] = createSignal(defaultStartUrl);
  const [gitName, setGitName] = createSignal("");
  const [gitUrl, setGitUrl] = createSignal("");
  const [saving, setSaving] = createSignal<ProjectType>();
  const [error, setError] = createSignal<string>();

  const createProject = (type: ProjectType) => {
    setError(undefined);
    setSaving(type);

    void (async () => {
      try {
        const projectName = type === "git" ? gitName().trim() : name().trim();
        const target = type === "git" ? gitUrl().trim() : startUrl().trim();
        if (!projectName) {
          throw new Error("Project name is required.");
        }
        if (!target) {
          throw new Error(type === "git" ? "Git URL is required." : "Start URL is required.");
        }

        const files =
          type === "yaml"
            ? [{ path: "webuse.yaml", content: yamlContent(projectName, target) }]
            : type === "python"
              ? [
                  { path: "webuse.yaml", content: pythonProjectContent(projectName) },
                  { path: `spiders/${slugify(projectName)}.py`, content: pythonContent(projectName, target) },
                ]
              : [];

        const response = await fetch("/api/projects", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            name: projectName,
            type,
            target,
            files,
          }),
        });
        const data = (await response.json().catch(() => ({}))) as ProjectResponse;
        if (!response.ok || !data.project) {
          throw new Error(data.error || `Failed to create project (${response.status})`);
        }

        navigate(`/projects/${data.project.id}/${type === "git" ? "settings" : "files"}`);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to create project");
      } finally {
        setSaving(undefined);
      }
    })();
  };

  return (
    <Layout currentTab="projects">
      <div class="mb-6 flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 class="text-3xl font-bold text-sky-400">Create project</h1>
          <p class="mt-1 text-sm text-gray-400">Start from a linked repo, YAML config, or Python spider</p>
        </div>
        <ButtonLink href="/projects" size="compact">
          Back to projects
        </ButtonLink>
      </div>

      <Show when={error()}>
        {message => (
          <div class="mb-4 rounded border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-200">
            {message()}
          </div>
        )}
      </Show>

      <div class="grid gap-4 lg:grid-cols-3">
        <section class="rounded-lg border border-gray-700 bg-gray-900 p-4">
          <div class="mb-4 flex items-center gap-2 text-lg font-semibold text-white">
            <FiGitBranch size={18} stroke-width={2} aria-hidden="true" />
            Link a git repo
          </div>
          <div class="grid gap-3">
            <label class="field dark-field">
              <span>Name</span>
              <input value={gitName()} onInput={event => setGitName(event.currentTarget.value)} />
            </label>
            <label class="field dark-field">
              <span>Git URL</span>
              <input
                placeholder="https://github.com/org/repo.git"
                value={gitUrl()}
                onInput={event => setGitUrl(event.currentTarget.value)}
              />
              <span class="text-xs text-gray-400">
                Files stay in the checkout under the worker directory and are not editable in the UI.
              </span>
            </label>
            <Button
              class="mt-1"
              disabled={saving() !== undefined}
              type="button"
              variant="primary"
              onClick={() => createProject("git")}
            >
              {saving() === "git" ? "Linking..." : "Link repo"}
            </Button>
          </div>
        </section>

        <section class="rounded-lg border border-gray-700 bg-gray-900 p-4">
          <div class="mb-4 flex items-center gap-2 text-lg font-semibold text-white">
            <FiFileText size={18} stroke-width={2} aria-hidden="true" />
            Create a YAML project
          </div>
          <ProjectBasics name={name()} startUrl={startUrl()} onName={setName} onStartUrl={setStartUrl} />
          <Button
            class="mt-4"
            disabled={saving() !== undefined}
            type="button"
            variant="primary"
            onClick={() => createProject("yaml")}
          >
            {saving() === "yaml" ? "Creating..." : "Create YAML project"}
          </Button>
        </section>

        <section class="rounded-lg border border-gray-700 bg-gray-900 p-4">
          <div class="mb-4 flex items-center gap-2 text-lg font-semibold text-white">
            <FiCode size={18} stroke-width={2} aria-hidden="true" />
            Create a Python project
          </div>
          <ProjectBasics name={name()} startUrl={startUrl()} onName={setName} onStartUrl={setStartUrl} />
          <Button
            class="mt-4"
            disabled={saving() !== undefined}
            type="button"
            variant="primary"
            onClick={() => createProject("python")}
          >
            {saving() === "python" ? "Creating..." : "Create Python project"}
          </Button>
        </section>
      </div>
    </Layout>
  );
}

function ProjectBasics(props: {
  name: string;
  startUrl: string;
  onName: (value: string) => void;
  onStartUrl: (value: string) => void;
}) {
  return (
    <div class="grid gap-3">
      <label class="field dark-field">
        <span>Name</span>
        <input value={props.name} onInput={event => props.onName(event.currentTarget.value)} />
      </label>
      <label class="field dark-field">
        <span>Start URL</span>
        <input value={props.startUrl} onInput={event => props.onStartUrl(event.currentTarget.value)} />
      </label>
    </div>
  );
}
