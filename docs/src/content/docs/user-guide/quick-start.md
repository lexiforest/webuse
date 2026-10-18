---
title: "Quick Start"
---


## Install

If you haven't installed `webuse`, install it with:

```sh
pip install webuse
```

or

```sh
uv add webuse
```

`webuse` comes with a simple and handy CLI, called `webuse`.

The following sections assume that you have a basic understanding of how to scrape the web.
This page only talks about how to orchestrate a scraping task, i.e. the *normal flow*.
For how to avoid getting blocked, see [Frequently Asked Questions](../faq/) and
[Signing and CAPTCHAs](../../advanced/request-hooks/).

## One-liner scraping

Use `webuse fetch` when you want to fetch one page and extract a small amount
of data immediately.

For example, let's crawl all the book titles on this mock book store page. We will be
using the https://books.toscrape.com as our target in this tutorial. You can visit
the website to see what data it contains and get the general picture of it.

```bash
webuse fetch https://books.toscrape.com/ \
  --css ".product_pod h3 a" \
  --attr title \
  --all
```

<details>
<summary>Output</summary>

```json
{
  "url": "https://books.toscrape.com/",
  "matches": [
    "A Light in the Attic",
    "Tipping the Velvet",
    "Soumission",
    "Sharp Objects",
    "Sapiens: A Brief History of Humankind",
    "The Requiem Red",
    "The Dirty Little Secrets of Getting Your Dream Job",
    "The Coming Woman: A Novel Based on the Life of the Infamous Feminist, Victoria Woodhull",
    "The Boys in the Boat: Nine Americans and Their Epic Quest for Gold at the 1936 Berlin Olympics",
    "The Black Maria",
    "Starving Hearts (Triangular Trade Trilogy, #1)",
    "Shakespeare's Sonnets",
    "Set Me Free",
    "Scott Pilgrim's Precious Little Life (Scott Pilgrim #1)",
    "Rip it Up and Start Again",
    "Our Band Could Be Your Life: Scenes from the American Indie Underground, 1981-1991",
    "Olio",
    "Mesaerion: The Best Science Fiction Stories 1800-1849",
    "Libertarianism for Beginners",
    "It's Only the Himalayas"
  ],
  "selector": ".product_pod h3 a"
}
```

</details>

Use structured LLM extraction when interpreting the page requires a model.
The schema determines the output shape. For a list of titles:

```bash
webuse fetch https://books.toscrape.com/ \
  --llm-extract "All book titles from the full title attributes" \
  --schema '{"type":"array","items":{"type":"string"}}'
```

For one title, use a string schema:

```bash
webuse fetch https://books.toscrape.com/ \
  --llm-extract "First book title from its full title attribute" \
  --schema '{"type":"string"}'
```

The output is the validated JSON value directly. Use `--first` with `--css` or
`--llm` when selecting one existing element; structured extraction gets its
cardinality from the schema.

:::tip
The Python CLI automatically checks for local LM Studio and Ollama servers
when no provider is configured.

For production, you probably want to configure an api-key.
:::

This is the fastest way to test selectors or inspect a target page. Structured
fetch output is pretty-printed by default; add `--jsonl` or `--csv` when you want compact
line-oriented output for a shell pipeline.

## One-file scraping

The same idea works in Python:

```python
import webuse

response = webuse.get("https://books.toscrape.com/")

for link in response.find_all(css="article.product_pod h3 a"):
    print(link.attr("title"))
```

`Response` builds its parsed document lazily, so a plain HTTP request does
not pay the HTML parsing cost until you call `find()`, `find_all()`, or another
document helper.

To extract the titles with an LLM, describe the values you want:

```python
import webuse

response = webuse.get("https://books.toscrape.com/")
titles = response.llm_extract(
    "All book titles, using the full title attributes instead of shortened link text",
    schema=list[str],
    max_chars=None,
)

for title in titles:
    print(title)
```

`schema=list[str]` requests and validates a list of strings. `llm_extract()` requires model access. Python
automatically discovers local LM Studio or Ollama when no provider is configured;
see [Selection and Extraction](../extraction/) for provider settings. For this small
page, `max_chars=None` sends the full document instead of truncating the model input.


## Create a project

In the above examples, we extracted some information from a single page.
When you want something more serious, it's perfect time to create a project.
A webuse project is a directory with a root `webuse.yaml`. Start with:

```bash
webuse create books_project
cd books_project
webuse gen books https://books.toscrape.com/
```

`webuse create` writes `webuse.yaml`, a README, and directories for spiders and local runtime state.

```
.
├── __init__.py
├── README.md
├── spiders
│   ├── __init__.py
│   ├── books.py
│   └── books.yaml
└── webuse.yaml
```

The `webuse.yaml` contains project configurations:

```yaml
name: books_project
user_agent: chrome  # Agent name used for robots.txt matching
robots_txt: true    # Obey the robots.txt rule
llm: {}             # LLM to use
concurrency: 5
per_domain: 1
log:                # Logging to stderr by default
  level: info
  file: stderr
  append: true
spiders:            # Registered spiders in this project
  books:
    path: spiders/books.py
```

`webuse gen` adds `spiders/books.yaml` and `spiders/books.py`, and registers the spider
in project config file.

The Python module defines the item model, pipeline implementations, and spider
class. Add custom parsing methods or hooks here when needed; keep the YAML
configuration connected through `spider_config_path`:

```py
import webuse
from pydantic import BaseModel


class Item(BaseModel):
    title: str


# This is a no-op, just to demostrate that you can clean the item here.
class CleanPipeline(webuse.ItemPipeline):
    def process_item(self, item: Item):
        return item


class BooksSpider(webuse.Spider):
    spider_config_path = "spiders/books.yaml"
    item_model = Item
```

The `books.yaml` contains the configuration for the spider:

```yaml
name: books
start_urls:
  - https://books.toscrape.com/
allowed_domains:
  - books.toscrape.com
max_depth: 1
pages:
  default:                   # How to process the page, the default route
    follow:                  # Which link to follow
      - css: a
        same_domain: true
    extract:                 # What items to extract
      books:                 # Name of the extracted items
        fields:              # Fields in the extracted item
          title: title
pipelines:                 # Pipelines to process the items from the spider
- class: spiders.books.CleanPipeline  # Use a custome processing pipeline
- type: jsonl            # Use the builtin jsonl pipeline to save the item
  path: output.jsonl     # The output filename
```

You can now run the spider with:


```bash
webuse crawl --spider books -o books.jsonl
```

`-o` selects JSONL, CSV, or SQLite output by file extension. The generated
spider also has its own pipeline writing `output.jsonl` inside the project.
Edit `pipelines` in `spiders/books.yaml` to change that destination.


### Define extraction in YAML

To extract book-specific fields, first extend the generated `Item` model in
`spiders/books.py`:

```python
class Item(BaseModel):
    title: str
    price: str = ""
    availability: str = ""
```

Then edit `spiders/books.yaml` to define the extraction and follow rules.

For example, replace `pages` with the rules below and set `max_depth: 2`.
The `default` page type handles book listings, while `detail` handles individual
book pages:

```yaml
max_depth: 2                         # Increase the max_depth to allow more pages
pages:
  default:
    follow:                          # Next pages to follow
      - css: .next a
        page_type: default            # The page type for the new page
        same_domain: true
      - css: .product_pod h3 a
        page_type: detail
        same_domain: true
    extract:                         # What fields to extract on the page
      books:
        item_css: .product_pod
        fields:
          title:
            css: h3 a
            attr: title
          price: .price_color
  detail:                            # Define a page type called "detail"
    extract:                         # What fields to extract on the page
      book_details:
        fields:
          title: .product_main h1
          price: .product_main .price_color
          availability: .product_main .availability
```

`default` is the catch-all page type. Pagination links stay in `default`, so the
next listing uses the same selectors and follow rules. Book links get `page_type: detail`,
so their responses use `pages.detail.extract` instead. No Python route method is
needed for these declarative page types.

On listings, `item_css` selects each book container and field selectors run inside
it. On detail pages, omitting `item_css` extracts one record from the whole page.
This example emits both listing records and detail records; they are separate
items, not merged. The detail fields fit the extended `Item` model.

`max_depth: 2` allows two link hops from a start URL, including a detail page
reached through the next listing page. Increase it to follow more pagination.

Run the spider, again:

```bash
webuse crawl --spider books -o books.jsonl
```

For a small sample, add `--max-requests 3`. Omitting `--spider` runs all
registered spiders with a shared request budget.

### Custom parsing with Python and YAML

Custom parsing uses the same two-file layout. Generate another spider from the
project directory:

```bash
webuse gen book_details https://books.toscrape.com/
```

Put seeds, scope, depth, follow rules, and pipeline settings in
`spiders/book_details.yaml`:

```yaml
name: book_details
start_urls:
  - https://books.toscrape.com/
allowed_domains:
  - books.toscrape.com
max_depth: 49
pages:
  default:
    follow:
      - css: .next a
        same_domain: true
pipelines:
  - class: spiders.book_details.CleanBookPipeline
  - type: jsonl
    path: output.jsonl
```

Replace `spiders/book_details.py` with the model and custom parser:

```python
import webuse
from pydantic import BaseModel


class BookItem(BaseModel):
    title: str
    price: str = ""


class CleanBookPipeline(webuse.ItemPipeline):
    def process_item(self, item: BookItem):
        return item


class BookDetailsSpider(webuse.Spider):
    spider_config_path = "spiders/book_details.yaml"
    item_model = BookItem

    def parse(self, response):
        for book in response.find_all(css=".product_pod"):
            yield {
                "title": book.find(css="h3 a").attr("title"),
                "price": book.find(css=".price_color").text(),
            }
```

The custom `parse()` replaces the default extractor, so this YAML omits the
starter `pages.default.extract` rules. YAML follow rules still discover the next
page. For multiple page types, keep routing and follow rules in YAML and implement
`parse_<page_type>()` methods in Python where needed. Custom parsing, JSON-LD
fallbacks, hooks, and async methods do not require moving settings into Python.

The same project command runs it:

```bash
webuse crawl --spider book_details -o books.jsonl
```

The base `Spider.parse()` extracts items from `extract` when you do not need
custom logic. Override `parse()` for conditions, normalization, and additional
requests. Generated spiders have no separate script entry point.

Direct Python calls to `crawl()`, `acrawl()`, and `Spider.run()` are also
available without creating a project.

### Pure Python spider

If you explicitly prefer all configuration in Python,
`webuse gen NAME URL --python-only` generates that alternative. It still requires an existing project
and registers the class in `webuse.yaml`. Use this option by preference, not as a
requirement for custom parsing. New projects use the YAML/Python split by default;
preserve an existing project's organization unless you intend to change it.

### Routing Follow-Up Requests

Webuse automatically calls `parse_<page_type>()` for each response with an assigned
page type, unless an explicit entry in `routes` overrides it.

There are two ways to send a discovered URL to a parser:

- **Assign `page_type` explicitly:** use `response.follow(url, page_type="author")`
  in Python, or `page_type: author` on a YAML follow rule.
- **Let URL patterns choose (recommended):** follow the URL without a type and
  declare `url_patterns` under `pages.author`.

For example, generate a spider from the current project:

```bash
webuse gen quotes https://quotes.toscrape.com/
```

Replace `spiders/quotes.yaml` with rules that find author links and let their
URLs select `parse_author()`:

```yaml
name: quotes
start_urls:
  - https://quotes.toscrape.com/
allowed_domains:
  - quotes.toscrape.com
max_depth: 1
pages:
  default:
    follow:
      - css: .author + a
        same_domain: true
        exclude: /author/unknown/?$
  author:
    url_patterns:
      - /author/[^/]+/?$
    exclude_patterns:
      - /author/unknown/?$
pipelines:
  - type: jsonl
    path: authors.jsonl
```

Then replace `spiders/quotes.py` with the custom handler:

```python
import webuse
from pydantic import BaseModel


class Author(BaseModel):
    name: str


class QuotesSpider(webuse.Spider):
    spider_config_path = "spiders/quotes.yaml"
    item_model = Author

    def parse(self, response):
        # YAML follow rules handle the listing page.
        return ()

    def parse_author(self, response):
        title = response.find(css="h3.author-title")
        if title is not None:
            yield Author(name=title.text().strip())
```

If no custom parsing is needed, the `pages` section can also extract the author
declaratively. Use this with a configuration-only registration
(`config: spiders/quotes.yaml`) instead of the Python class above:

```yaml
pages:
  default:
    follow:
      - css: .author + a
        exclude: /author/unknown/?$
  author:
    url_patterns:
      - /author/[^/]+/?$
    exclude_patterns:
      - /author/unknown/?$
    extract:
      authors:
        fields:
          name: h3.author-title
```

To assign the type explicitly, add `page_type: author` to that follow rule, or
pass `page_type="author"` to `response.follow()`. The URL must still pass the
author type's patterns; otherwise it is skipped without trying another type.
With no `url_patterns`, explicit assignment is allowed, subject to exclusions.
For untyped links, `exclude_patterns` only prevents assignment to that page type;
an unmatched URL can still use default handling. Use a follow rule's `exclude`
to prevent discovering those links, as the examples do for unknown authors.

Automatic matching checks types in declaration order and chooses the first match
without an exclusion. If none matches, the URL uses `default` handling. The spider
dispatches to `parse_<page_type>()` or an entry in `routes`; YAML spiders use the
matching extraction rules. Already-seen requests are checked before queueing and
again before downloading.

## Going async

For those who prefer performance and async API, we fully support asyncio.
Generate an async spider with `--async`:

```bash
webuse gen async_books https://books.toscrape.com/ --async
webuse crawl --spider async_books
```

The generated class inherits from `AsyncSpider`, and `webuse crawl` awaits it automatically.

See [Async Crawling](../async/) for the corresponding sync and async APIs.

## Vibe coding

If you don't want to write code by hand, you can either use our built-in harness or
ask your Codex or Claude to write it for you.

For Codex/Claude, simply say:

```text
Install the skills from: https://github.com/lexiforest/webuse
```

For the built-in coding assistant, see [Harness](../harness/). To manage executions,
logs, records, and schedules, see [Dashboard](../dashboard/).
