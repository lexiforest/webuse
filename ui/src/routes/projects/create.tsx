import { TextField, TextFieldInput, TextFieldLabel } from "~/components/ui/text-field";
import { A, useNavigate } from "@solidjs/router";
import { Show, createSignal } from "solid-js";
import { FiCode, FiFileText } from "solid-icons/fi";

import { Button } from "~/components/ui/button";
import Layout from "~/layout/dashboard";

type Starter = "yaml" | "python";

type ProjectResponse = {
  project?: {
    id: number;
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
  return `name: ${JSON.stringify(name)}
start_urls:
  - ${JSON.stringify(startUrl)}
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
        title = response.find(css="title")
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
  const [saving, setSaving] = createSignal<Starter>();
  const [error, setError] = createSignal<string>();

  const createProject = (starter: Starter) => {
    setError(undefined);
    setSaving(starter);

    void (async () => {
      try {
        const projectName = name().trim();
        const target = startUrl().trim();
        if (!projectName) {
          throw new Error("Project name is required.");
        }
        if (!target) {
          throw new Error("Start URL is required.");
        }

        const files =
          starter === "yaml"
            ? [
                { path: "webuse.yaml", content: `name: ${JSON.stringify(projectName)}\nspiders:\n  ${slugify(projectName)}:\n    config: spiders/${slugify(projectName)}.yaml\n` },
                { path: `spiders/${slugify(projectName)}.yaml`, content: yamlContent(projectName, target) },
              ]
            : [
                { path: "webuse.yaml", content: pythonProjectContent(projectName) },
                { path: `spiders/${slugify(projectName)}.py`, content: pythonContent(projectName, target) },
              ];

        const response = await fetch("/api/projects", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            name: projectName,
            target,
            files,
          }),
        });
        const data = (await response.json().catch(() => ({}))) as ProjectResponse;
        if (!response.ok || !data.project) {
          throw new Error(data.error || `Failed to create project (${response.status})`);
        }

        window.dispatchEvent(new Event("webuse:projects-changed"));
        navigate(`/projects/${data.project.id}/files`);
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
          <p class="mt-1 text-sm text-gray-400">Start with YAML configuration or Python spider files</p>
        </div>
        <Button variant="outline" as={A} href="/projects" size="sm">
          Back to projects
        </Button>
      </div>

      <Show when={error()}>
        {message => (
          <div class="mb-4 rounded border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-200">
            {message()}
          </div>
        )}
      </Show>

      <div class="grid gap-4 lg:grid-cols-2">
        <section class="rounded-lg border border-gray-700 bg-gray-900 p-4">
          <div class="mb-4 flex items-center gap-2 text-lg font-semibold text-white">
            <FiFileText size={18} stroke-width={2} aria-hidden="true" />
            YAML starter
          </div>
          <ProjectBasics name={name()} startUrl={startUrl()} onName={setName} onStartUrl={setStartUrl} />
          <Button
            class="mt-4"
            disabled={saving() !== undefined}
            type="button"
            variant="default"
            onClick={() => createProject("yaml")}
          >
            {saving() === "yaml" ? "Creating..." : "Create from YAML"}
          </Button>
        </section>

        <section class="rounded-lg border border-gray-700 bg-gray-900 p-4">
          <div class="mb-4 flex items-center gap-2 text-lg font-semibold text-white">
            <FiCode size={18} stroke-width={2} aria-hidden="true" />
            Python starter
          </div>
          <ProjectBasics name={name()} startUrl={startUrl()} onName={setName} onStartUrl={setStartUrl} />
          <Button
            class="mt-4"
            disabled={saving() !== undefined}
            type="button"
            variant="default"
            onClick={() => createProject("python")}
          >
            {saving() === "python" ? "Creating..." : "Create from Python"}
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
      <TextField value={props.name} onChange={value => props.onName(value)}>
        <TextFieldLabel>Name</TextFieldLabel>
        <TextFieldInput />
      </TextField>
      <TextField value={props.startUrl} onChange={value => props.onStartUrl(value)}>
        <TextFieldLabel>Start URL</TextFieldLabel>
        <TextFieldInput />
      </TextField>
    </div>
  );
}
