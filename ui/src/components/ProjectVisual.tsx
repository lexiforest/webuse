import { For, Show, createEffect, createMemo, createSignal, onMount } from "solid-js";
import { parse as parseYaml } from "yaml";

type ProjectFile = {
  path: string;
  content: string;
};

type ProjectVisualProps = {
  files: ProjectFile[];
  target: string;
  type: string;
};

type VisualNodeKind = "start" | "follow" | "extract" | "item" | "database" | "route" | "python" | "note";

type VisualNode = {
  id: string;
  label: string;
  detail?: string;
  kind: VisualNodeKind;
};

type VisualEdge = {
  from: string;
  to: string;
  label?: string;
};

type VisualGraph = {
  nodes: VisualNode[];
  edges: VisualEdge[];
  notes: string[];
};

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function asList(value: unknown): unknown[] {
  if (Array.isArray(value)) {
    return value;
  }
  return value === undefined || value === null || value === "" ? [] : [value];
}

function scalar(value: unknown) {
  return typeof value === "string" || typeof value === "number" || typeof value === "boolean"
    ? String(value)
    : "";
}

function truncate(value: string, max = 52) {
  return value.length > max ? `${value.slice(0, max - 1)}...` : value;
}

function node(
  id: string,
  label: string,
  detail: string | undefined,
  kind: VisualNodeKind,
): VisualNode {
  return {
    id,
    label,
    detail,
    kind,
  };
}

function cssOrXpath(rule: Record<string, unknown>) {
  if (typeof rule.css === "string") {
    return `css: ${rule.css}`;
  }
  if (typeof rule.xpath === "string") {
    return `xpath: ${rule.xpath}`;
  }
  return "follow rule";
}

function extractFieldNames(extract: Record<string, unknown>) {
  const fields = asRecord(extract.fields);
  return Object.keys(fields);
}

function itemExtractors(extract: Record<string, unknown>) {
  return Object.entries(extract)
    .map(([name, value]) => ({ name, spec: asRecord(value) }))
    .filter(item => Object.keys(item.spec).length > 0);
}

function inlineSpiders(parsed: Record<string, unknown>) {
  const spiders = asRecord(parsed.spiders);
  const entries = Object.entries(spiders)
    .map(([name, value]) => ({ name, config: asRecord(value) }))
    .filter(entry => {
      const keys = Object.keys(entry.config);
      return keys.length > 0 && !("path" in entry.config) && !("module" in entry.config) && !("config" in entry.config);
    });
  return entries;
}

function yamlGraph(files: ProjectFile[], target: string): VisualGraph | undefined {
  const configFile = files.find(file => file.path === "webuse.yaml" || file.path === "webuse.yml");
  if (!configFile) {
    return undefined;
  }

  let parsed: Record<string, unknown>;
  try {
    parsed = asRecord(parseYaml(configFile.content));
  } catch (error) {
    return graph(
      [node("yaml-error", "YAML parse error", error instanceof Error ? error.message : "Invalid YAML", "note")],
      [],
      ["Fix webuse.yaml to render the workflow graph."],
    );
  }
  const spiders = inlineSpiders(parsed);
  const notes: string[] = [];
  if (Object.keys(asRecord(parsed.spiders)).length > 0 && spiders.length === 0) {
    return graph(
      [node("external", "External spiders", "Use referenced Python or YAML spider files", "note")],
      [],
      ["Inline spider configs render here. Referenced spider files are shown by the Python view."],
    );
  }

  const nodes: VisualNode[] = [];
  const edges: VisualEdge[] = [];

  spiders.forEach(({ name: spiderName, config: spiderConfig }, spiderIndex) => {
    const startUrls = asList(spiderConfig.start_urls).map(scalar).filter(Boolean);
    const starts = startUrls.length > 0 ? startUrls : target ? [target] : ["start"];
    const pages = asRecord(spiderConfig.pages);
    const prefix = `${spiderIndex}-${spiderName.replace(/[^a-zA-Z0-9]/g, "-")}`;

    if (Array.isArray(spiderConfig.allowed_domains)) {
      notes.push(`${spiderName}.allowed_domains: ${spiderConfig.allowed_domains.map(scalar).filter(Boolean).join(", ")}`);
    }
    if (spiderConfig.max_depth !== undefined) {
      notes.push(`${spiderName}.max_depth: ${scalar(spiderConfig.max_depth)}`);
    }
    if (spiderConfig.max_requests !== undefined) {
      notes.push(`${spiderName}.max_requests: ${scalar(spiderConfig.max_requests)}`);
    }

    starts.forEach((url, index) => {
      nodes.push(node(`start-${prefix}-${index}`, `Start: ${spiderName}`, truncate(url), "start"));
    });

    Object.entries(pages).forEach(([category, rawPage], pageIndex) => {
      const page = asRecord(rawPage);
      const sourceId = category === "default" ? undefined : `page-${prefix}-${category}`;
      if (sourceId) {
        nodes.push(node(sourceId, `Page: ${category}`, spiderName, "route"));
      }
      const sourceNodes = sourceId ? [sourceId] : starts.map((_, startIndex) => `start-${prefix}-${startIndex}`);

      asList(page.follow).map(asRecord).forEach((rule, ruleIndex) => {
        const followId = `follow-${prefix}-${pageIndex}-${ruleIndex}`;
        const targetCategory = scalar(rule.category) || "page";
        const pageId = `page-${prefix}-${targetCategory}`;
        nodes.push(node(followId, "Follow", cssOrXpath(rule), "follow"));
        nodes.push(
          node(
            pageId,
            `Page: ${targetCategory}`,
            rule.same_domain ? "same domain" : spiderName,
            "route",
          ),
        );
        sourceNodes.forEach(source => edges.push({ from: source, to: followId }));
        edges.push({ from: followId, to: pageId, label: scalar(rule.attr) || "href" });
      });

      itemExtractors(asRecord(page.extract)).forEach((item, itemIndex) => {
        const extractId = `extract-${prefix}-${pageIndex}-${itemIndex}`;
        const itemId = `item-${prefix}-${pageIndex}-${itemIndex}`;
        const fields = extractFieldNames(item.spec);
        nodes.push(
          node(
            extractId,
            `Extract: ${category}`,
            item.spec.item_css ? `item_css: ${scalar(item.spec.item_css)}` : "document",
            "extract",
          ),
        );
        nodes.push(
          node(
            itemId,
            `Item: ${item.name}`,
            fields.length > 0 ? fields.join(", ") : "configured fields",
            "item",
          ),
        );
        sourceNodes.forEach(source => edges.push({ from: source, to: extractId }));
        edges.push({ from: extractId, to: itemId });
      });
    });
  });

  return graph(nodes, edges, notes);
}

function stringListFromAssignment(content: string, name: string) {
  const match = content.match(new RegExp(`\\b${name}\\s*=\\s*(\\[[\\s\\S]*?\\]|["'][^"']+["'])`));
  if (!match) {
    return [];
  }
  return [...match[1].matchAll(/["']([^"']+)["']/g)].map(item => item[1]);
}

function methodBlocks(content: string) {
  const lines = content.split("\n");
  const blocks: Array<{ name: string; body: string }> = [];

  for (let index = 0; index < lines.length; index += 1) {
    const match = lines[index].match(/^(\s*)def\s+(parse\w*)\s*\(/);
    if (!match) {
      continue;
    }
    const indent = match[1].length;
    const body: string[] = [];
    for (let cursor = index + 1; cursor < lines.length; cursor += 1) {
      const line = lines[cursor];
      if (line.trim() && line.search(/\S/) <= indent) {
        break;
      }
      body.push(line);
    }
    blocks.push({ name: match[2], body: body.join("\n") });
  }

  return blocks;
}

function routeEntries(content: string) {
  const routes = new Map<string, string>();
  const match = content.match(/\broutes\s*=\s*\{([\s\S]*?)\}/);
  if (!match) {
    return routes;
  }
  for (const entry of match[1].matchAll(/["']([^"']+)["']\s*:\s*([A-Za-z_]\w*)/g)) {
    routes.set(entry[1], entry[2]);
  }
  return routes;
}

function requestCategories(body: string) {
  const categories = new Set<string>();
  for (const match of body.matchAll(/category\s*=\s*["']([^"']+)["']/g)) {
    categories.add(match[1]);
  }
  if (/yield\s+.*(?:RequestOptions|CrawlRequest|response\.request|response\.follow)\s*\(/.test(body) && categories.size === 0) {
    categories.add("default");
  }
  return [...categories];
}

function itemOutputs(body: string) {
  const outputs = new Set<string>();
  for (const block of body.matchAll(/yield\s+\{([\s\S]*?)\}/g)) {
    const fields = [...block[1].matchAll(/["']([^"']+)["']\s*:/g)].map(match => match[1]);
    outputs.add(fields.length > 0 ? fields.join(", ") : "dict item");
  }
  for (const call of body.matchAll(/yield\s+([A-Z][A-Za-z0-9_]*)\s*\(/g)) {
    if (!/(?:Request|Options)$/.test(call[1])) {
      outputs.add(call[1]);
    }
  }
  return [...outputs];
}

function pythonGraph(files: ProjectFile[], target: string): VisualGraph | undefined {
  const pythonFiles = files.filter(file => file.path.endsWith(".py"));
  if (pythonFiles.length === 0) {
    return undefined;
  }

  const content = pythonFiles.map(file => `# ${file.path}\n${file.content}`).join("\n\n");
  const starts = stringListFromAssignment(content, "start_urls");
  const routes = routeEntries(content);
  const methods = methodBlocks(content);
  const notes: string[] = ["Python graph is inferred statically from spider attributes and parse_* methods."];
  const allowedDomains = stringListFromAssignment(content, "allowed_domains");
  if (allowedDomains.length > 0) {
    notes.push(`allowed_domains: ${allowedDomains.join(", ")}`);
  }
  const maxDepth = content.match(/\bmax_depth\s*=\s*([0-9]+)/);
  if (maxDepth) {
    notes.push(`max_depth: ${maxDepth[1]}`);
  }

  const nodes: VisualNode[] = [];
  const edges: VisualEdge[] = [];
  const startValues = starts.length > 0 ? starts : target ? [target] : ["Spider.start()"];
  startValues.forEach((url, index) => {
    nodes.push(node(`start-${index}`, "Start URL", truncate(url), "start"));
  });

  const parseMethods = methods.length > 0 ? methods : [{ name: "parse", body: "" }];
  parseMethods.forEach(method => {
    const parseId = `parse-${method.name}`;
    nodes.push(node(parseId, method.name, "Python parse method", "python"));
    if (method.name === "parse") {
      startValues.forEach((_, startIndex) => edges.push({ from: `start-${startIndex}`, to: parseId }));
    }

    const categories = requestCategories(method.body);
    categories.forEach(category => {
      const targetMethod = routes.get(category) ?? `parse_${category}`;
      const routeId = `route-${method.name}-${category}`;
      nodes.push(node(routeId, `Request: ${category}`, targetMethod, "route"));
      edges.push({ from: parseId, to: routeId, label: "yield request" });
    });

    itemOutputs(method.body).forEach((fields, itemIndex) => {
      const itemId = `item-${method.name}-${itemIndex}`;
      nodes.push(node(itemId, "Item", fields, "item"));
      edges.push({ from: parseId, to: itemId, label: "yield item" });
    });
  });

  if (!content.includes("yield") && methods.length > 0) {
    notes.push("No yielded requests or items were detected in parse methods.");
  }

  return graph(nodes, edges, notes);
}

function graph(nodes: VisualNode[], edges: VisualEdge[], notes: string[]): VisualGraph {
  if (nodes.length === 0) {
    nodes.push(node("empty", "No workflow detected", "Add webuse.yaml or a Python spider", "note"));
  }
  addDatabaseNode(nodes, edges);
  return { nodes, edges, notes };
}

function addDatabaseNode(nodes: VisualNode[], edges: VisualEdge[]) {
  const itemNodes = nodes.filter(item => item.kind === "item");
  if (itemNodes.length === 0 || nodes.some(item => item.kind === "database")) {
    return;
  }
  const database = node("database", "Database", "items", "database");
  nodes.push(database);
  for (const item of itemNodes) {
    edges.push({ from: item.id, to: database.id, label: "store" });
  }
}

const mermaidShapes: Record<VisualNodeKind, string> = {
  start: "flag",
  follow: "doc",
  extract: "tri",
  item: "lin-rect",
  database: "database",
  route: "doc",
  python: "tag-doc",
  note: "brace",
};

const mermaidClasses: Record<VisualNodeKind, string> = {
  start: "startNode",
  follow: "followNode",
  extract: "extractNode",
  item: "itemNode",
  database: "databaseNode",
  route: "routeNode",
  python: "pythonNode",
  note: "noteNode",
};

let mermaidRenderCounter = 0;
let mermaidPromise: Promise<typeof import("mermaid").default> | undefined;

function mermaidId(id: string) {
  return `n_${id.replace(/[^A-Za-z0-9_]/g, "_")}`;
}

function htmlEscape(value: string) {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function quotedMermaid(value: string) {
  return JSON.stringify(
    value
      .split("<br/>")
      .map(part => htmlEscape(part))
      .join("<br/>")
      .replace(/\r?\n/g, "<br/>"),
  );
}

function nodeLabel(item: VisualNode) {
  return item.detail ? `${item.label}<br/>${truncate(item.detail, 70)}` : item.label;
}

function edgeLabel(label: string | undefined) {
  if (!label) {
    return "-->";
  }
  return `-- ${quotedMermaid(label)} -->`;
}

function mermaidDefinition(visual: VisualGraph) {
  const lines = [
    "flowchart LR",
    "  classDef startNode fill:#075985,stroke:#38bdf8,color:#f8fafc;",
    "  classDef followNode fill:#365314,stroke:#84cc16,color:#f8fafc;",
    "  classDef extractNode fill:#581c87,stroke:#c084fc,color:#f8fafc;",
    "  classDef itemNode fill:#064e3b,stroke:#34d399,color:#f8fafc;",
    "  classDef databaseNode fill:#0f172a,stroke:#38bdf8,color:#f8fafc;",
    "  classDef routeNode fill:#1f2937,stroke:#94a3b8,color:#f8fafc;",
    "  classDef pythonNode fill:#1f2937,stroke:#94a3b8,color:#f8fafc;",
    "  classDef noteNode fill:#422006,stroke:#f59e0b,color:#f8fafc;",
  ];

  for (const item of visual.nodes) {
    lines.push(
      `  ${mermaidId(item.id)}@{ shape: ${mermaidShapes[item.kind]}, label: ${quotedMermaid(nodeLabel(item))} }`,
    );
    lines.push(`  class ${mermaidId(item.id)} ${mermaidClasses[item.kind]};`);
  }

  for (const edge of visual.edges) {
    lines.push(`  ${mermaidId(edge.from)} ${edgeLabel(edge.label)} ${mermaidId(edge.to)}`);
  }

  return lines.join("\n");
}

async function loadMermaid() {
  mermaidPromise ??= import("mermaid").then(module => {
    module.default.initialize({
      startOnLoad: false,
      securityLevel: "strict",
      theme: "base",
      flowchart: {
        curve: "basis",
        htmlLabels: true,
        nodeSpacing: 24,
        rankSpacing: 42,
      },
      themeVariables: {
        background: "#0f172a",
        fontFamily: "Inter, ui-sans-serif, system-ui, sans-serif",
        fontSize: "12px",
        lineColor: "#64748b",
        primaryTextColor: "#f8fafc",
      },
    });
    return module.default;
  });
  return mermaidPromise;
}

export default function ProjectVisual(props: ProjectVisualProps) {
  const [mounted, setMounted] = createSignal(false);
  const [renderedSvg, setRenderedSvg] = createSignal("");
  const [renderError, setRenderError] = createSignal("");
  let renderVersion = 0;

  const visual = createMemo(() => {
    if (props.type === "git") {
      return graph(
        [
          node("git", "Git checkout", truncate(props.target), "start"),
          node("worker", "Worker run", "clone/pull under work directory", "python"),
          node("project", "Project files", "read from checkout", "route"),
        ],
        [
          { from: "git", to: "worker" },
          { from: "worker", to: "project" },
        ],
        ["Git-linked projects are not editable in the UI; the workflow is resolved from the checkout at run time."],
      );
    }
    if (props.type === "python") {
      return pythonGraph(props.files, props.target) ?? yamlGraph(props.files, props.target) ?? graph([], [], []);
    }
    return yamlGraph(props.files, props.target) ?? pythonGraph(props.files, props.target) ?? graph([], [], []);
  });

  const definition = createMemo(() => mermaidDefinition(visual()));

  onMount(() => setMounted(true));

  createEffect(() => {
    if (!mounted()) {
      return;
    }

    const source = definition();
    const renderId = `project-visual-${Date.now()}-${mermaidRenderCounter++}`;
    const currentRender = ++renderVersion;
    setRenderError("");
    setRenderedSvg("");

    void loadMermaid()
      .then(mermaid => mermaid.render(renderId, source))
      .then(result => {
        if (currentRender === renderVersion) {
          setRenderedSvg(result.svg);
        }
      })
      .catch(error => {
        if (currentRender === renderVersion) {
          setRenderError(error instanceof Error ? error.message : "Unable to render workflow graph.");
        }
      });
  });

  return (
    <div class="project-visual">
      <div class="project-visual-canvas">
        <Show when={renderedSvg()} fallback={<div class="project-visual-loading">Rendering workflow...</div>}>
          <div class="project-visual-mermaid" role="img" aria-label="Project workflow graph" innerHTML={renderedSvg()} />
        </Show>
        <Show when={renderError()}>
          <div class="project-visual-error">{renderError()}</div>
        </Show>
      </div>
      <Show when={visual().notes.length > 0}>
        <div class="project-visual-notes">
          <For each={visual().notes}>{note => <div>{note}</div>}</For>
        </div>
      </Show>
    </div>
  );
}
