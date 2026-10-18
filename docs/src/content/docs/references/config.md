---
title: "Configuration"
---

Webuse separates project defaults and spider registration from each spider's crawl,
extraction, and item-processing settings. Use YAML for new project and spider
configuration. See [Quick Start](../../user-guide/quick-start/) for a complete
project walkthrough.

## Files and discovery

| File | Scope | Loading |
| --- | --- | --- |
| `webuse.yaml` | Project defaults and registered spiders | `webuse crawl DIRECTORY`, or Python `Spider.project_dir` / `Spider.config_path`. |
| `spiders/books.yaml` | One spider's settings | A registry entry's `config`, or Python `Spider.spider_config_path`. The filename is arbitrary. |
| `.webuserc.yaml` | Local model and monitoring defaults | Nearest file from the current directory up through home or filesystem root. |
| `~/.config/webuse/config.yaml` | User model and monitoring defaults | Framework configuration loader. |

Keep one root project configuration in the specified directory; new projects use
`webuse.yaml`. Project discovery does not search parent directories. Files must contain
a mapping. Unknown top-level project and spider fields are rejected.

`webuse crawl DIRECTORY --spider NAME` runs a registered spider. Omitting
`--spider` runs all entries. Individual files are not CLI crawl targets.

## Project configuration

The schema is `ProjectConfig` in `src/webuse/spider/config.py`.

| Field | Type | Default | Purpose |
| --- | --- | --- | --- |
| `name` | String | Unset | Project name. |
| `user_agent` | String | Unset | Default agent name for robots.txt matching. |
| `robots_txt` | Boolean | Unset | Default robots.txt policy. |
| `concurrency` | Positive integer | Unset | Default maximum simultaneous page downloads per crawl. |
| `per_domain` | Positive integer | Unset | Default maximum simultaneous page downloads per hostname and port. |
| `llm` | Mapping | `{}` | Model settings scoped to each spider execution. |
| `log` | Mapping | `{}` | Logging settings applied by `webuse crawl`. |
| `spiders` | Mapping | `{}` | Registered spider names and targets; must be nonempty to crawl. |

Generated projects set `robots_txt: true` and `user_agent: chrome`. These scaffold
settings differ from the library fallback values listed under spider configuration.

```yaml
name: books-project
user_agent: chrome
robots_txt: true
llm: {}
concurrency: 5
per_domain: 1
log:
  level: info
  file: stderr
  append: true
spiders:
  books:
    path: spiders/books.py
```

This is the default generated layout: `spiders/books.py` defines the model and
custom code, and its class sets `spider_config_path = "spiders/books.yaml"`.
Seeds, scope, depth, declarative `pages` rules, request defaults, and pipeline
configuration belong in that YAML file even when parsing uses Python callbacks.
See [custom parsing](../../user-guide/quick-start/#custom-parsing-with-python-and-yaml).

### `spiders`

Each registry value can be an inline spider configuration, a string target, or
a mapping identifying a target:

| Entry | Meaning |
| --- | --- |
| `config: spiders/books.yaml` | Load a separate YAML spider configuration without a spider subclass. |
| `path: spiders/books.py` | Load a Python file containing a spider. |
| `module: spiders.books:BooksSpider` | Import a specific Python spider class. |
| Inline spider fields | Validate as `SpiderConfig`; the registry key supplies `name` if omitted. |

File paths resolve relative to the project root. Python targets may define
`Spider` or `AsyncSpider`; specify a class when a module contains multiple spiders.
Inline configurations and class-based settings remain supported, but they are
not the default layout for new projects. Use Python-only configuration when the
user explicitly prefers it; preserve existing project layouts.

### `concurrency` and `per_domain`

| Field | Type | Fallback | Purpose |
| --- | --- | --- | --- |
| `concurrency` | Positive integer | `10` | Maximum simultaneous page downloads across the crawl. |
| `per_domain` | Positive integer | No separate limit | Maximum simultaneous page downloads per hostname and port. |

Both fields are top-level project settings, using the same names as spider
settings. Spider settings and execution arguments override these defaults. Robots lookups are
separate from page-download limits. Per-host override maps are not supported.

### `log`

| Field | Type | Default | Purpose |
| --- | --- | --- | --- |
| `level` | String | `WEBUSE_LOG_LEVEL`, then `INFO` | Minimum log level. |
| `file` | String | `stderr` | `stderr`, `stdout`, or a path relative to the project root. |
| `append` | Boolean | `true` | Append to a log file; `false` truncates it. |

An empty `log` mapping leaves logging unchanged. Library callers control logging
through `configure_logger()`; running a spider does not reconfigure the logger.

### `llm`

| Field | Type | Purpose |
| --- | --- | --- |
| `model` | String | Model identifier. |
| `base_url` | String | OpenAI-compatible API base URL. |
| `api_key` | String | API credential. Prefer environment configuration for secrets. |
| `provider` | String | Provider label. |

Project `llm` values override model defaults during `Spider.run()` and
`AsyncSpider.run()`. Explicit extraction-call arguments take precedence.
Concurrent async executions have separate settings; previous defaults are restored
when an execution exits.

Outside the project override, model defaults resolve from highest to lowest:

1. Environment variables: `WEBUSE_LLM_MODEL`, `WEBUSE_LLM_BASE_URL`,
   `WEBUSE_LLM_API_KEY`, and `WEBUSE_LLM_PROVIDER`. Each falls back to its
   `OPENAI_MODEL`, `OPENAI_BASE_URL`, `OPENAI_API_KEY`, or `OPENAI_PROVIDER` equivalent.
2. The nearest `.webuserc.yaml`, under `llm`: search the current directory and
   its parents, including home, then stop. Outside home, search through the
   filesystem root. Only the nearest file is loaded; ancestor files are not merged.
3. `~/.config/webuse/config.yaml`, under `llm`.

When explicit settings are absent, the Python CLI discovers local LM Studio and
Ollama services through their OpenAI-compatible `/v1/models` endpoints.
[Harness & UI](../../user-guide/harness/) uses saved model settings from SQLite
when configured, otherwise falling back to environment and model configuration
files, then local discovery.

## Spider configuration

The schema is `SpiderConfig` in `src/webuse/spider/config.py`. These fields belong
in a separate spider file or under an inline `spiders.<name>` entry.

The fallback column describes a plain spider with no project, class, config, or
execution override. Omitted fields retain values supplied by those other sources.

| Field | Type | Fallback | Purpose |
| --- | --- | --- | --- |
| `name` | String | Unset | Spider name. |
| `start_urls` | URL string or list | Empty | Initial requests. Python may also supply `CrawlRequest` objects. |
| `goal` | String | Required for agentic executions | Task and completion criteria; requires `AgenticSpider`. |
| `limits` | Mapping | Required for agentic executions | Finite budgets validated as `AgentLimits`; requires `AgenticSpider`. |
| `pages` | Mapping | Unset | Follow and extraction rules keyed by page type. |
| `max_depth` | Integer | `0` | Maximum discovery depth; seeds have depth zero. |
| `max_requests` | Integer | No limit | Maximum page requests. |
| `concurrency` | Positive integer | `10` | Total page-download concurrency. |
| `per_domain` | Positive integer | No separate limit | Page-download concurrency per hostname and port. |
| `dedupe` | Boolean | `true` | Deduplicate normalized URLs. |
| `robots_txt` | Boolean | `false` | Check robots.txt before fetching pages. |
| `user_agent` | String | `webuse` | Agent name for robots.txt matching. |
| `allowed_domains` | String or list | Unrestricted | Allowed hostnames, including ports when applicable. |
| `request_defaults` | Mapping | Unset | Default HTTP request options. |
| `same_domain` | Boolean | `false` | Default for configured follow rules' `same_domain`. |
| `pipelines` | List | `[]` | Ordered pipeline specifications for this spider. |

### Settings precedence

Crawl settings resolve from highest to lowest:

1. Arguments to `Spider.run()` or `AsyncSpider.run()`.
2. Explicit fields in the spider configuration.
3. Spider instance or class attributes.
4. Project defaults for `concurrency`, `per_domain`, `robots_txt`, and `user_agent`.
5. Library fallback values.

Resolution produces per-execution settings without mutating the spider instance.
Pipeline precedence is separate; see [Item pipelines](#item-pipelines).

### Agentic configuration

`AgenticSpider` adds `goal` and `limits` to the spider settings. Register a Python
subclass and load its YAML through `spider_config_path`; a config-only registry
entry does not select the agentic runtime. The Pydantic `item_model` and hooks
belong in the subclass.

```yaml
name: books
goal: Collect book titles and prices.
start_urls:
  - https://books.toscrape.com/
allowed_domains:
  - books.toscrape.com
limits:
  max_tokens: 100000
```

`goal` must be nonblank. Both fields follow [settings precedence](#settings-precedence),
including arguments to `AgenticSpider.run()`. Ordinary spiders reject these fields.
See [Agentic Crawlers](../../advanced/agentic/) for a complete project example.

#### `limits`

The schema is `AgentLimits` in `src/webuse/agent.py`.

| Field | Type | Default | Purpose |
| --- | --- | --- | --- |
| `max_tokens` | Positive integer | Required | Total model token budget for the execution. |
| `max_requests` | Positive integer | Unset | Maximum crawl requests. |
| `max_turns` | Positive integer | Unset | Maximum model turns. |
| `max_seconds` | Positive number | Unset | Maximum execution duration in seconds. |
| `max_output_tokens` | Positive integer | Provider default | Output-token cap per model response. |
| `max_page_bytes` | Positive integer | Unset | Maximum downloaded response size in bytes. |
| `observation_chars` | Integer, at least 256 | `8000` | Character window for page observations. |
| `memory_chars` | Integer, at least 256 | `4000` | Maximum serialized working-memory characters sent each turn. |

Unknown fields are rejected. A supplied `limits` mapping replaces the whole
configuration rather than merging individual fields. Top-level `max_requests`
can tighten `limits.max_requests`, but cannot increase it. `memory_chars` limits
working-memory notes, not the number of retained pages.

Token usage sums the provider's reported `usage.total_tokens`; no prompt-size
estimate is reserved before requests. Omitting `max_output_tokens` or setting it
to null uses the provider's default. A response can exceed the remaining total
budget; the execution then stops before executing its tool calls or requesting another
model response.

#### Crawl settings and state

Agentic spiders require deduplication and have no default `max_depth` limit.
Static `pages` rules are omitted because the model chooses navigation and
extraction actions. The engine stops when the queue is empty and no request is
active, without a model completion decision.

`request_queue`, `request_seen`, and `request_hasher` arguments to
`AgenticSpider.run()` or `agentic_crawl()` accept the normal crawl-state
implementations. These interfaces are synchronous; remote backends can block the
agent loop. Persisting queue and seen state does not restore downloaded pages
or unfinished records.

### `request_defaults`

`user_agent` controls robots.txt matching. HTTP clients default to
`impersonate="chrome"`; use `request_defaults.impersonate` to change that profile
or `request_defaults.headers.User-Agent` to override the HTTP header.

```yaml
request_defaults:
  impersonate: chrome
  timeout: 30
  headers:
    Accept-Language: en-US
```

This mapping is passed to the curl_cffi session when the engine creates its HTTP
client. It accepts session options such as headers, cookies, authentication,
timeouts, proxies, TLS verification, and impersonation. When passing an existing
client to the engine, configure that client directly. Individual requests use
`RequestOptions` from `src/webuse/models.py` for request-specific settings.

## Page rules

### URL patterns

Each page type can declare URL inclusion and exclusion patterns alongside
its extraction and follow rules:

```yaml
pages:
  detail:
    url_patterns:
      - '/products/[0-9]+(?:\?|$)'
      - '/catalogue/'
    exclude_patterns:
      - '/catalogue/ads\.html$'
    extract:
      product:
        fields:
          title: h1
```

| Field | Type | Default | Purpose |
| --- | --- | --- | --- |
| `url_patterns` | List of regex strings | `[]` | Any matching pattern makes the page type a candidate. |
| `exclude_patterns` | List of regex strings | `[]` | Any matching pattern disqualifies this page type. |

Patterns are searched against the normalized absolute request URL (including its
query, excluding its fragment) before queueing and downloading. This applies to
seeds, followed links, and callback-generated requests:

- Without `page_type`, the first type with an inclusion match and no exclusion
  match wins. Excluded types are passed over; unmatched URLs use `default` handling.
- With `page_type`, only that type's patterns apply. If `url_patterns` is nonempty,
  at least one must match; no `exclude_patterns` entry may match. A rejected URL
  is skipped, without trying another type.

An empty `url_patterns` list allows explicit assignment but does not select a
type automatically. Types used only by Python handlers need no `pages` entry.
Redirects do not change the assigned type. Scope, depth, robots.txt, and follow-rule
filters still apply. With `dedupe: true`, request fingerprints are checked before
queueing and claimed atomically on dequeue, preventing duplicate downloads even
when several pending requests refer to the same URL.

Pattern lists must contain nonempty regex strings. `pages.*` is reserved for
fallback rules and cannot have URL patterns. Invalid patterns fail before the
crawl starts. Python uses `re.search`; the Rust prototype uses its `regex` crate,
which does not support lookaround or backreferences.

Python spiders load the same `pages` mapping from their YAML through
`spider_config_path`. Direct Python callers can also set `Spider.pages` or
`AsyncSpider.pages`.
Matching page types select `parse_<page_type>()` or `routes`, or use the page type's
declarative extraction rules. `crawl(pages=...)` and `acrawl(pages=...)` also accept
the full mapping, including extraction and follow rules. Explicit `extract=` and
`follow=` arguments take precedence over their page-configured counterparts.
Agentic spiders use goals rather than page routing.

### Page type rules

`pages.<page_type>` groups rules by the source request's page type. `default`
matches uncategorized requests, including ordinary URL seeds. A follow rule's
`page_type` labels discovered requests and selects their destination page rules.

```yaml
name: books
start_urls:
  - https://books.toscrape.com/
max_depth: 1
pages:
  default:
    follow:
      - css: .product_pod h3 a
        page_type: detail
        same_domain: true
    extract:
      books:
        item_css: .product_pod
        fields:
          title:
            css: h3 a
            attr: title
          price: .price_color
  detail:
    extract:
      book_details:
        fields:
          title: h1
          description: "#product_description + p"
```

### `pages.<page_type>.follow`

Accepts a CSS selector string, a rule mapping, or a list of either.

| Field | Type | Default | Purpose |
| --- | --- | --- | --- |
| `css` | String | Unset | Select elements containing links; mutually exclusive with `llm`. |
| `llm` | String | Unset | Select existing link elements by description using a model. |
| `all` | Boolean | `true` | Follow all matches; `false` selects the first in document order. |
| `attr` | String | `href` | Attribute containing each URL. |
| `page_type` | String | Unset | Page type assigned to discovered requests. |
| `include` | String | Unset | Regular expression URLs must match. |
| `exclude` | String | Unset | Regular expression excluding matching URLs. |
| `same_domain` | Boolean | Spider's `same_domain` | Restrict links to the source page's hostname and port. |
| `allowed_domains` | String or list | Unrestricted | Additional domain restriction for this rule. |
| `max_depth` | Integer | Unset | Additional depth limit for this rule. |

The source page type is the enclosing page key; do not specify `source_page_type`
inside a page's follow rule. Python `FollowRule` also accepts a `predicate`
callback, which cannot be expressed as a YAML function.

### `pages.<page_type>.extract`

Maps item names to extraction specifications. Supply either `fields` or
`llm_extract` with `schema`. The latter produces one record object or an array of
record objects in one model call per scope.

| Field | Type | Default | Purpose |
| --- | --- | --- | --- |
| `fields` | Mapping | Unset | Output field names and extraction rules. |
| `llm_extract` | String | Unset | Prompt for structured record extraction, instead of `fields`. |
| `schema` | JSON Schema | Required with `llm_extract` | Validate the model output before records enter pipelines. |
| `item_css` | String | Unset | Select repeated item containers; omit for one item from the whole response. |
| `item_model` | String | Unset | Import path to a Pydantic model used to validate pipeline items. |
| `type` | String | Item name | Override the extracted dictionary's `_type` label. |

Use `"*"` as an extraction page type fallback. An explicitly empty page type mapping
produces no items. An unmatched page type without a fallback produces no items in
the engine; spiders still require a handler or extraction page type for routed pages.

### Field rules

A selector string such as `title: h1` is shorthand for `title: {css: h1}`.
A mapping selects existing nodes with `css` or `llm`, or transforms content with
`llm_extract` and a `schema`:

| Operation | Value | Result |
| --- | --- | --- |
| `css` | CSS selector | First match's text or attribute; `all: true` returns a list. |
| `llm` | Element description | Model-selected node's text or attribute; `all: true` returns a list. |
| `llm_extract` | Extraction instruction | Validated value whose type and cardinality come from `schema`. |

Selection rules share the same contract as follow rules. `attr` reads an attribute
instead of text. Field selection defaults to `all: false`; follow selection
defaults to `all: true`. Both return matches in document order. No match gives
null or an empty array. `required: true` rejects absent matches or missing
attributes, but permits empty text. `css: "."` or `css: "&"` reads the current scope.

Structured extraction requires a JSON Schema and does not accept `attr`, `all`,
or `required`: express those constraints in the schema. Python configuration
also accepts Python types, such as `schema=str` or `schema=Product`.
Rules operate within the current item when `item_css` is set.

```yaml
fields:
  title: h1
  purchase_url:
    llm: primary purchase link
    attr: href
  image_url:
    css: img.product
    attr: src
  price:
    llm_extract: Current selling price as a number
    schema:
      type: number
      minimum: 0
```

Prefer one model call for a complete structured record when several fields need
interpretation:

```yaml
pages:
  default:
    extract:
      product:
        item_css: article.product
        llm_extract: Product title and current selling price
        schema:
          type: object
          required: [title, price]
          additionalProperties: false
          properties:
            title: {type: string}
            price: {type: number}
```

Malformed JSON or output that violates the schema raises `ExtractionError`;
selection and provider errors also propagate rather than producing empty records.

Unknown extraction options and malformed rules raise `ConfigError` before
downloads begin, including rules for page types that are never visited.
Plain CSS extraction does not require an LLM.

### Python extraction configuration

`crawl(extract=...)`, `acrawl(extract=...)`, and `Spider.extract` accept the
page type-to-item mapping directly, without the `pages` and `extract` wrappers:

```python
rules = {
    "default": {
        "product": {
            "item_css": "article",
            "fields": {"title": "h2", "price": {"css": ".price"}},
        },
    },
}
```

The base `Spider.parse()` uses these rules. Overriding `parse()` replaces that
behavior. Engines also accept extraction callbacks. See [Spider](../../advanced/spider/)
for Python handlers, follow-up requests, and page type routing.

## Item pipelines

`pipelines` belongs to the spider configuration. It accepts an ordered list
of pipeline specifications. Project-level `pipelines` is not supported.

```yaml
pipelines:
  - class: spiders.books.CleanPipeline
  - type: jsonl
    path: output.jsonl
```

| Specification | Purpose |
| --- | --- |
| `class: package.module.PipelineClass` | Import a custom pipeline class. |
| `type: jsonl` | Write JSON Lines to `path`. |
| `type: csv` | Write CSV to `path`. |
| `type: sqlite` | Write records to `path`, with a configurable `table`. |
| `type: assets` | Download URLs from `urls_field` to `directory`; write metadata to `output_field`. |
| `type: webhook` | Send each item as JSON to `url`; defaults to `POST`. |

Additional keys in a pipeline specification become constructor arguments.
See [Pipelines](../pipelines/) for processing behavior and custom implementations.
Pipelines process Pydantic `BaseModel` items. For dictionaries, set the named
extractor's `item_model` or Python `Spider.item_model` to validate and convert them.
Generated models and cleanup pipelines live in the spider module, such as
`spiders.books.Item` and `spiders.books.CleanPipeline`.

Pipeline chains resolve from highest to lowest, replacing the entire chain:

1. `pipelines=[...]` passed to `Spider.run()` or `AsyncSpider.run()`.
2. Python `Spider.pipelines`.
3. The spider configuration's `pipelines`.

An explicit empty list disables pipelines. Configured paths and custom class
imports resolve relative to the project root. Without a project, file-based
spider configuration uses its own directory. Python `Spider.pipelines`
specifications also use the project root when available; existing pipeline
instances keep their own paths. Run-time specifications use the current working
directory.

## Monitoring connection

Monitoring is control-plane configuration, separate from `webuse.yaml` and spider
configuration. Set the fallback connection in `.webuserc.yaml`:

```yaml
monitoring:
  prometheus_url: http://127.0.0.1:9090
```

A nonempty URL saved in **Settings → Monitoring** takes precedence, followed by
`WEBUSE_PROMETHEUS_URL`, then the configuration file. The saved override lives in
`~/.webuse/webuse.db` by default. Clear it to restore fallback discovery. Panel
visibility is saved per project in the database and is not deployment configuration.
See [Monitoring Architecture](../../advanced/monitoring/) for the exporter and
crawler instrumentation settings.
