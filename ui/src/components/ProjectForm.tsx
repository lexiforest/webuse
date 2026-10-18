import { TextField, TextFieldInput, TextFieldLabel } from "~/components/ui/text-field";
import { A, useBeforeLeave, useNavigate } from "@solidjs/router";
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

import { Button } from "~/components/ui/button";
import Harness, { type HarnessMessage, type ToolActivity } from "~/components/Harness";
import ProjectVisual from "~/components/ProjectVisual";
import ModelIndicator from "~/components/ModelIndicator";
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

export type ProjectFormValue = {
  name: string;
  target: string;
  cron?: string;
  crawlCommand?: string;
  config?: Record<string, unknown>;
  files?: ProjectFile[];
  revision?: string;
  workspacePath?: string;
  omitted?: string[];
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

type ProjectFormTab = "harness" | "settings" | "files" | "visual";

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
  return value === "harness" || value === "settings" || value === "files" || value === "visual" ? value : undefined;
}

function tabFromPath(pathname: string): ProjectFormTab | undefined {
  const segment = pathname.split("/").filter(Boolean).at(-1);
  return normalizeTab(segment);
}

function isConfigObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function initialFiles(value: ProjectFormValue): ProjectFile[] {
  if (value.files) {
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
    target: value.target,
    cron: (value.cron ?? "").trim(),
    crawlCommand: (value.crawlCommand ?? "").trim(),
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
  const [target, setTarget] = createSignal(props.initialValue.target);
  const [cron, setCron] = createSignal(props.initialValue.cron ?? "");
  const [crawlCommand, setCrawlCommand] = createSignal(props.initialValue.crawlCommand ?? "");
  const [files, setFiles] = createSignal<ProjectFile[]>(initialFileState);
  const [revision, setRevision] = createSignal(props.initialValue.revision);
  const [omitted, setOmitted] = createSignal(props.initialValue.omitted ?? []);
  const [externalChange, setExternalChange] = createSignal(false);
  const [selectedPath, setSelectedPath] = createSignal(files()[0]?.path ?? "webuse.yaml");
  const [saving, setSaving] = createSignal(false);
  const [error, setError] = createSignal<string>();
  const [fileSidebarOpen, setFileSidebarOpen] = createSignal(true);
  const [expanded, setExpanded] = createSignal(false);
  const [harnessWidth, setHarnessWidth] = createSignal(352);
  const [resizingHarness, setResizingHarness] = createSignal(false);
  const [harnessInput, setHarnessInput] = createSignal("");
  const [harnessMessages, setHarnessMessages] = createSignal<HarnessMessage[]>([]);
  const [harnessError, setHarnessError] = createSignal<string>();
  const [harnessSessionId, setHarnessSessionId] = createSignal<number>();
  const [harnessLoading, setHarnessLoading] = createSignal(false);
  const [harnessSending, setHarnessSending] = createSignal(false);
  const [harnessText, setHarnessText] = createSignal("");
  const [harnessTools, setHarnessTools] = createSignal<ToolActivity[]>([]);
  const [harnessStatus, setHarnessStatus] = createSignal("");
  let harnessRequest: AbortController | undefined;
  let harnessGeneration = 0;
  let disposed = false;
  onCleanup(() => { disposed = true; harnessRequest?.abort(); });
  const [activeTab, setActiveTab] = createSignal<ProjectFormTab>(
    props.defaultTab ?? "settings",
  );
  const [savedSnapshot, setSavedSnapshot] = createSignal(
    projectSnapshot({ ...props.initialValue, files: initialFileState }),
  );
  let highlightRef: HTMLPreElement | undefined;

  const currentSnapshot = createMemo(() =>
    projectSnapshot({
      name: name(),
      target: target(),
      cron: cron(),
      crawlCommand: crawlCommand(),
      files: files(),
    }),
  );
  const isDirty = createMemo(() => currentSnapshot() !== savedSnapshot());
  const acceptWorkspace = (project: ProjectFormValue) => {
    setFiles(project.files ?? []);
    setRevision(project.revision);
    setOmitted(project.omitted ?? []);
    setSavedSnapshot(projectSnapshot({ ...project, files: project.files ?? [] }));
    setExternalChange(false);
  };
  const reloadWorkspace = async (explicit = false) => {
    if (!props.projectId || harnessSending() || saving()) return;
    if (explicit && isDirty() && !window.confirm("Discard unsaved editor changes and reload files from disk?")) return;
    const loadedRevision = revision();
    try {
      const response = await fetch(props.endpoint);
      if (!response.ok) throw new Error(await readError(response, "Could not reload workspace."));
      const data = await response.json() as ProjectSaveResponse;
      if (!data.project || harnessSending() || saving() || loadedRevision !== revision()) return;
      if (!explicit && isDirty()) {
        if (data.project.revision !== revision()) setExternalChange(true);
        return;
      }
      if (!isDirty()) {
        setName(data.project.name);
        setTarget(data.project.target); setCron(data.project.cron ?? "");
        setCrawlCommand(data.project.crawlCommand ?? "");
      }
      acceptWorkspace(data.project);
      if (explicit) setError(undefined);
    } catch (err) { if (explicit) setError(err instanceof Error ? err.message : String(err)); }
  };
  const saveFiles = async () => {
    if (!props.projectId || harnessSending() || saving()) return;
    setSaving(true); setError(undefined);
    try {
      const response = await fetch(props.endpoint, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ files: files(), revision: revision() }) });
      if (!response.ok) throw new Error(await readError(response, "Could not save workspace."));
      const data = await response.json() as ProjectSaveResponse;
      if (data.project) acceptWorkspace(data.project);
    } catch (err) { setError(err instanceof Error ? err.message : String(err)); }
    finally { setSaving(false); }
  };
  const fileTree = createMemo(() => buildFileTree(files()));
  const cronDescription = createMemo(() => {
    const value = cron().trim();
    if (!value) {
      return { text: "Runs manually until a schedule is configured.", valid: true };
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

  useBeforeLeave(event => {
    if (event.defaultPrevented) {
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
      const nextTab = window.location.pathname.replace(/\/$/, "") === props.tabBasePath ? "harness" : tabFromPath(window.location.pathname);
      if (nextTab) {
        setActiveTab(nextTab);
      }
    };

    syncTabFromPath();
    window.addEventListener("popstate", syncTabFromPath);
    onCleanup(() => window.removeEventListener("popstate", syncTabFromPath));

    const handleBeforeUnload = (event: BeforeUnloadEvent) => {
      if (!isDirty()) {
        return;
      }
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", handleBeforeUnload);
    onCleanup(() => window.removeEventListener("beforeunload", handleBeforeUnload));
    const refresh = () => void reloadWorkspace();
    const poll = setInterval(refresh, 5000);
    window.addEventListener("focus", refresh);
    onCleanup(() => { clearInterval(poll); window.removeEventListener("focus", refresh); });

    const projectId = props.projectId;
    if (projectId) {
      setHarnessLoading(true);
      let historyLoading = false;
      const syncHistory = async () => {
        if (historyLoading || harnessRequest || disposed) return;
        historyLoading = true;
        const generation = harnessGeneration;
        try {
          const response = await fetch(`/api/assistant-project?project_id=${projectId}`);
          if (!response.ok) {
            throw new Error(await readError(response, `Failed to load assistant history (${response.status})`));
          }
          const data = await readJsonResponse<{
            session?: { id: number; title: string };
            messages?: HarnessMessage[];
            pendingMessageId?: number;
            running?: boolean;
            progress?: { text: string; tools: ToolActivity[]; status: string };
          }>(response);
          if (disposed || harnessRequest || generation !== harnessGeneration) return;
          const wasRunning = harnessSending();
          setHarnessSessionId(data.session?.id);
          setHarnessMessages(data.messages ?? []);
          setHarnessSending(!!data.running);
          setHarnessText(data.progress?.text ?? "");
          setHarnessTools(data.progress?.tools ?? []);
          setHarnessStatus(data.progress?.status ?? "");
          setHarnessError(data.running ? undefined : data.messages?.at(-1)?.metadata?.error);
          if (data.session?.title) applySessionTitle(data.session.title);
          setHarnessLoading(false);
          if (wasRunning && !data.running) {
            window.dispatchEvent(new Event("webuse:projects-changed"));
            void reloadWorkspace();
          }
          if (data.pendingMessageId && !data.running) await sendHarnessMessage(data.pendingMessageId);
        } catch (err) {
          if (!disposed) setHarnessError(err instanceof Error ? err.message : "Failed to load assistant history");
        } finally {
          historyLoading = false;
          if (!disposed) setHarnessLoading(false);
        }
      };
      void syncHistory();
      const historyPoll = setInterval(() => void syncHistory(), 2000);
      window.addEventListener("focus", syncHistory);
      onCleanup(() => { clearInterval(historyPoll); window.removeEventListener("focus", syncHistory); });
    }
  });

  const changeTab = (value: string) => {
    const requestedTab = normalizeTab(value) ?? "settings";
    const nextTab = requestedTab;
    setActiveTab(nextTab);
    if (props.tabBasePath) {
      window.history.pushState(null, "", nextTab === "harness" ? props.tabBasePath : `${props.tabBasePath}/${nextTab}`);
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

  const startHarnessResize = (event: PointerEvent) => {
    event.preventDefault();
    const pointerId = event.pointerId;
    const target = event.currentTarget as HTMLElement;
    const editor = target.closest(".project-file-editor") as HTMLElement | null;
    if (!editor) {
      return;
    }

    target.setPointerCapture(pointerId);
    setResizingHarness(true);

    const onMove = (moveEvent: PointerEvent) => {
      const rect = editor.getBoundingClientRect();
      const nextWidth = rect.right - moveEvent.clientX;
      const maxWidth = Math.max(280, rect.width - 360);
      setHarnessWidth(Math.round(Math.min(Math.max(nextWidth, 280), maxWidth)));
    };
    const onDone = () => {
      setResizingHarness(false);
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
    if (harnessSending() || saving()) return;
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
    if (harnessSending() || saving()) return;
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
    if (harnessSending() || saving()) return;
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
    if (harnessSending() || saving()) return;
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

  const applySessionTitle = (title: string) => {
    const saved = JSON.parse(savedSnapshot()) as ProjectFormValue;
    if (name() === saved.name) setName(title);
    setSavedSnapshot(projectSnapshot({ ...saved, name: title, files: saved.files ?? [] }));
  };

  const sendHarnessMessage = async (pendingMessageId?: number) => {
    if (harnessSending() || saving()) return;
    const prompt = harnessInput().trim();
    if (!prompt && !pendingMessageId) {
      return;
    }
    if (!props.projectId) {
      setHarnessError("Save the project before using Harness.");
      return;
    }

    harnessGeneration++;
    setHarnessError(undefined);
    setHarnessSending(true);
    setHarnessText(""); setHarnessTools([]); setHarnessStatus("");
    harnessRequest = new AbortController();
    if (!pendingMessageId) setHarnessMessages(current => [...current, { role: "user", content: prompt }]);
    setHarnessInput("");
    let accepted = false;
    let completed = false;

    try {
      const response = await fetch("/api/assistant-project", {
        method: "POST",
        signal: harnessRequest.signal,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          projectId: props.projectId,
          sessionId: harnessSessionId(),
          message: prompt,
          pendingMessageId,
          files: files(),
          revision: revision(),
          selectedPath: selectedPath(),
        }),
      });

      if (!response.ok) {
        throw new Error(await readError(response, `Assistant request failed (${response.status})`));
      }
      accepted = true;

      // The server saves submitted files before starting the background turn.
      const saved = JSON.parse(savedSnapshot()) as ProjectFormValue;
      setSavedSnapshot(projectSnapshot({ ...saved, files: files() }));

      if (!response.body) throw new Error("Assistant stream is unavailable.");
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      const receive = (line: string) => {
        if (disposed) return;
        const data = JSON.parse(line) as { type: string; text?: string; tool?: ToolActivity; error?: string; session?: { id: number }; sessionTitle?: string; messages?: HarnessMessage[]; files?: ProjectFile[]; selectedPath?: string; revision?: string; omitted?: string[] };
        if (data.type === "text") setHarnessText(current => current + (data.text || ""));
        if (data.type === "status") setHarnessStatus(data.text || "");
        if (data.type === "tool" && data.tool) {
          const tool = data.tool;
          setHarnessTools(current => current.some(item => item.id === tool.id) ? current.map(item => item.id === tool.id ? tool : item) : [...current, tool]);
          setHarnessStatus("");
        }
        if (data.type === "error") throw new Error(data.error || "Assistant failed.");
        if (data.type === "result") {
          completed = true;
          if (data.session?.id) setHarnessSessionId(data.session.id);
          if (data.messages) setHarnessMessages(data.messages);
          if (data.error) setHarnessError(data.error);
          if (data.sessionTitle) {
            applySessionTitle(data.sessionTitle);
          }
          if (data.files) {
            setFiles(data.files);
            setRevision(data.revision);
            setOmitted(data.omitted ?? []);
            const saved = JSON.parse(savedSnapshot()) as ProjectFormValue;
            setSavedSnapshot(projectSnapshot({ ...saved, files: data.files }));
            setExternalChange(false);
            setSelectedPath(data.selectedPath && data.files.some(file => file.path === data.selectedPath) ? data.selectedPath : data.files[0]?.path ?? "");
          }
        }
      };
      try {
        while (true) {
          const chunk = await reader.read();
          buffer += decoder.decode(chunk.value, { stream: !chunk.done });
          const lines = buffer.split("\n"); buffer = lines.pop() || "";
          for (const line of lines) if (line.trim()) receive(line);
          if (chunk.done) break;
        }
        if (buffer.trim()) receive(buffer);
        if (!completed) throw new Error("Assistant connection ended before the result arrived.");
      } finally { reader.releaseLock(); }
    } catch (err) {
      if (!disposed) setHarnessError(err instanceof Error ? err.message : "Assistant request failed");
    } finally {
      harnessRequest = undefined;
      if (!disposed) {
        // History polling reconnects to the turn if only the stream was interrupted.
        if (completed || !accepted) setHarnessSending(false);
        window.dispatchEvent(new Event("webuse:projects-changed"));
        void reloadWorkspace();
      }
    }
  };

  const stopHarness = async () => {
    setHarnessStatus("Stopping...");
    try {
      const response = await fetch(`/api/assistant-project?project_id=${props.projectId}`, { method: "DELETE" });
      if (!response.ok) throw new Error("Could not stop the assistant.");
    } catch (error) { setHarnessError(error instanceof Error ? error.message : String(error)); }
  };

  const renderHarness = () => (
    <>
      <Harness
        messages={harnessMessages()}
        value={harnessInput()}
        pending={harnessSending()}
        streamedText={harnessText()}
        tools={harnessTools()}
        pendingText={harnessStatus()}
        onCancel={stopHarness}
        loading={harnessLoading()}
        disabled={!props.projectId}
        placeholder={props.projectId ? "Ask about this project" : "Save the project before using Harness"}
        emptyTitle="No messages yet"
        emptyDescription="Ask the assistant to inspect, edit, and test this crawler. Python tools run on this computer."
        assistantName="webuse"
        onValueChange={value => {
          setHarnessInput(value);
          setHarnessError(undefined);
        }}
        onSubmit={() => void sendHarnessMessage()}
      />
      <Show when={harnessError()}>
        <div class="mt-2 rounded border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-200">
          {harnessError()}
        </div>
      </Show>
    </>
  );

  const deriveConfig = () => {
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
        <Button variant="outline"
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
          variant="destructive"
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
    if (harnessSending() || saving()) return;
    setError(undefined);
    setSaving(true);

    try {
      const parsedConfig = deriveConfig();

      const response = await fetch(props.endpoint, {
        method: props.method,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: name(),
          target: target(),
          cron: cron().trim(),
          crawlCommand: crawlCommand().trim(),
          config: parsedConfig,
          files: files(),
          revision: revision(),
        }),
      });

      if (!response.ok) {
        const data = (await response.json().catch(() => ({}))) as { error?: string };
        throw new Error(data.error || `Failed to save project (${response.status})`);
      }

      const data = (await response.json()) as ProjectSaveResponse;
      if (data.project) acceptWorkspace(data.project);
      window.dispatchEvent(new Event("webuse:projects-changed"));
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
      class={`flex min-h-0 flex-1 flex-col overflow-hidden ${
        expanded() ? "fixed inset-2 z-50 rounded-lg border border-gray-700 bg-gray-900 p-4 shadow-2xl" : ""
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
              <TabsTrigger value="harness">Harness</TabsTrigger>
              <TabsTrigger value="files">Files</TabsTrigger>
              <TabsTrigger value="visual">Visual</TabsTrigger>
              <TabsTrigger value="settings">Settings</TabsTrigger>
            </TabsList>
          </Show>

          <Show when={props.projectId && activeTab() !== "harness"}>
            <div class="shrink-0 text-xs text-gray-400">
              <div class="break-all">Workspace: {props.initialValue.workspacePath}</div>
              <div>Executions use the current files on disk. Save edits before running; use Git to track and restore code.</div>
              <Show when={externalChange()}><div class="text-amber-300">Files changed on disk. Reload before saving; your editor changes have been kept.</div></Show>
              <Show when={omitted().length}><div>{omitted().length} binary or large files are available on disk but omitted from this editor.</div></Show>
            </div>
          </Show>

          <TabsContent value="harness" class="flex min-h-0 flex-1 flex-col">
            <div class="mx-auto flex min-h-0 w-full max-w-3xl flex-1 flex-col">
              {renderHarness()}
            </div>
          </TabsContent>

          <TabsContent value="settings">
            <div class="grid gap-4">
              <TextField value={name()} required onChange={value => setName(value)}>
                <TextFieldLabel>Name</TextFieldLabel>
                <TextFieldInput />
              </TextField>

              <TextField value={target()} required onChange={value => setTarget(value)}>
                <TextFieldLabel>Target</TextFieldLabel>
                <TextFieldInput />
              </TextField>

              <TextField value={crawlCommand()} onChange={value => setCrawlCommand(value)}>
                <TextFieldLabel>Crawl command</TextFieldLabel>
                <TextFieldInput placeholder="Default: Webuse crawl" />
                <span class="text-xs text-gray-400">Run from this project's workspace. Leave empty for Webuse. For example: scrapy crawl books -o "$WEBUSE_OUTPUT_PATH"</span>
                <span class="text-xs text-gray-400">Write JSONL to WEBUSE_OUTPUT_PATH for dashboard records. Sample commands receive WEBUSE_MAX_REQUESTS and must enforce that limit themselves.</span>
              </TextField>

              <TextField value={cron()} onChange={value => setCron(value)}>
                <TextFieldLabel>Cron schedule (UTC)</TextFieldLabel>
                <TextFieldInput placeholder="0 * * * *" />
                <span
                  class={`text-xs ${cronDescription().valid ? "text-gray-400" : "text-amber-300"}`}
                >
                  {cronDescription().text}
                </span>
              </TextField>
            </div>
          </TabsContent>

          <TabsContent value="files" class="flex min-h-0 flex-1 flex-col">
            <div class="flex min-h-0 flex-1 flex-col gap-3">
              <div class="flex flex-wrap items-center justify-between gap-2">
                <div class="flex min-w-0 items-center gap-2 text-sm text-gray-300">
                  <Button variant="outline"
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
                <div class="ml-auto flex min-w-0 items-center gap-2">
                  <Show when={expanded()}><div class="min-w-0 max-w-48"><ModelIndicator /></div></Show>
                  <Button variant="outline"
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
              </div>

              <div
                class={`project-file-editor ${fileSidebarOpen() ? "" : "project-file-editor-tree-collapsed"}`}
                style={{ "--project-harness-width": `${harnessWidth()}px` }}
              >
                <Show when={fileSidebarOpen()}>
                  <aside class="project-file-tree">
                    <div class="mb-2 flex items-center justify-between gap-2">
                      <span class="text-xs font-medium uppercase text-gray-500">Files</span>
                      <div class="flex shrink-0 items-center gap-1.5">
                        <Button variant="outline"
                          aria-label="Add file"
                          size="icon"
                          type="button"
                          onClick={addFile}
                        >
                          <FiPlus size={13} stroke-width={2} aria-hidden="true" />
                        </Button>
                        <Button variant="outline"
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
                  <Button variant="outline"
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
                        readOnly={harnessSending() || saving()}
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
                        readOnly={harnessSending() || saving()}
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
                        readOnly={harnessSending() || saving()}
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
                  aria-label="Resize Harness"
                  class={`project-harness-resizer ${resizingHarness() ? "project-harness-resizer-active" : ""}`}
                  role="separator"
                  tabIndex={0}
                  onPointerDown={startHarnessResize}
                />

                <aside class="project-harness">
                  <div class="flex items-center gap-2 border-b border-gray-800 px-3 py-2 text-sm font-medium text-gray-200">
                    <FiMessageSquare size={14} stroke-width={2} aria-hidden="true" />
                    <span>Harness</span>
                  </div>
                  <div class="flex min-h-0 flex-1 flex-col p-3">
                    {renderHarness()}
                  </div>
                </aside>
              </div>
            </div>
          </TabsContent>

          <TabsContent value="visual" class="flex min-h-0 flex-1 flex-col">
            <ProjectVisual files={files()} target={target()} />
          </TabsContent>
        </Tabs>

        <Show when={activeTab() !== "harness"}>
          <div class="flex justify-end gap-2">
            <Show when={props.projectId}>
              <Button variant="outline" type="button" size="sm" disabled={saving() || harnessSending()} onClick={() => void reloadWorkspace(true)}>Reload files</Button>
              <Button variant="outline" type="button" size="sm" disabled={saving() || harnessSending()} onClick={() => void saveFiles()}>Save files</Button>
            </Show>
            <Button variant="outline" as={A}
              class="!text-xs !leading-4"
              href="/projects"
              size="sm"
            >
              Cancel
            </Button>
            <Button class="!text-xs !leading-4" variant="default" size="sm" type="submit" disabled={saving() || harnessSending()}>
              {saving() ? "Saving..." : props.submitLabel}
            </Button>
          </div>
        </Show>
      </div>
    </form>
  );
}
