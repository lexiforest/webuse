import { useNavigate } from "@solidjs/router";
import { For, createSignal, type JSX } from "solid-js";
import { parse as parseYaml, stringify as stringifyYaml } from "yaml";

import Button, { ButtonLink } from "~/components/Button";

export type ProjectFormValue = {
  name: string;
  type: "source" | "git";
  target: string;
  config?: Record<string, unknown>;
};

type ProjectFormProps = {
  initialValue: ProjectFormValue;
  method: "POST" | "PUT";
  submitLabel: string;
  endpoint: string;
};

export const booksToScrapeProject: ProjectFormValue = {
  name: "Books to Scrape",
  type: "source",
  target: "https://books.toscrape.com/",
  config: {
    start_urls: ["https://books.toscrape.com/"],
    allowed_domains: ["books.toscrape.com"],
    max_depth: 1,
    follow: [{ css: ".next a", same_domain: true }],
    extract: {
      item_css: ".product_pod",
      fields: {
        title: {
          css: "h3 a",
          attr: "title",
        },
        price: ".price_color",
        availability: ".availability",
      },
    },
  },
};

function stringifyConfig(config: Record<string, unknown> | undefined) {
  return config ? stringifyYaml(config) : "";
}

function isConfigObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function highlightScalar(text: string): JSX.Element[] {
  const pieces: JSX.Element[] = [];
  const pattern = /("(?:\\.|[^"])*"|'(?:''|[^'])*'|\b(?:true|false|null)\b|-?\d+(?:\.\d+)?)/gi;
  let cursor = 0;
  let match: RegExpExecArray | null;

  while ((match = pattern.exec(text)) !== null) {
    if (match.index > cursor) {
      pieces.push(text.slice(cursor, match.index));
    }

    const token = match[0];
    const className =
      token === "true" || token === "false" || token === "null"
        ? "yaml-boolean"
        : /^-?\d/.test(token)
          ? "yaml-number"
          : "yaml-string";
    pieces.push(<span class={className}>{token}</span>);
    cursor = match.index + token.length;
  }

  if (cursor < text.length) {
    pieces.push(text.slice(cursor));
  }

  return pieces;
}

function highlightYamlLine(line: string): JSX.Element {
  const commentIndex = line.search(/(^|[^\\])#/);
  const hasComment = commentIndex !== -1;
  const beforeComment = hasComment ? line.slice(0, commentIndex + (line[commentIndex] === "#" ? 0 : 1)) : line;
  const comment = hasComment ? line.slice(beforeComment.length) : "";
  const keyMatch = beforeComment.match(/^(\s*)(-\s*)?([A-Za-z_][\w.-]*)(:)(.*)$/);

  if (!keyMatch) {
    return (
      <>
        {highlightScalar(beforeComment)}
        {comment && <span class="yaml-comment">{comment}</span>}
      </>
    );
  }

  return (
    <>
      {keyMatch[1]}
      {keyMatch[2] && <span class="yaml-marker">{keyMatch[2]}</span>}
      <span class="yaml-key">{keyMatch[3]}</span>
      <span class="yaml-punctuation">{keyMatch[4]}</span>
      {highlightScalar(keyMatch[5])}
      {comment && <span class="yaml-comment">{comment}</span>}
    </>
  );
}

export default function ProjectForm(props: ProjectFormProps) {
  const navigate = useNavigate();
  const [name, setName] = createSignal(props.initialValue.name);
  const [type, setType] = createSignal<"source" | "git">(props.initialValue.type);
  const [target, setTarget] = createSignal(props.initialValue.target);
  const [config, setConfig] = createSignal(stringifyConfig(props.initialValue.config));
  const [saving, setSaving] = createSignal(false);
  const [error, setError] = createSignal<string>();
  let highlightRef: HTMLPreElement | undefined;

  const yamlLines = () => {
    const value = config();
    return value.length > 0 ? value.split("\n") : [""];
  };

  const syncHighlightScroll = (event: Event) => {
    const textarea = event.currentTarget as HTMLTextAreaElement;
    if (!highlightRef) {
      return;
    }

    highlightRef.scrollTop = textarea.scrollTop;
    highlightRef.scrollLeft = textarea.scrollLeft;
  };

  const submitProject = async (event: SubmitEvent) => {
    event.preventDefault();
    setError(undefined);
    setSaving(true);

    try {
      let parsedConfig: Record<string, unknown> | undefined;

      const configText = config().trim();
      if (configText.length > 0) {
        const value = parseYaml(configText) as unknown;
        if (!isConfigObject(value)) {
          throw new Error("Config must be a YAML mapping.");
        }
        parsedConfig = value;
      }

      const response = await fetch(props.endpoint, {
        method: props.method,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: name(),
          type: type(),
          target: target(),
          config: parsedConfig,
        }),
      });

      if (!response.ok) {
        const data = (await response.json().catch(() => ({}))) as { error?: string };
        throw new Error(data.error || `Failed to save project (${response.status})`);
      }

      navigate("/projects");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save project");
    } finally {
      setSaving(false);
    }
  };

  return (
    <form class="rounded-lg border border-gray-700 bg-gray-900 p-4" onSubmit={submitProject}>
      {error() && (
        <div class="mb-4 rounded border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-200">
          {error()}
        </div>
      )}

      <div class="grid gap-4">
        <label class="field dark-field">
          <span>Name</span>
          <input value={name()} onInput={event => setName(event.currentTarget.value)} required />
        </label>

        <label class="field dark-field">
          <span>Type</span>
          <select value={type()} onInput={event => setType(event.currentTarget.value as "source" | "git")}>
            <option value="source">source</option>
            <option value="git">git</option>
          </select>
        </label>

        <label class="field dark-field">
          <span>{type() === "git" ? "Git URL" : "Source URL"}</span>
          <input value={target()} onInput={event => setTarget(event.currentTarget.value)} required />
        </label>

        <label class="field dark-field">
          <span>Config YAML</span>
          <div class="yaml-editor">
            <pre ref={highlightRef} class="yaml-highlight" aria-hidden="true">
              <For each={yamlLines()}>{line => <div>{highlightYamlLine(line)}</div>}</For>
            </pre>
            <textarea
              rows="16"
              spellcheck={false}
              value={config()}
              onInput={event => setConfig(event.currentTarget.value)}
              onScroll={syncHighlightScroll}
            />
          </div>
        </label>

        <div class="flex justify-end gap-2">
          <ButtonLink href="/projects">
            Cancel
          </ButtonLink>
          <Button variant="primary" type="submit" disabled={saving()}>
            {saving() ? "Saving..." : props.submitLabel}
          </Button>
        </div>
      </div>
    </form>
  );
}
