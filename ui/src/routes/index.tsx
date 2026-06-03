import { For, Show, createMemo, createSignal } from "solid-js";

type Mode = "fetch" | "crawl";
type Format = "yaml" | "toml";
type Method = "GET" | "POST" | "PUT" | "DELETE";
type SelectorKind = "css" | "xpath" | "smart";

type RequestDefaults = {
  headers: string;
  cookies: string;
  params: string;
  timeout: string;
  impersonate: string;
  proxy: string;
  verify: boolean;
  followRedirects: boolean;
  ja3: string;
  akamai: string;
};

type FollowRule = {
  id: number;
  kind: "css" | "xpath";
  selector: string;
  attr: string;
  sameDomain: boolean;
  include: string;
  exclude: string;
  maxDepth: string;
  allowedDomains: string;
};

type ExtractRule = {
  id: number;
  name: string;
  kind: SelectorKind;
  selector: string;
  attr: string;
  all: boolean;
};

const methods: Method[] = ["GET", "POST", "PUT", "DELETE"];
const formats: Format[] = ["yaml", "toml"];
let nextId = 3;

const defaultDefaults = (): RequestDefaults => ({
  headers: "",
  cookies: "",
  params: "",
  timeout: "10",
  impersonate: "chrome",
  proxy: "",
  verify: true,
  followRedirects: true,
  ja3: "",
  akamai: "",
});

const compactLines = (value: string) =>
  value
    .split("\n")
    .map(line => line.trim())
    .filter(Boolean);

const parsePairs = (value: string) => {
  const result: Record<string, string> = {};
  for (const line of compactLines(value)) {
    const index = line.indexOf("=");
    if (index > 0) result[line.slice(0, index).trim()] = line.slice(index + 1).trim();
  }
  return result;
};

const list = (value: string) =>
  value
    .split(/[\n,]/)
    .map(item => item.trim())
    .filter(Boolean);

const scalar = (value: string) => {
  if (value === "") return undefined;
  const number = Number(value);
  if (!Number.isNaN(number) && value.trim() !== "") return number;
  return value;
};

const quoteToml = (value: string) => JSON.stringify(value);

const yamlScalar = (value: unknown) => {
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "number") return String(value);
  return JSON.stringify(String(value));
};

const appendYamlObject = (lines: string[], indent: string, values: Record<string, unknown>) => {
  for (const [key, value] of Object.entries(values)) {
    if (value === undefined || value === "" || value === null) continue;
    if (Array.isArray(value)) {
      if (!value.length) continue;
      lines.push(`${indent}${key}:`);
      for (const item of value) {
        if (typeof item === "object" && item !== null) {
          const entries = Object.entries(item as Record<string, unknown>).filter(([, entry]) => entry !== "");
          if (!entries.length) continue;
          const [first, ...rest] = entries;
          lines.push(`${indent}  - ${first[0]}: ${yamlScalar(first[1])}`);
          appendYamlObject(lines, `${indent}    `, Object.fromEntries(rest));
        } else {
          lines.push(`${indent}  - ${yamlScalar(item)}`);
        }
      }
    } else if (typeof value === "object") {
      const entries = Object.entries(value as Record<string, unknown>).filter(([, item]) => item !== "");
      if (!entries.length) continue;
      lines.push(`${indent}${key}:`);
      appendYamlObject(lines, `${indent}  `, Object.fromEntries(entries));
    } else {
      lines.push(`${indent}${key}: ${yamlScalar(value)}`);
    }
  }
};

const appendTomlObject = (lines: string[], section: string, values: Record<string, unknown>) => {
  const scalars: string[] = [];
  const nested: [string, Record<string, unknown>][] = [];
  for (const [key, value] of Object.entries(values)) {
    if (value === undefined || value === "" || value === null) continue;
    if (Array.isArray(value)) {
      if (!value.length) continue;
      scalars.push(`${key} = [${value.map(item => quoteToml(String(item))).join(", ")}]`);
    } else if (typeof value === "object") {
      nested.push([key, value as Record<string, unknown>]);
    } else if (typeof value === "boolean" || typeof value === "number") {
      scalars.push(`${key} = ${value}`);
    } else {
      scalars.push(`${key} = ${quoteToml(String(value))}`);
    }
  }
  if (scalars.length) {
    lines.push(`[${section}]`);
    lines.push(...scalars);
    lines.push("");
  }
  for (const [key, value] of nested) appendTomlObject(lines, `${section}.${key}`, value);
};

const requestDefaults = (defaults: RequestDefaults) => ({
  headers: parsePairs(defaults.headers),
  cookies: parsePairs(defaults.cookies),
  params: parsePairs(defaults.params),
  timeout: scalar(defaults.timeout),
  impersonate: defaults.impersonate,
  proxy: defaults.proxy,
  verify: defaults.verify,
  follow_redirects: defaults.followRedirects,
  ja3: defaults.ja3,
  akamai: defaults.akamai,
});

const cleanObject = (value: Record<string, unknown>) =>
  Object.fromEntries(
    Object.entries(value).filter(([, item]) => {
      if (item === undefined || item === "" || item === null) return false;
      if (Array.isArray(item)) return item.length > 0;
      if (typeof item === "object") return Object.keys(item as Record<string, unknown>).length > 0;
      return true;
    })
  );

const fieldId = (prefix: string, id: number, field: string) => `${prefix}-${id}-${field}`;

export default function Home() {
  const [mode, setMode] = createSignal<Mode>("crawl");
  const [format, setFormat] = createSignal<Format>("yaml");
  const [fetchUrl, setFetchUrl] = createSignal("https://example.com/products");
  const [method, setMethod] = createSignal<Method>("GET");
  const [jsonOutput, setJsonOutput] = createSignal(false);
  const [smartPrompt, setSmartPrompt] = createSignal("primary product link");
  const [smartKey, setSmartKey] = createSignal("primary-product-link");
  const [smartStore, setSmartStore] = createSignal(".webuse/selectors.json");
  const [seeds, setSeeds] = createSignal("https://example.com");
  const [maxDepth, setMaxDepth] = createSignal("2");
  const [maxRequests, setMaxRequests] = createSignal("100");
  const [concurrency, setConcurrency] = createSignal("5");
  const [allowedDomains, setAllowedDomains] = createSignal("example.com");
  const [defaults, setDefaults] = createSignal<RequestDefaults>(defaultDefaults());
  const [followRules, setFollowRules] = createSignal<FollowRule[]>([
    {
      id: 1,
      kind: "css",
      selector: "a.next",
      attr: "href",
      sameDomain: true,
      include: "",
      exclude: "",
      maxDepth: "1",
      allowedDomains: "example.com",
    },
  ]);
  const [extractRules, setExtractRules] = createSignal<ExtractRule[]>([
    { id: 2, name: "title", kind: "css", selector: "h1", attr: "", all: false },
  ]);
  const [testVisible, setTestVisible] = createSignal(false);

  const setDefault = <K extends keyof RequestDefaults>(key: K, value: RequestDefaults[K]) => {
    setDefaults(current => ({ ...current, [key]: value }));
  };

  const updateFollow = (id: number, values: Partial<FollowRule>) => {
    setFollowRules(current => current.map(rule => (rule.id === id ? { ...rule, ...values } : rule)));
  };

  const updateExtract = (id: number, values: Partial<ExtractRule>) => {
    setExtractRules(current => current.map(rule => (rule.id === id ? { ...rule, ...values } : rule)));
  };

  const addFollow = () => {
    setFollowRules(current => [
      ...current,
      {
        id: nextId++,
        kind: "css",
        selector: "a[href]",
        attr: "href",
        sameDomain: true,
        include: "",
        exclude: "",
        maxDepth: "",
        allowedDomains: "",
      },
    ]);
  };

  const addExtract = () => {
    setExtractRules(current => [
      ...current,
      { id: nextId++, name: `field_${current.length + 1}`, kind: "css", selector: "", attr: "", all: false },
    ]);
  };

  const configObject = createMemo(() => {
    if (mode() === "fetch") {
      return {
        fetch: cleanObject({
          url: fetchUrl(),
          method: method(),
          json_output: jsonOutput(),
          smart_store: smartStore(),
          smart_key: smartKey(),
          ...requestDefaults(defaults()),
        }),
      };
    }

    const extract: Record<string, unknown> = {};
    for (const rule of extractRules()) {
      if (!rule.name || !rule.selector) continue;
      extract[rule.name] = cleanObject({
        [rule.kind]: rule.selector,
        attr: rule.attr,
        all: rule.all,
      });
    }

    return {
      crawl: cleanObject({
        seeds: list(seeds()),
        max_depth: scalar(maxDepth()),
        max_requests: scalar(maxRequests()),
        concurrency: scalar(concurrency()),
        allowed_domains: list(allowedDomains()),
        request_defaults: requestDefaults(defaults()),
        follow: followRules()
          .filter(rule => rule.selector)
          .map(rule =>
            cleanObject({
              [rule.kind]: rule.selector,
              attr: rule.attr || "href",
              same_domain: rule.sameDomain,
              include: rule.include,
              exclude: rule.exclude,
              max_depth: scalar(rule.maxDepth),
              allowed_domains: list(rule.allowedDomains),
            })
          ),
        extract,
      }),
    };
  });

  const yamlOutput = createMemo(() => {
    const lines: string[] = [];
    appendYamlObject(lines, "", configObject());
    return `${lines.join("\n")}\n`;
  });

  const tomlOutput = createMemo(() => {
    const lines: string[] = [];
    const config = configObject();
    if ("fetch" in config) appendTomlObject(lines, "fetch", config.fetch as Record<string, unknown>);
    if ("crawl" in config) {
      const crawl = config.crawl as Record<string, unknown>;
      const { follow, extract, request_defaults, ...rest } = crawl;
      appendTomlObject(lines, "crawl", rest);
      if (request_defaults) appendTomlObject(lines, "crawl.request_defaults", request_defaults as Record<string, unknown>);
      for (const rule of (follow as Record<string, unknown>[] | undefined) || []) {
        lines.push("[[crawl.follow]]");
        for (const [key, value] of Object.entries(rule)) {
          if (Array.isArray(value)) lines.push(`${key} = [${value.map(item => quoteToml(String(item))).join(", ")}]`);
          else if (typeof value === "boolean" || typeof value === "number") lines.push(`${key} = ${value}`);
          else lines.push(`${key} = ${quoteToml(String(value))}`);
        }
        lines.push("");
      }
      for (const [name, rule] of Object.entries((extract as Record<string, unknown>) || {})) {
        appendTomlObject(lines, `crawl.extract.${name}`, rule as Record<string, unknown>);
      }
    }
    return `${lines.join("\n").trim()}\n`;
  });

  const output = createMemo(() => (format() === "yaml" ? yamlOutput() : tomlOutput()));
  const fileName = createMemo(() => `webuse.${format() === "yaml" ? "yaml" : "toml"}`);
  const command = createMemo(() => {
    const smart = mode() === "fetch" && smartPrompt() ? ` --smart ${quoteToml(smartPrompt())}` : "";
    return `webuse ${mode()} --config ${fileName()}${smart}`;
  });
  const validation = createMemo(() => {
    const issues: string[] = [];
    if (mode() === "fetch" && !fetchUrl()) issues.push("Fetch URL is required.");
    if (mode() === "crawl" && !list(seeds()).length) issues.push("At least one crawl seed is required.");
    if (mode() === "crawl" && !Object.keys((configObject().crawl as Record<string, unknown>).extract || {}).length) {
      issues.push("At least one extraction field is recommended.");
    }
    return issues;
  });

  return (
    <main class="min-h-screen bg-slate-50 text-slate-950">
      <section class="border-b border-slate-200 bg-white">
        <div class="mx-auto flex w-full max-w-7xl flex-col gap-4 px-5 py-5 md:flex-row md:items-center md:justify-between">
          <div>
            <h1 class="text-2xl font-semibold">webuse task builder</h1>
            <p class="mt-1 text-sm text-slate-600">Generate fetch and crawl config files.</p>
          </div>
          <div class="flex flex-wrap items-center gap-2">
            <Segmented value={mode()} options={["crawl", "fetch"]} onChange={value => setMode(value as Mode)} />
            <Segmented value={format()} options={formats} onChange={value => setFormat(value as Format)} />
          </div>
        </div>
      </section>

      <section class="mx-auto grid w-full max-w-7xl gap-5 px-5 py-5 lg:grid-cols-[minmax(0,1fr)_minmax(360px,0.85fr)]">
        <div class="space-y-5">
          <Show
            when={mode() === "fetch"}
            fallback={
              <Panel title="Crawl">
                <div class="grid gap-3 md:grid-cols-2">
                  <TextArea label="Seeds" value={seeds()} onInput={setSeeds} rows={3} />
                  <TextInput label="Allowed domains" value={allowedDomains()} onInput={setAllowedDomains} />
                  <TextInput label="Max depth" value={maxDepth()} onInput={setMaxDepth} />
                  <TextInput label="Max requests" value={maxRequests()} onInput={setMaxRequests} />
                  <TextInput label="Concurrency" value={concurrency()} onInput={setConcurrency} />
                </div>
              </Panel>
            }
          >
            <Panel title="Fetch">
              <div class="grid gap-3 md:grid-cols-[1fr_140px]">
                <TextInput label="URL" value={fetchUrl()} onInput={setFetchUrl} />
                <Select label="Method" value={method()} options={methods} onInput={value => setMethod(value as Method)} />
                <TextInput label="Smart prompt" value={smartPrompt()} onInput={setSmartPrompt} />
                <TextInput label="Smart key" value={smartKey()} onInput={setSmartKey} />
                <TextInput label="Smart store" value={smartStore()} onInput={setSmartStore} />
                <label class="flex min-h-12 items-center gap-2 rounded border border-slate-300 bg-white px-3 text-sm">
                  <input type="checkbox" checked={jsonOutput()} onInput={event => setJsonOutput(event.currentTarget.checked)} />
                  JSON output
                </label>
              </div>
            </Panel>
          </Show>

          <Panel title="Request Defaults">
            <div class="grid gap-3 md:grid-cols-2">
              <TextArea label="Headers" value={defaults().headers} onInput={value => setDefault("headers", value)} rows={3} />
              <TextArea label="Params" value={defaults().params} onInput={value => setDefault("params", value)} rows={3} />
              <TextArea label="Cookies" value={defaults().cookies} onInput={value => setDefault("cookies", value)} rows={3} />
              <TextInput label="Timeout" value={defaults().timeout} onInput={value => setDefault("timeout", value)} />
              <TextInput label="Impersonate" value={defaults().impersonate} onInput={value => setDefault("impersonate", value)} />
              <TextInput label="Proxy" value={defaults().proxy} onInput={value => setDefault("proxy", value)} />
              <TextInput label="JA3" value={defaults().ja3} onInput={value => setDefault("ja3", value)} />
              <TextInput label="Akamai" value={defaults().akamai} onInput={value => setDefault("akamai", value)} />
              <label class="flex min-h-12 items-center gap-2 rounded border border-slate-300 bg-white px-3 text-sm">
                <input type="checkbox" checked={defaults().verify} onInput={event => setDefault("verify", event.currentTarget.checked)} />
                Verify TLS
              </label>
              <label class="flex min-h-12 items-center gap-2 rounded border border-slate-300 bg-white px-3 text-sm">
                <input
                  type="checkbox"
                  checked={defaults().followRedirects}
                  onInput={event => setDefault("followRedirects", event.currentTarget.checked)}
                />
                Follow redirects
              </label>
            </div>
          </Panel>

          <Show when={mode() === "crawl"}>
            <Panel title="Follow Rules" action={<button class="btn" type="button" onClick={addFollow}>Add</button>}>
              <div class="space-y-3">
                <For each={followRules()}>
                  {rule => (
                    <div class="rule-grid">
                      <Select
                        label="Type"
                        value={rule.kind}
                        options={["css", "xpath"]}
                        onInput={value => updateFollow(rule.id, { kind: value as "css" | "xpath" })}
                      />
                      <TextInput label="Selector" value={rule.selector} onInput={value => updateFollow(rule.id, { selector: value })} />
                      <TextInput label="Attr" value={rule.attr} onInput={value => updateFollow(rule.id, { attr: value })} />
                      <TextInput label="Include" value={rule.include} onInput={value => updateFollow(rule.id, { include: value })} />
                      <TextInput label="Exclude" value={rule.exclude} onInput={value => updateFollow(rule.id, { exclude: value })} />
                      <TextInput label="Max depth" value={rule.maxDepth} onInput={value => updateFollow(rule.id, { maxDepth: value })} />
                      <TextInput
                        label="Allowed domains"
                        value={rule.allowedDomains}
                        onInput={value => updateFollow(rule.id, { allowedDomains: value })}
                      />
                      <label class="flex min-h-12 items-center gap-2 rounded border border-slate-300 bg-white px-3 text-sm">
                        <input
                          type="checkbox"
                          checked={rule.sameDomain}
                          onInput={event => updateFollow(rule.id, { sameDomain: event.currentTarget.checked })}
                        />
                        Same domain
                      </label>
                      <button
                        class="btn danger"
                        type="button"
                        onClick={() => setFollowRules(current => current.filter(item => item.id !== rule.id))}
                      >
                        Remove
                      </button>
                    </div>
                  )}
                </For>
              </div>
            </Panel>

            <Panel title="Extraction Rules" action={<button class="btn" type="button" onClick={addExtract}>Add</button>}>
              <div class="space-y-3">
                <For each={extractRules()}>
                  {rule => (
                    <div class="rule-grid">
                      <TextInput label="Field" value={rule.name} onInput={value => updateExtract(rule.id, { name: value })} />
                      <Select
                        label="Type"
                        value={rule.kind}
                        options={["css", "xpath", "smart"]}
                        onInput={value => updateExtract(rule.id, { kind: value as SelectorKind })}
                      />
                      <TextInput label="Selector" value={rule.selector} onInput={value => updateExtract(rule.id, { selector: value })} />
                      <TextInput label="Attr" value={rule.attr} onInput={value => updateExtract(rule.id, { attr: value })} />
                      <label class="flex min-h-12 items-center gap-2 rounded border border-slate-300 bg-white px-3 text-sm">
                        <input type="checkbox" checked={rule.all} onInput={event => updateExtract(rule.id, { all: event.currentTarget.checked })} />
                        All matches
                      </label>
                      <button
                        class="btn danger"
                        type="button"
                        onClick={() => setExtractRules(current => current.filter(item => item.id !== rule.id))}
                      >
                        Remove
                      </button>
                    </div>
                  )}
                </For>
              </div>
            </Panel>
          </Show>
        </div>

        <aside class="space-y-5">
          <Panel title={fileName()}>
            <pre class="output">{output()}</pre>
          </Panel>
          <Panel title="Preview">
            <div class="space-y-3">
              <code class="block rounded bg-slate-950 p-3 text-sm text-slate-50">{command()}</code>
              <button class="btn primary" type="button" onClick={() => setTestVisible(value => !value)}>
                Test run
              </button>
              <Show when={testVisible()}>
                <div class="rounded border border-slate-300 bg-white p-3 text-sm">
                  <Show
                    when={validation().length === 0}
                    fallback={
                      <ul class="list-disc pl-5 text-red-700">
                        <For each={validation()}>{issue => <li>{issue}</li>}</For>
                      </ul>
                    }
                  >
                    <p class="text-emerald-700">Config is ready.</p>
                    <p class="mt-2 text-slate-600">{command()}</p>
                  </Show>
                </div>
              </Show>
            </div>
          </Panel>
        </aside>
      </section>
    </main>
  );
}

function Panel(props: { title: string; action?: unknown; children: unknown }) {
  return (
    <section class="rounded border border-slate-200 bg-slate-100 p-4">
      <div class="mb-3 flex items-center justify-between gap-3">
        <h2 class="text-base font-semibold">{props.title}</h2>
        {props.action}
      </div>
      {props.children}
    </section>
  );
}

function Segmented(props: { value: string; options: readonly string[]; onChange: (value: string) => void }) {
  return (
    <div class="inline-flex overflow-hidden rounded border border-slate-300 bg-white p-1">
      <For each={props.options}>
        {option => (
          <button
            type="button"
            class={`rounded px-3 py-1.5 text-sm capitalize ${props.value === option ? "bg-slate-900 text-white" : "text-slate-700"}`}
            onClick={() => props.onChange(option)}
          >
            {option}
          </button>
        )}
      </For>
    </div>
  );
}

function TextInput(props: { label: string; value: string; onInput: (value: string) => void }) {
  const id = createMemo(() => props.label.toLowerCase().replace(/[^a-z0-9]+/g, "-"));
  return (
    <label for={id()} class="field">
      <span>{props.label}</span>
      <input id={id()} value={props.value} onInput={event => props.onInput(event.currentTarget.value)} />
    </label>
  );
}

function TextArea(props: { label: string; value: string; rows?: number; onInput: (value: string) => void }) {
  const id = createMemo(() => props.label.toLowerCase().replace(/[^a-z0-9]+/g, "-"));
  return (
    <label for={id()} class="field">
      <span>{props.label}</span>
      <textarea id={id()} rows={props.rows || 2} value={props.value} onInput={event => props.onInput(event.currentTarget.value)} />
    </label>
  );
}

function Select(props: { label: string; value: string; options: readonly string[]; onInput: (value: string) => void }) {
  const id = createMemo(() => props.label.toLowerCase().replace(/[^a-z0-9]+/g, "-"));
  return (
    <label for={id()} class="field">
      <span>{props.label}</span>
      <select id={id()} value={props.value} onInput={event => props.onInput(event.currentTarget.value)}>
        <For each={props.options}>{option => <option value={option}>{option}</option>}</For>
      </select>
    </label>
  );
}
