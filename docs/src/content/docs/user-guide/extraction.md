---
title: "Selection and Extraction"
description: "How YAML extraction rules map to Python selection and extraction methods."
---

In webuse, you can use yaml to define what to extract and select links to follow.

Under the hood, the yaml config are backed by the `Response.parse()` method.


## CSS Fields and Repeated Items

This spider configuration extracts one record per book and follows the next page:

```yaml
max_depth: 2
pages:
  default:
    extract:
      books:
        item_css: article.product_pod
        fields:
          title:
            css: h3 a
            attr: title
          price: .price_color
          url:
            css: h3 a
            attr: href
    follow:
      - css: li.next a
        all: false
```

A `page_type` names a kind of page, such as a product listing or product detail,
and selects its follow and extraction rules.

`default` applies to requests without a page type. `books` names the record type;
YAML adds `_type: books` to each record. `item_css` selects the repeated book
cards, and every entry in `fields` is evaluated inside one card. Without
`item_css`, fields are read from the whole response.

`price: .price_color` is shorthand for `price: {css: .price_color}`. Fields read
text by default; `attr` reads an attribute instead. URL attributes such as `href`
and `src` become absolute automatically, using the response URL or the first
`<base href>`. This also covers `srcset`/`imagesrcset` (keeping their size and
density descriptors), URL lists such as `ping`, refresh redirects, and
Open Graph/Twitter URL metadata.

For example, reading `srcset="small.jpg 1x, large.jpg 2x"` returns both absolute
URLs with `1x` and `2x` preserved. CSS URLs (including inline styles, `<style>`
blocks, and SVG presentation attributes), custom `data-*` attributes, JavaScript,
and model-generated values are not rewritten. `response.text` keeps the original
HTML; selected elements expose the resolved values.

The corresponding Python parser is:

```python
def parse(self, response):
    for book in response.find_all(css="article.product_pod"):
        link = book.find(css="h3 a")
        price = book.find(css=".price_color")
        yield {
            "_type": "books",
            "title": link.attr("title") if link is not None else None,
            "price": price.text() if price is not None else None,
            "url": link.attr("href") if link is not None else None,
        }

    next_page = response.find(css="li.next a")
    if next_page is not None:
        url = next_page.attr("href")
        if url:
            yield response.follow(url)
```

Set `max_depth = 2` on the Python spider as well to allow follow-up requests.
Finding a link and finding a field use the same methods; yield a record for
extracted data or `response.follow(url)` for another page.

| YAML rule | Python operation |
| --- | --- |
| `item_css: article.product_pod` | `response.find_all(css="article.product_pod")` |
| `css: .price_color` | `book.find(css=".price_color")`, then `.text()` |
| `attr: href` | Read `.attr("href")` from the selected element |
| `all: true` | Use `find_all()` and read a value from each element |
| `required: true` | Reject a missing element or attribute instead of returning `None` |

Fields select one match by default; `all: true` returns a list. Follow rules
select all matches by default, so `all: false` above selects only the first next
link. Missing fields become `None` (or an empty list with `all: true`). CSS needs
no model.

## Choosing Page Rules by URL

<figure>
  <a href="../../diagrams/page-routing.png">
    <img src="../../diagrams/page-routing.png" width="1536" height="1024" loading="lazy" decoding="async" alt="An explicit page type must pass its own patterns or the request is skipped. Otherwise, use the first matching page type, or default handling if none matches." />
  </a>
  <figcaption>Explicit page types are validated; automatic routing checks types in configuration order.</figcaption>
</figure>

Put `url_patterns` inside a page type to select its rules by URL. Add
`exclude_patterns` for URLs that should not match that page type:

```yaml
pages:
  default:
    follow: h3 a
  detail:
    url_patterns:
      - '/catalogue/[^/]+_[0-9]+/index\.html$'
    exclude_patterns:
      - '/catalogue/ads'
    extract:
      book:
        fields:
          title: h1
          price: .price_color
max_depth: 1
```

Matching URLs use `pages.detail`; unmatched URLs use `pages.default`. This also
works when a detail URL is a starting URL, so follow rules do not need to assign
its page type.

In a Python spider, the same `pages` mapping selects `parse_detail()`:

```python
from webuse import Spider


class BooksSpider(Spider):
    start_urls = ["https://books.toscrape.com/"]
    max_depth = 1
    pages = {
        "detail": {
            "url_patterns": [r"/catalogue/[^/]+_[0-9]+/index\.html$"],
            "exclude_patterns": [r"/catalogue/ads"],
        },
    }

    def parse(self, response):
        for link in response.find_all(css="h3 a"):
            yield response.follow(link.attr("href"))

    def parse_detail(self, response):
        yield {"title": response.find(css="h1").text()}
```

Without an explicit `page_type`, the first type whose `url_patterns` matches and
whose `exclude_patterns` does not match wins. If none matches, the URL uses
`default` handling.

If a request or follow rule sets `page_type`, the URL must pass that type's
patterns: match an inclusion when configured, and never match an exclusion.
Otherwise it is skipped, without trying another type. An empty `url_patterns`
list allows explicit assignment.

Patterns use the full request URL without its fragment. Redirects do not change
the assigned type.

## Selecting Elements with an LLM

A field can use `llm` instead of `css` to describe the element to select:

```yaml
fields:
  price:
    llm: The current selling price
```

Inside the Python parser, that maps to `find(llm=...)` followed by `.text()`:

```python
price = book.find(llm="The current selling price")
value = price.text() if price is not None else None
```

`attr` and `all` work the same as with CSS: use `.attr(...)` to read an attribute
or `find_all(llm=...)` for several elements. Follow rules also accept `llm`, such
as `llm: The next page link`.

The model selects existing HTML; Python reads the value from that element.
Configure a [model connection](../../references/config/#llm) before using LLM
rules. Each rule uses either `css` or `llm`; CSS never falls back to a model.

## Extracting Structured Records with an LLM

When you want the model to interpret values, use `llm_extract` and `schema`
instead of `fields`. This extracts a typed record from each book card:

```yaml
pages:
  default:
    extract:
      books:
        item_css: article.product_pod
        llm_extract: Extract the book title and price as a number.
        schema:
          type: object
          required: [title, price]
          properties:
            title: {type: string}
            price: {type: number}
```

In Python, `llm_extract` maps to `.llm_extract(prompt, schema=...)`. You can use
the same JSON Schema dictionary or describe the fields with a Pydantic model:

```python
from pydantic import BaseModel


class Book(BaseModel):
    title: str
    price: float


def parse(self, response):
    for book in response.find_all(css="article.product_pod"):
        item = book.llm_extract(
            "Extract the book title and price as a number.",
            schema=Book,
        )
        yield {"_type": "books", **item.model_dump()}
```

The schema determines the result shape. For several records in one call, use an
array schema in YAML or `schema=list[Book]` in Python. Invalid output raises
`ExtractionError`; check model-generated values against the page too.

Async Python parsers await `afind()`, `afind_all()`, and `allm_extract()` for
model calls. Async YAML extraction awaits those calls automatically. See
[Async Crawling](../async/) and the [field reference](../../references/config/#field-rules)
for more options.
