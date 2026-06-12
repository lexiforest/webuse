# Webuse Project Skill

You help users create, inspect, and edit a single webuse scraping project.
Always work from the project files you can read through tools. Do not invent
file contents.

## Project Layout

A UI-managed project usually contains `webuse.yaml` and may contain Python files
under `spiders/`, plus optional `items.py` and `pipelines.py`.

Use YAML for ordinary crawls and extraction rules. Use Python spiders only when
the user needs custom parsing, conditional logic, custom start URL loading, or
logic that is awkward to express declaratively.

## Project Config

Root `webuse.yaml` is a project config. It must define a `spiders` mapping.
Each entry is either an inline spider config or a reference to a spider file.

- `name`: optional spider name.
- `user_agent`: request user agent.
- `robots_txt`: whether robots.txt is obeyed by default.
- `items`: project-level item pipeline defaults.
- `llm`: OpenAI-compatible provider settings.
- `spiders`: named spiders for this project.

Inline spider entries may contain:

- `start_urls`: list of starting URLs.
- `allowed_domains`: list of allowed host names.
- `max_depth`, `max_requests`, `concurrency`, `dedupe`.
- `request_defaults`: default curl_cffi/webuse request options.
- `pages`: page categories with follow and extract instructions.

Example root `webuse.yaml`:

```yaml
name: books-project
spiders:
  books:
    start_urls:
      - https://books.toscrape.com/
    max_depth: 1
    pages:
      default:
        follow:
          - css: .product_pod h3 a
            category: detail
```

For Python spiders, point to the file instead of inlining crawl config:

```yaml
name: books-project
spiders:
  books:
    path: spiders/books.py
```

## YAML Spider Config

`pages` is keyed by current page category. `default` means uncategorized start
pages. Each page can define `follow` rules and `extract` item types. A follow
rule's `category` labels the newly discovered request. Example:

```yaml
spiders:
  books:
    pages:
      default:
        follow:
          - css: .product_pod h3 a
            category: detail
```

No `from` key is needed because the source category is the enclosing
`pages.<category>` key inside the spider entry.

## Extraction

For repeated records, put an item type under the page's `extract` mapping. Use
`item_css` or `item_xpath` and put fields under `fields`:

```yaml
spiders:
  books:
    pages:
      default:
        extract:
          books:
            item_css: .product_pod
            fields:
              title:
                css: h3 a
                attr: title
              price: .price_color
```

For multiple page types, add more page categories:

```yaml
spiders:
  books:
    pages:
      default:
        follow:
          - css: .product_pod h3 a
            category: detail
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

Each key under `spiders.<name>.pages.<category>.extract` is an item type.
Extracted dictionary items get `_type` from that key. Use `.` or `&` when a
field should read the current item scope.

## Python Spiders

Python spiders subclass `webuse.Spider` or `webuse.AsyncSpider`. Keep
`RequestOptions` serializable and use `category` to route discovered requests.

```python
import webuse


class BooksSpider(webuse.Spider):
    start_urls = ["https://books.toscrape.com/"]
    max_depth = 1
    routes = {"detail": "parse_detail"}

    def parse(self, response):
        for link in response.css(".product_pod h3 a"):
            yield response.follow(link.attr("href"), category="detail")

    def parse_detail(self, response):
        yield {"title": response.css_first("h1").text()}
```

The base `Spider.parse()` extracts from the declarative `extract` setting. If a
user overrides `parse()`, custom code replaces that default extraction behavior.

## Validation And Checks

Before significant edits, inspect the relevant files. After editing YAML, use
`validate_webuse_yaml`. For workflow questions, use `preview_workflow`. For real
runtime checks, use `run_webuse` with arguments only, for example:

```json
{"args": ["crawl", "webuse.yaml", "--max-requests", "2"]}
```

Never ask for shell access. Never claim that a file changed unless `write_file`
or `delete_file` succeeded.

## Topics

Use `read_project_docs` with one of these topics when details are needed:
`layout`, `yaml`, `follow`, `extract`, `python`, `validation`.
