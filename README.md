# Webuse

`webuse` is a combination of 3 layers:

- A Python crawler framework.
- A harness for writing crawlers on top of the framework.
- A orchestrator and UI for running the crawlers.

For hosted version with integrated proxies and browser rendering, visit
[impersonate.pro/webuse](https://impersonate.pro/webuse).

## Why

`curl_cffi` can be a good starting point for writing a crawler or scraper, it's fairly
easy to use AI to generate a decent script. But keeping it running means
handling blocked requests, sessions, dynamic pages, broken extraction, and changes
to the target site.

If you're writing a lot crawlers, soon you or your assistant will create a home-made
framework across different projects for these common tasks.

`webuse` is here to be the framework you has been or will be building, along with
a harness on how to write crawlers on top of the framework, and finally
the process manager and metrics dashboard.

Besides, you can also bring your existing scripts to the orchestrator, and it can
also manage the process for you.


## Agentic crawlers


Except for the traditional crawlers we have been writing, webuse also comes with a
special kind of crawler whose execution schedule is dynamically controlled by an LLM.
Generating crawler code with AI does not by itself make the crawler agentic: this
mode uses the model during operation to decide when the crawler should run.

The benefits of agentic crawlers is more reliablity against site changes.


## Install

Requires Python 3.11 or newer. Add the Python package to your project:

```bash
pip install webuse
```

## Usage

```
webuse ui
```

Released packages include the compiled UI. `webuse ui` opens
`http://127.0.0.1:2951/` and runs until you press Ctrl+C. It requires Node.js 24+
on PATH, but no npm install or frontend build. Python-only crawling does not
require Node. Data is saved in `~/.webuse/ui`; use `--data-dir` to change it,
`--port` to change the port, or `--no-open` to skip opening the browser.

Open the URL printed by Vite, by default `http://127.0.0.1:2951/`. Configure the model
endpoint, model, and credentials in Settings before using Chat. Python provider
helpers already discover LM Studio and Ollama when no provider is configured;
automatic discovery in UI Chat is still planned. The control plane discovers the
repository's `.venv/bin/python` automatically during source development.
The packaged launcher uses the Python interpreter running `webuse ui` for crawlers.

### Building with AI

These are three views of the same crawler project:

- **Chat** expresses intent and helps create, edit, and debug the crawler.
- **Code** holds the implementation and configuration that users can inspect.
- **Dashboard** makes execution status, logs, and extracted records visible.

Chat is powered by [Pi](https://pi.dev/), with Webuse tools and a bundled crawler
skill. It can inspect pages, read and edit project drafts, execute Python checks,
run small crawls, and inspect their logs and records. Responses and tool activity
stream into Chat; Stop cancels the current turn. Review the resulting files and
Save to update the project. Sample crawls use drafts without changing its saved
version or schedule. Python tools execute on your computer as the UI user.

Configure a streaming, tool-capable OpenAI-compatible model in Settings. Pi
conversation context persists locally; no Pi account or separate Pi installation
is required. Automatic UI model discovery and cloud isolation remain planned.

The product direction is to keep this experience consistent locally and in cloud.
The local UI will offer Run locally and Deploy to cloud. Local projects can run
on the user's machine and later be deployed. Projects
created on the hosted website run in cloud workspaces. Cloud deployment is not
implemented in the current CLI.

Local success does not guarantee cloud success: dependencies, proxy identity,
geography, cookies, and network access can differ. Deployment should validate
these differences and provide failure evidence. LLM monitoring should use that
evidence to advise users, without silently deploying repairs.

### Building from scratch

#### Fetch and extract

```python
import webuse

with webuse.Client(impersonate="chrome", timeout=20) as client:
    response = client.get("https://example.com")
    title = response.css_first("title")
    print(title.text() if title is not None else None)

    for link in response.css("a"):
        print(link.attr("href"), link.text())
```

Use `AsyncClient` and `await client.get(...)` for async requests. XPath and regex
selectors are also available. Plain selectors work without an LLM.

Clients inherit curl_cffi sessions and accept its native HTTP arguments, such as
`allow_redirects`. Responses retain native headers, cookies, streaming, and
`raise_for_status()`, with Webuse's parsing methods added. Use
`async with client.stream("GET", url)` for async streaming.

The CLI supports the same basic workflow:

```bash
uv run webuse fetch https://example.com --css "title"
uv run webuse fetch https://example.com --xpath "//a" --jsonl
```

See [smart selectors](docs/smart-selectors.rst) for model-backed extraction and
selector caching. The default selector cache is `.webuse/selectors.json`; keep
generated state out of version control.

#### Crawl with Python or configuration

```python
import webuse

result = webuse.crawl(
    ["https://example.com"],
    follow=webuse.FollowRule(css="a", same_domain=True),
    extract={"title": "h1"},
    max_depth=1,
    concurrency=5,
    per_domain=1,
)

print(result.items)
print(result.stats)
```

Use `await webuse.acrawl(...)` for async crawling. Larger projects can use
`webuse.Spider` or `webuse.AsyncSpider`, with custom parsing, request categories,
Pydantic item models, and pipelines.

Both engines record download failures in `result.errors` and propagate parsing
or pipeline exceptions. Project concurrency defaults and per-domain limits apply
to both engines; see [configuration](docs/config.rst) for precedence and logging.

Use YAML for Webuse configuration: `webuse.yaml` for project settings and named
spiders, or standalone files such as `books.yaml` for a declarative crawler:

```yaml
name: books
start_urls:
  - https://books.toscrape.com/
allowed_domains:
  - books.toscrape.com
max_depth: 1
pages:
  default:
    follow:
      - css: .next a
    extract:
      books:
        item_css: .product_pod
        fields:
          title:
            css: h3 a
            attr: title
          price: .price_color
```

Run it and write the extracted records to JSONL:

```bash
uv run webuse crawl books.yaml -o books.jsonl
```

The CLI also runs project spiders:

```bash
uv run webuse crawl books_project --spider books -o books.jsonl
```

See the [quick start](docs/quick-start.rst), [CLI guide](docs/cli.rst), and
[configuration guide](docs/config.rst) for more examples.

## Cloud version

Webuse Cloud will focus on the work around a production crawler:

| Service | Intended benefit |
| --- | --- |
| Isolated agent environments and background runs | Use a provided Docker image for the agent workspace, then execute saved crawlers independently of a laptop or chat session |
| Managed proxies | Connect crawlers to geographic routing, rotation, and sticky sessions without managing provider setup |
| Hosted browsers | Run JavaScript interactions through a browser endpoint compatible with existing automation code |
| CAPTCHA integration | Handle supported challenges through a separate solver provider with controlled spending |
| Defuddle-based extraction API | Convert HTML pages into Markdown for downstream consumption |
| Integrated LLM API | Provide model access for agentic crawler scheduling and analysis |
| Monitoring and streaming logs | Follow crawler progress and inspect failures while runs execute |
| Diagnosis and data sanity checks | Use logs and failed responses to distinguish request failures, blocks, and broken extraction |

A simple metrics emitter, StatsD-like wire format, and time-series database will
feed the dashboard and monitoring advice. Existing counters and polled logs are
the starting point, not the complete monitoring service.

The cloud agent will have Webuse skills preloaded to explain these APIs and
workflows. Live capability discovery will describe the services and allowances
actually available in its workspace. Runtime configuration will supply endpoints
and credentials separately from prompts and generated code. MCP is an optional
integration proposal; its inclusion, tool contract, and delivery scope remain open.

The framework will remain optional for cloud deployment. Existing code should be
able to use standard service endpoints; richer record-level monitoring may need a
small adapter. SSH access is also proposed for users connecting their own tools.

The planned Pro and Free environments both have 1 vCPU and 2 GiB RAM. Pro is a
monthly plan; Free includes four hours of runtime. Pro runtime hours, Free renewal
timing, concurrency, and paid-service allowances remain unspecified. These are
planning targets, not an available cloud subscription from this checkout.

Providers, API contracts, remaining allowances, and launch sequencing are still
being designed. Browser rendering and CAPTCHA solving are separate capabilities, and
coverage will depend on the target site and provider. These are roadmap items,
not services available from this checkout.

## Development

To develop from this repository, use a Python 3.11+ development
environment and Node.js 24 or newer:

```bash
uv sync --extra dev
cd ui
npm ci
npm run dev
```

The build installs locked npm dependencies, compiles the UI, and bundles it into both the
source distribution and wheel. See [release packaging](docs/deploy.rst).

The local UI currently launches Python crawler subprocesses. It is a local
development control plane, not the planned isolated multi-tenant cloud runtime.
See [ui/README.md](ui/README.md) for runtime configuration and deployment commands.

Python checks:

```bash
uv sync --extra dev
uv run python3 -m compileall src tests
uv run pytest -q
```

UI checks, from `ui/`:

```bash
npm run typecheck
npm test
npm run build
```


## Documentation and development

- [Documentation index](docs/index.rst)
- [Local UI setup](ui/README.md)
- [Examples](examples/)

## License

The project is released under the MIT license.
