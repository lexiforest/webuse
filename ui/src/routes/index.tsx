import { useNavigate } from "@solidjs/router";
import { Show, createSignal } from "solid-js";
import { FiArrowUp, FiMessageSquare } from "solid-icons/fi";

import Layout from "~/layout/dashboard";

type CreatedProject = { id: number };

const pendingPromptKey = (projectId: number) => `webuse:project:${projectId}:pending-prompt`;

function projectName(prompt: string) {
  const firstLine = prompt.split("\n", 1)[0].trim();
  const withoutUrl = firstLine.replace(/https?:\/\/\S+/gi, "").replace(/\s+/g, " ").trim();
  const title = withoutUrl || "New crawler";
  return title.length > 56 ? `${title.slice(0, 53).trimEnd()}...` : title;
}

function projectTarget(prompt: string) {
  const match = prompt.match(/https?:\/\/[^\s<>"')\]]+/i)?.[0];
  return match?.replace(/[.,;:!?]+$/, "") || "Generated from prompt";
}

function starterYaml(name: string) {
  return `name: ${JSON.stringify(name)}\nspiders:\n  crawler:\n    start_urls: []\n`;
}

export default function NewProject() {
  const navigate = useNavigate();
  const [prompt, setPrompt] = createSignal("");
  const [creating, setCreating] = createSignal(false);
  const [error, setError] = createSignal<string>();

  function handleKeyDown(event: KeyboardEvent) {
    if (event.key !== "Enter" || event.shiftKey || event.isComposing) return;
    event.preventDefault();
    void submit();
  }

  async function submit() {
    const message = prompt().trim();
    if (!message || creating()) return;

    setCreating(true);
    setError(undefined);
    try {
      const name = projectName(message);
      const response = await fetch("/api/projects", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name,
          type: "yaml",
          target: projectTarget(message),
          files: [{ path: "webuse.yaml", content: starterYaml(name) }],
        }),
      });
      const data = (await response.json().catch(() => ({}))) as { project?: CreatedProject; error?: string };
      if (!response.ok || !data.project) {
        throw new Error(data.error || `Failed to create project (${response.status})`);
      }

      window.sessionStorage.setItem(pendingPromptKey(data.project.id), message);
      navigate(`/projects/${data.project.id}/files`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create project");
      setCreating(false);
    }
  }

  return (
    <Layout currentTab="new project">
      <div class="grid min-h-full flex-1 place-items-center px-3 py-12">
        <section class="w-full max-w-3xl -translate-y-[8vh]">
          <div class="mb-8 text-center">
            <div class="mx-auto mb-4 grid h-12 w-12 place-items-center rounded-2xl bg-sky-500/15 text-sky-300">
              <FiMessageSquare size={24} stroke-width={1.8} aria-hidden="true" />
            </div>
            <h1 class="text-3xl font-semibold tracking-tight text-white sm:text-4xl">What do you want to crawl?</h1>
            <p class="mt-3 text-sm text-gray-400">Describe the site and the data you need. Include a URL when you have one.</p>
          </div>

          <div class="new-project-composer">
            <textarea
              autofocus
              aria-label="Describe your crawler"
              disabled={creating()}
              placeholder="Build a crawler for https://example.com that extracts..."
              rows={3}
              value={prompt()}
              onInput={event => {
                setPrompt(event.currentTarget.value);
                setError(undefined);
              }}
              onKeyDown={handleKeyDown}
            />
            <button
              aria-label="Create project"
              class="new-project-submit"
              disabled={creating() || !prompt().trim()}
              type="button"
              onClick={() => void submit()}
            >
              <FiArrowUp size={18} stroke-width={2.5} aria-hidden="true" />
            </button>
          </div>
          <div class="mt-3 min-h-5 text-center text-xs text-gray-500">
            {creating() ? "Creating your project..." : "Enter to send · Shift+Enter for a new line"}
          </div>
          <Show when={error()}>
            {message => <div class="mt-4 rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-200">{message()}</div>}
          </Show>
        </section>
      </div>
    </Layout>
  );
}
