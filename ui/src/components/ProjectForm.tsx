import { useBeforeLeave, useNavigate } from "@solidjs/router";
import cronstrue from "cronstrue";
import { For, Show, createMemo, createSignal, onCleanup, onMount, type JSX } from "solid-js";
import {
  FiAlertCircle,
  FiChevronRight,
  FiChevronsLeft,
  FiChevronsRight,
  FiEdit3,
  FiFile,
  FiFolder,
  FiMaximize2,
  FiMessageSquare,
  FiMinimize2,
  FiPlus,
  FiSidebar,
  FiTrash2,
} from "solid-icons/fi";
import { parse as parseYaml, stringify as stringifyYaml } from "yaml";

import Button, { ButtonLink } from "~/components/Button";
import LLMChat, { type LLMChatMessage } from "~/components/LLMChat";
import ProjectVisual from "~/components/ProjectVisual";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "~/components/ui/Collapsible";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "~/components/ui/Tabs";

export type ProjectFile = {
  path: string;
  content: string;
};

export type ProjectType = "source" | "yaml" | "python" | "git";

export type ProjectFormValue = {
  name: string;
  type: ProjectType;
  target: string;
  cron?: string;
  config?: Record<string, unknown>;
  files?: ProjectFile[];
};

type ProjectFormProps = {
  initialValue: ProjectFormValue;
  method: "POST" | "PUT";
  submitLabel: string;
  endpoint: string;
  projectId?: number;
  defaultTab?: ProjectFormTab;
  tabBasePath?: string;
};

type ProjectFormTab = "settings" | "files" | "visual";

type ProjectSaveResponse = {
  project?: ProjectFormValue & {
    id: number;
  };
};

type FileTreeNode = {
  name: string;
  path: string;
  type: "folder" | "file";
  file?: ProjectFile;
  children: FileTreeNode[];
};

function normalizeTab(value: unknown): ProjectFormTab | undefined {
  return value === "settings" || value === "files" || value === "visual" ? value : undefined;
}

function tabFromPath(pathname: string): ProjectFormTab | undefined {
  const segment = pathname.split("/").filter(Boolean).at(-1);
  return normalizeTab(segment);
}

export const booksToScrapeProject: ProjectFormValue = {
  name: "Books to Scrape",
  type: "source",
  target: "https://books.toscrape.com/",
  cron: "",
  config: {
    name: "Books to Scrape",
    spiders: {
      books: {
        start_urls: ["https://books.toscrape.com/"],
        allowed_domains: ["books.toscrape.com"],
        max_depth: 1,
        pages: {
          default: {
            follow: [{ css: ".next a", same_domain: true }],
            extract: {
              books: {
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
          },
        },
      },
    },
  },
  files: [
    {
      path: "webuse.yaml",
      content: `name: Books to Scrape
spiders:
  books:
    start_urls:
      - https://books.toscrape.com/
    allowed_domains:
      - books.toscrape.com
    max_depth: 1
    pages:
      default:
        follow:
          - css: .next a
            same_domain: true
        extract:
          books:
            item_css: .product_pod
            fields:
              title:
                css: h3 a
                attr: title
              price: .price_color
              availability: .availability
`,
    },
    {
      path: "spiders/books.py",
      content: `import webuse


class BooksSpider(webuse.Spider):
    name = "books"
`,
    },
  ],
};

function isConfigObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function initialFiles(value: ProjectFormValue): ProjectFile[] {
  if (value.type === "git") {
    return [];
  }
  if (value.files && value.files.length > 0) {
    return value.files;
  }
  return [
    {
      path: "webuse.yaml",
      content: value.config ? stringifyYaml(value.config) : "",
    },
  ];
}

function projectSnapshot(value: ProjectFormValue & { files: ProjectFile[] }) {
  return JSON.stringify({
    name: value.name,
    type: value.type,
    target: value.target,
    cron: (value.cron ?? "").trim(),
    files: value.files
      .map(file => ({ path: file.path, content: file.content }))
      .sort((left, right) => left.path.localeCompare(right.path)),
  });
}

function isYamlPath(path: string) {
  return path.endsWith(".yaml") || path.endsWith(".yml");
}

function isPythonPath(path: string) {
  return path.endsWith(".py");
}

function sortTree(nodes: FileTreeNode[]) {
  nodes.sort((left, right) => {
    if (left.type !== right.type) {
      return left.type === "folder" ? -1 : 1;
    }
    return left.name.localeCompare(right.name);
  });
  for (const node of nodes) {
    sortTree(node.children);
  }
}

function buildFileTree(files: ProjectFile[]) {
  const root: FileTreeNode = {
    name: "",
    path: "",
    type: "folder",
    children: [],
  };

  for (const file of files) {
    const parts = file.path.split("/");
    let parent = root;

    for (let index = 0; index < parts.length; index += 1) {
      const name = parts[index];
      const path = parts.slice(0, index + 1).join("/");
      const isFile = index === parts.length - 1;

      if (isFile) {
        parent.children.push({ name, path, type: "file", file, children: [] });
        continue;
      }

      let folder = parent.children.find(
        child => child.type === "folder" && child.name === name,
      );
      if (!folder) {
        folder = { name, path, type: "folder", children: [] };
        parent.children.push(folder);
      }
      parent = folder;
    }
  }

  sortTree(root.children);
  return root.children;
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

function highlightPythonLine(line: string): JSX.Element {
  const pieces: JSX.Element[] = [];
  const keywords =
    "False|None|True|and|as|assert|async|await|break|case|class|continue|def|del|elif|else|except|finally|for|from|global|if|import|in|is|lambda|match|nonlocal|not|or|pass|raise|return|try|while|with|yield";
  const builtins =
    "bool|dict|float|int|len|list|print|range|set|str|super|tuple|type";
  const pattern = new RegExp(
    `(#.*$|"(?:\\\\.|[^"\\\\])*"|'(?:\\\\.|[^'\\\\])*'|@[A-Za-z_][\\w.]*|\\b(?:${keywords})\\b|\\b(?:${builtins}|self|cls)\\b|\\b\\d+(?:\\.\\d+)?\\b)`,
    "g",
  );
  let cursor = 0;
  let match: RegExpExecArray | null;

  while ((match = pattern.exec(line)) !== null) {
    if (match.index > cursor) {
      pieces.push(line.slice(cursor, match.index));
    }

    const token = match[0];
    let className = "python-number";
    if (token.startsWith("#")) {
      className = "python-comment";
    } else if (token.startsWith("\"") || token.startsWith("'")) {
      className = "python-string";
    } else if (token.startsWith("@")) {
      className = "python-decorator";
    } else if (new RegExp(`^(?:${keywords})$`).test(token)) {
      className = "python-keyword";
    } else if (/^(?:self|cls|bool|dict|float|int|len|list|print|range|set|str|super|tuple|type)$/.test(token)) {
      className = "python-builtin";
    }
    pieces.push(<span class={className}>{token}</span>);
    cursor = match.index + token.length;
  }

  if (cursor < line.length) {
    pieces.push(line.slice(cursor));
  }

  return <>{pieces}</>;
}

async function readJsonResponse<T>(response: Response): Promise<T> {
  const contentType = response.headers.get("content-type") ?? "";
  if (!contentType.includes("application/json")) {
    const text = await response.text().catch(() => "");
    throw new Error(
      text.trim().startsWith("<!doctype") || text.trim().startsWith("<html")
        ? "Assistant API returned the app HTML page. Restart the UI dev server so the new API route is loaded."
        : "Assistant API returned a non-JSON response.",
    );
  }
  return response.json() as Promise<T>;
}

async function readError(response: Response, fallback: string) {
  return readJsonResponse<{ error?: string }>(response)
    .then(data => data.error || fallback)
    .catch(() => fallback);
}

export default function ProjectForm(props: ProjectFormProps) {
  const navigate = useNavigate();
  const initialFileState = initialFiles(props.initialValue);
  const [name, setName] = createSignal(props.initialValue.name);
  const [type, setType] = createSignal<ProjectType>(props.initialValue.type);
  const [target, setTarget] = createSignal(props.initialValue.target);
  const [cron, setCron] = createSignal(props.initialValue.cron ?? "");
  const [files, setFiles] = createSignal<ProjectFile[]>(initialFileState);
  const [selectedPath, setSelectedPath] = createSignal(files()[0]?.path ?? "webuse.yaml");
  const [saving, setSaving] = createSignal(false);
  const [error, setError] = createSignal<string>();
  const [fileSidebarOpen, setFileSidebarOpen] = createSignal(true);
  const [expanded, setExpanded] = createSignal(false);
  const [chatWidth, setChatWidth] = createSignal(352);
  const [resizingChat, setResizingChat] = createSignal(false);
  const [chatInput, setChatInput] = createSignal("");
  const [chatMessages, setChatMessages] = createSignal<LLMChatMessage[]>([]);
  const [chatError, setChatError] = createSignal<string>();
  const [chatSessionId, setChatSessionId] = createSignal<number>();
  const [chatLoading, setChatLoading] = createSignal(false);
  const [chatSending, setChatSending] = createSignal(false);
  const [activeTab, setActiveTab] = createSignal<ProjectFormTab>(
    props.initialValue.type === "git" ? "settings" : (props.defaultTab ?? "settings"),
  );
  const [savedSnapshot, setSavedSnapshot] = createSignal(
    projectSnapshot({ ...props.initialValue, files: initialFileState }),
  );
  let highlightRef: HTMLPreElement | undefined;

  const currentSnapshot = createMemo(() =>
    projectSnapshot({
      name: name(),
      type: type(),
      target: target(),
      cron: cron(),
      files: files(),
    }),
  );
  const isDirty = createMemo(() => currentSnapshot() !== savedSnapshot());
  const isGitProject = createMemo(() => type() === "git");
  const fileTree = createMemo(() => buildFileTree(files()));
  const cronDescription = createMemo(() => {
    const value = cron().trim();
    if (!value) {
      return { text: "Runs manually unless started from the Runs page.", valid: true };
    }

    try {
      return { text: cronstrue.toString(value), valid: true };
    } catch {
      return { text: "Enter a valid cron expression, for example 0 * * * *.", valid: false };
    }
  });
  const selectedFile = () => files().find(file => file.path === selectedPath()) ?? files()[0];
  const selectedContent = () => selectedFile()?.content ?? "";
  let lineNumberRef: HTMLDivElement | undefined;
  const codeLines = () => {
    const value = selectedContent();
    return value.length > 0 ? value.split("\n") : [""];
  };
  const lineNumbers = createMemo(() => codeLines().map((_, index) => index + 1));

  const confirmDiscardChanges = () =>
    window.confirm("You have unsaved project changes. Leave without saving?") &&
    window.confirm("Unsaved project changes will be lost. Leave anyway?");

  const blockAssistantLeave = () => {
    window.alert("The LLM is still thinking. Wait for it to finish before leaving this page.");
  };

  useBeforeLeave(event => {
    if (event.defaultPrevented) {
      return;
    }

    if (chatSending()) {
      event.preventDefault();
      setTimeout(blockAssistantLeave, 0);
      return;
    }

    if (!isDirty()) {
      return;
    }
    event.preventDefault();
    setTimeout(() => {
      if (confirmDiscardChanges()) {
        event.retry(true);
      }
    }, 0);
  });

  onMount(() => {
    const syncTabFromPath = () => {
      const nextTab = tabFromPath(window.location.pathname);
      if (nextTab) {
        setActiveTab(isGitProject() && nextTab === "files" ? "visual" : nextTab);
      }
    };

    syncTabFromPath();
    window.addEventListener("popstate", syncTabFromPath);
    onCleanup(() => window.removeEventListener("popstate", syncTabFromPath));

    const handleBeforeUnload = (event: BeforeUnloadEvent) => {
      if (!isDirty() && !chatSending()) {
        return;
      }
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", handleBeforeUnload);
    onCleanup(() => window.removeEventListener("beforeunload", handleBeforeUnload));

    if (props.projectId) {
      setChatLoading(true);
      void (async () => {
        try {
          const response = await fetch(`/api/assistant-project?project_id=${props.projectId}`);
          if (!response.ok) {
            throw new Error(await readError(response, `Failed to load assistant history (${response.status})`));
          }
          const data = await readJsonResponse<{
            session?: { id: number };
            messages?: LLMChatMessage[];
          }>(response);
          setChatSessionId(data.session?.id);
          setChatMessages(data.messages ?? []);
        } catch (err) {
          setChatError(err instanceof Error ? err.message : "Failed to load assistant history");
        } finally {
          setChatLoading(false);
        }
      })();
    }
  });

  const changeTab = (value: string) => {
    const requestedTab = normalizeTab(value) ?? "settings";
    const nextTab = isGitProject() && requestedTab === "files" ? "visual" : requestedTab;
    setActiveTab(nextTab);
    if (props.tabBasePath) {
      window.history.pushState(null, "", `${props.tabBasePath}/${nextTab}`);
    }
  };

  const toggleExpanded = () => {
    if (!expanded()) {
      changeTab("files");
    }
    setExpanded(value => !value);
  };

  const syncHighlightScroll = (event: Event) => {
    const textarea = event.currentTarget as HTMLTextAreaElement;
    if (highlightRef) {
      highlightRef.scrollTop = textarea.scrollTop;
      highlightRef.scrollLeft = textarea.scrollLeft;
    }
    if (lineNumberRef) {
      lineNumberRef.scrollTop = textarea.scrollTop;
    }
  };

  const startChatResize = (event: PointerEvent) => {
    event.preventDefault();
    const pointerId = event.pointerId;
    const target = event.currentTarget as HTMLElement;
    const editor = target.closest(".project-file-editor") as HTMLElement | null;
    if (!editor) {
      return;
    }

    target.setPointerCapture(pointerId);
    setResizingChat(true);

    const onMove = (moveEvent: PointerEvent) => {
      const rect = editor.getBoundingClientRect();
      const nextWidth = rect.right - moveEvent.clientX;
      const maxWidth = Math.max(280, rect.width - 360);
      setChatWidth(Math.round(Math.min(Math.max(nextWidth, 280), maxWidth)));
    };
    const onDone = () => {
      setResizingChat(false);
      if (target.hasPointerCapture(pointerId)) {
        target.releasePointerCapture(pointerId);
      }
      target.removeEventListener("pointermove", onMove);
      target.removeEventListener("pointerup", onDone);
      target.removeEventListener("pointercancel", onDone);
    };

    target.addEventListener("pointermove", onMove);
    target.addEventListener("pointerup", onDone);
    target.addEventListener("pointercancel", onDone);
  };

  const updateSelectedFile = (patch: Partial<ProjectFile>) => {
    const currentPath = selectedFile()?.path;
    if (!currentPath) {
      return;
    }
    setFiles(current =>
      current.map(file => {
        if (file.path !== currentPath) {
          return file;
        }
        const next = { ...file, ...patch };
        if (patch.path !== undefined) {
          setSelectedPath(patch.path);
        }
        return next;
      }),
    );
  };

  const addFile = () => {
    const path = window.prompt("New file path", "spiders/new_spider.py")?.trim();
    if (!path) {
      return;
    }
    if (files().some(file => file.path === path)) {
      setError(`File already exists: ${path}`);
      return;
    }
    setError(undefined);
    setFiles(current => [...current, { path, content: "" }].sort((left, right) => left.path.localeCompare(right.path)));
    setSelectedPath(path);
  };

  const renameFile = (path: string, nextPathValue: string) => {
    const nextPath = nextPathValue.trim();
    if (!nextPath) {
      return;
    }
    if (nextPath === path) {
      return;
    }
    if (files().some(file => file.path === nextPath)) {
      setError(`File already exists: ${nextPath}`);
      return;
    }
    setError(undefined);
    setFiles(current =>
      current
        .map(file => (file.path === path ? { ...file, path: nextPath } : file))
        .sort((left, right) => left.path.localeCompare(right.path)),
    );
    setSelectedPath(nextPath);
  };

  const promptRenameFile = (path: string) => {
    const nextPath = window.prompt("Rename file path", path);
    if (nextPath === null) {
      return;
    }
    renameFile(path, nextPath);
  };

  const deleteFile = (path: string) => {
    if (files().length <= 1) {
      return;
    }
    if (!window.confirm(`Delete ${path}?`)) {
      return;
    }
    const next = files().filter(item => item.path !== path);
    setFiles(next);
    setSelectedPath(next[0]?.path ?? "webuse.yaml");
  };

  const sendChatMessage = async () => {
    const prompt = chatInput().trim();
    if (!prompt) {
      return;
    }
    if (!props.projectId) {
      setChatError("Save the project before using the LLM assistant.");
      return;
    }

    setChatError(undefined);
    setChatSending(true);
    setChatMessages(current => [...current, { role: "user", content: prompt }]);
    setChatInput("");

    try {
      const response = await fetch("/api/assistant-project", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          projectId: props.projectId,
          sessionId: chatSessionId(),
          message: prompt,
          files: files(),
          selectedPath: selectedPath(),
        }),
      });

      if (!response.ok) {
        throw new Error(await readError(response, `Assistant request failed (${response.status})`));
      }

      const data = await readJsonResponse<{
        session?: { id: number };
        messages?: ChatMessage[];
        files?: ProjectFile[];
        selectedPath?: string;
      }>(response);
      if (data.session?.id) {
        setChatSessionId(data.session.id);
      }
      if (data.messages) {
        setChatMessages(data.messages);
      }
      if (data.files) {
        setFiles(data.files);
        setSelectedPath(
          data.selectedPath && data.files.some(file => file.path === data.selectedPath)
            ? data.selectedPath
            : data.files[0]?.path ?? "",
        );
      }
    } catch (err) {
      setChatError(err instanceof Error ? err.message : "Assistant request failed");
    } finally {
      setChatSending(false);
    }
  };

  const deriveConfig = () => {
    if (isGitProject()) {
      return undefined;
    }
    const webuseFile = files().find(file => file.path === "webuse.yaml" || file.path === "webuse.yml");
    if (!webuseFile || webuseFile.content.trim().length === 0) {
      return undefined;
    }
    const value = parseYaml(webuseFile.content) as unknown;
    if (!isConfigObject(value)) {
      throw new Error("webuse.yaml must be a YAML mapping.");
    }
    return value;
  };

  const renderTreeNode = (node: FileTreeNode): JSX.Element => {
    if (node.type === "folder") {
      return (
        <Collapsible defaultOpen class="project-tree-folder">
          <CollapsibleTrigger class="project-tree-folder-trigger">
            <FiChevronRight class="project-tree-chevron" size={14} stroke-width={2} aria-hidden="true" />
            <FiFolder size={14} stroke-width={2} aria-hidden="true" />
            <span>{node.name}</span>
          </CollapsibleTrigger>
          <CollapsibleContent class="project-tree-folder-content">
            <For each={node.children}>{child => renderTreeNode(child)}</For>
          </CollapsibleContent>
        </Collapsible>
      );
    }

    return (
      <div
        class={`project-tree-file group ${selectedPath() === node.path ? "project-tree-file-active" : ""}`}
        onClick={() => setSelectedPath(node.path)}
      >
        <FiFile size={14} stroke-width={2} aria-hidden="true" />
        <span>{node.name}</span>
        <Button
          aria-label={`Rename ${node.path}`}
          class="project-tree-file-action opacity-0 focus:opacity-100 group-hover:opacity-100"
          size="icon"
          type="button"
          onClick={event => {
            event.stopPropagation();
            promptRenameFile(node.path);
          }}
        >
          <FiEdit3 size={12} stroke-width={2} aria-hidden="true" />
        </Button>
        <Button
          aria-label={`Delete ${node.path}`}
          class="project-tree-file-action opacity-0 focus:opacity-100 group-hover:opacity-100"
          size="icon"
          variant="danger"
          type="button"
          disabled={files().length <= 1}
          onClick={event => {
            event.stopPropagation();
            deleteFile(node.path);
          }}
        >
          <FiTrash2 size={12} stroke-width={2} aria-hidden="true" />
        </Button>
      </div>
    );
  };

  const submitProject = async (event: SubmitEvent) => {
    event.preventDefault();
    setError(undefined);
    setSaving(true);

    try {
      const parsedConfig = deriveConfig();

      const response = await fetch(props.endpoint, {
        method: props.method,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: name(),
          type: type(),
          target: target(),
          cron: cron().trim(),
          config: parsedConfig,
          files: isGitProject() ? [] : files(),
        }),
      });

      if (!response.ok) {
        const data = (await response.json().catch(() => ({}))) as { error?: string };
        throw new Error(data.error || `Failed to save project (${response.status})`);
      }

      const data = (await response.json()) as ProjectSaveResponse;
      setSavedSnapshot(currentSnapshot());
      if (props.method === "POST" && data.project?.id) {
        navigate(`/projects/${data.project.id}/files`);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save project");
    } finally {
      setSaving(false);
    }
  };

  return (
    <form
      class={`flex min-h-0 flex-1 flex-col overflow-hidden rounded-lg border border-gray-700 bg-gray-900 p-4 ${
        expanded() ? "fixed inset-2 z-50 shadow-2xl" : ""
      }`}
      onSubmit={submitProject}
    >
      {error() && (
        <div class="mb-4 rounded border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-200">
          {error()}
        </div>
      )}

      <div class="flex min-h-0 flex-1 flex-col gap-4">
        <Tabs value={activeTab()} onChange={changeTab} class="min-h-0 flex-1">
          <Show when={!expanded()}>
            <TabsList>
              <TabsTrigger value="settings">Settings</TabsTrigger>
              <Show when={!isGitProject()}>
                <TabsTrigger value="files">Files</TabsTrigger>
              </Show>
              <TabsTrigger value="visual">Visual</TabsTrigger>
            </TabsList>
          </Show>

          <TabsContent value="settings">
            <div class="grid gap-4">
              <label class="field dark-field">
                <span>Name</span>
                <input value={name()} onInput={event => setName(event.currentTarget.value)} required />
              </label>

              <label class="field dark-field">
                <span>Type</span>
                <select value={type()} onInput={event => setType(event.currentTarget.value as ProjectType)}>
                  <option value="yaml">yaml</option>
                  <option value="python">python</option>
                  <option value="git">git</option>
                  <option value="source">source</option>
                </select>
              </label>

              <label class="field dark-field">
                <span>{type() === "git" ? "Git URL" : "Start URL"}</span>
                <input value={target()} onInput={event => setTarget(event.currentTarget.value)} required />
              </label>

              <label class="field dark-field">
                <span>Cron schedule</span>
                <input
                  placeholder="0 * * * *"
                  value={cron()}
                  onInput={event => setCron(event.currentTarget.value)}
                />
                <span
                  class={`text-xs ${cronDescription().valid ? "text-gray-400" : "text-amber-300"}`}
                >
                  {cronDescription().text}
                </span>
              </label>
            </div>
          </TabsContent>

          <TabsContent value="files" class="flex min-h-0 flex-1 flex-col">
            <div class="flex min-h-0 flex-1 flex-col gap-3">
              <div class="flex flex-wrap items-center justify-between gap-2">
                <div class="flex min-w-0 items-center gap-2 text-sm text-gray-300">
                  <Button
                    aria-label={fileSidebarOpen() ? "Collapse file sidebar" : "Expand file sidebar"}
                    size="icon"
                    type="button"
                    onClick={() => setFileSidebarOpen(value => !value)}
                  >
                    <FiSidebar size={14} stroke-width={2} aria-hidden="true" />
                  </Button>
                  <span class="min-w-0 truncate font-mono text-xs text-gray-400">
                    {selectedFile()?.path ?? "No file selected"}
                  </span>
                  <Show when={isDirty()}>
                    <FiAlertCircle
                      aria-label="Unsaved changes"
                      class="shrink-0 text-amber-300"
                      size={14}
                      stroke-width={2}
                    />
                  </Show>
                </div>
                <Button
                  aria-label={expanded() ? "Collapse editor" : "Expand editor"}
                  size="icon"
                  type="button"
                  onClick={toggleExpanded}
                >
                  {expanded() ? (
                    <FiMinimize2 size={13} stroke-width={2} aria-hidden="true" />
                  ) : (
                    <FiMaximize2 size={13} stroke-width={2} aria-hidden="true" />
                  )}
                </Button>
              </div>

              <div
                class={`project-file-editor ${fileSidebarOpen() ? "" : "project-file-editor-tree-collapsed"}`}
                style={{ "--project-chat-width": `${chatWidth()}px` }}
              >
                <Show when={fileSidebarOpen()}>
                  <aside class="project-file-tree">
                    <div class="mb-2 flex items-center justify-between gap-2">
                      <span class="text-xs font-medium uppercase text-gray-500">Files</span>
                      <div class="flex shrink-0 items-center gap-1.5">
                        <Button
                          aria-label="Add file"
                          size="icon"
                          type="button"
                          onClick={addFile}
                        >
                          <FiPlus size={13} stroke-width={2} aria-hidden="true" />
                        </Button>
                        <Button
                          aria-label="Collapse file sidebar"
                          size="icon"
                          type="button"
                          onClick={() => setFileSidebarOpen(false)}
                        >
                          <FiChevronsLeft size={13} stroke-width={2} aria-hidden="true" />
                        </Button>
                      </div>
                    </div>
                    <Show when={fileTree().length > 0}>
                      <div class="project-tree">
                        <For each={fileTree()}>{node => renderTreeNode(node)}</For>
                      </div>
                    </Show>
                  </aside>
                </Show>

                <Show when={!fileSidebarOpen()}>
                  <Button
                    aria-label="Expand file sidebar"
                    class="project-file-tree-rail"
                    size="icon"
                    type="button"
                    onClick={() => setFileSidebarOpen(true)}
                  >
                    <FiChevronsRight size={13} stroke-width={2} aria-hidden="true" />
                  </Button>
                </Show>

                <div class="project-code-pane">
                  {selectedFile() && isYamlPath(selectedFile()!.path) ? (
                    <div class="highlighted-editor">
                      <div ref={lineNumberRef} class="editor-line-numbers" aria-hidden="true">
                        <For each={lineNumbers()}>{number => <div>{number}</div>}</For>
                      </div>
                      <pre ref={highlightRef} class="syntax-highlight" aria-hidden="true">
                        <For each={codeLines()}>{line => <div>{highlightYamlLine(line)}</div>}</For>
                      </pre>
                      <textarea
                        spellcheck={false}
                        value={selectedContent()}
                        wrap="off"
                        onInput={event => updateSelectedFile({ content: event.currentTarget.value })}
                        onScroll={syncHighlightScroll}
                      />
                    </div>
                  ) : selectedFile() && isPythonPath(selectedFile()!.path) ? (
                    <div class="highlighted-editor">
                      <div ref={lineNumberRef} class="editor-line-numbers" aria-hidden="true">
                        <For each={lineNumbers()}>{number => <div>{number}</div>}</For>
                      </div>
                      <pre ref={highlightRef} class="syntax-highlight" aria-hidden="true">
                        <For each={codeLines()}>{line => <div>{highlightPythonLine(line)}</div>}</For>
                      </pre>
                      <textarea
                        spellcheck={false}
                        value={selectedContent()}
                        wrap="off"
                        onInput={event => updateSelectedFile({ content: event.currentTarget.value })}
                        onScroll={syncHighlightScroll}
                      />
                    </div>
                  ) : (
                    <div class="highlighted-editor">
                      <div ref={lineNumberRef} class="editor-line-numbers" aria-hidden="true">
                        <For each={lineNumbers()}>{number => <div>{number}</div>}</For>
                      </div>
                      <textarea
                        class="code-editor"
                        spellcheck={false}
                        value={selectedContent()}
                        wrap="off"
                        onInput={event => updateSelectedFile({ content: event.currentTarget.value })}
                        onScroll={syncHighlightScroll}
                      />
                    </div>
                  )}
                </div>

                <div
                  aria-label="Resize LLM chat"
                  class={`project-chat-resizer ${resizingChat() ? "project-chat-resizer-active" : ""}`}
                  role="separator"
                  tabIndex={0}
                  onPointerDown={startChatResize}
                />

                <aside class="project-llm-chat">
                  <div class="flex items-center gap-2 border-b border-gray-800 px-3 py-2 text-sm font-medium text-gray-200">
                    <FiMessageSquare size={14} stroke-width={2} aria-hidden="true" />
                    <span>LLM</span>
                  </div>
                  <div class="flex min-h-0 flex-1 flex-col p-3">
                    <LLMChat
                      messages={chatMessages()}
                      value={chatInput()}
                      pending={chatSending()}
                      loading={chatLoading()}
                      disabled={!props.projectId}
                      placeholder={props.projectId ? "Ask about this project" : "Save the project before using LLM"}
                      emptyTitle="No messages yet"
                      emptyDescription="Ask the assistant to inspect or edit this webuse project."
                      assistantName="webuse"
                      onValueChange={value => {
                        setChatInput(value);
                        setChatError(undefined);
                      }}
                      onSubmit={sendChatMessage}
                    />
                    <Show when={chatError()}>
                      <div class="mt-2 rounded border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-200">
                        {chatError()}
                      </div>
                    </Show>
                  </div>
                </aside>
              </div>
            </div>
          </TabsContent>

          <TabsContent value="visual" class="flex min-h-0 flex-1 flex-col">
            <ProjectVisual files={files()} target={target()} type={type()} />
          </TabsContent>
        </Tabs>

        <div class="flex justify-end gap-2">
          <ButtonLink
            class="!text-xs !leading-4"
            href="/projects"
            size="compact"
            onClick={event => {
              if (chatSending()) {
                event.preventDefault();
                blockAssistantLeave();
              }
            }}
          >
            Cancel
          </ButtonLink>
          <Button class="!text-xs !leading-4" variant="primary" size="compact" type="submit" disabled={saving()}>
            {saving() ? "Saving..." : props.submitLabel}
          </Button>
        </div>
      </div>
    </form>
  );
}
