---
title: Agentic Spiders
description: Let a model choose navigation and extraction actions during a crawl.
---

:::caution[Warning]
**This is highly experimental.**
:::

Ordinary crawlers can explicitly select elements with `find(llm=...)` or
transform content with `llm_extract(prompt, schema=...)`. An agentic crawler
goes further: its model chooses follow-up requests and assembles records while
the crawl runs. Its CSS extraction tool reads values without a nested model call.

`AgenticSpider` runs a request queue with LLM-driven processing in Python. Declare
the goal, starting URLs, output schema, and total token budget. The model chooses
which links to queue and how to extract data. The engine stops when the queue is
empty and no request is still being processed.

It can choose a relevant category, inspect catalog listings, and visit product pages
for missing fields. The steps depend on what it finds on each page.

## Define and run a spider

[web-scraping.dev](https://web-scraping.dev/) is a target site for testing spiders.

Let's build a spider that crawls the apparel catalog and collects **every product
priced below $30**. For each matching product, we'll collect its name, current
price, brand, material, and detail-page URL. The crawl is complete when all apparel
listing pages and their products have been examined.

Open the [product catalog](https://web-scraping.dev/products) and look around first.
You'll find category links and several pages of products. Open a
[product page](https://web-scraping.dev/product/24), and you'll also find a price
and a Features table. For this simple task, all the information we need is available
in the HTML.

## Create the project

Start by creating a project and generating a spider:

```bash
webuse create catalog_project
cd catalog_project
webuse gen apparel https://web-scraping.dev/products --async
```

The generator creates `spiders/apparel.yaml` for configuration and `spiders/apparel.py`
for the Python class, then registers the spider in `webuse.yaml`.

## Set the goal and crawl scope

Open `spiders/apparel.yaml` and update it:

```yaml
name: apparel
goal: >-
  Collect every apparel product currently priced below USD 30, with its name,
  current price, brand and material from the Features table, and base product URL.
start_urls:
  - https://web-scraping.dev/products?category=apparel
allowed_domains:
  - web-scraping.dev
robots_txt: true
limits:
  max_tokens: 500000
```

The `goal` guides navigation and extraction without declarative extraction rules.
`limits.max_tokens` sets the total model token budget; reaching it can leave a
partial crawl. Requests, turns, duration, and depth have no default limits.
We'll write records with the crawl command's `-o` option.

## Define the records and download hook

Open `spiders/apparel.py` and use the following code:

```python
import asyncio

from pydantic import BaseModel, Field, HttpUrl
from webuse import AgenticSpider, SignalBus


class Product(BaseModel):
    name: str
    price_usd: float = Field(gt=0, lt=30)
    brand: str
    material: str
    url: HttpUrl


async def pace_download():
    await asyncio.sleep(2)


class ApparelSpider(AgenticSpider):
    spider_config_path = "spiders/apparel.yaml"
    item_model = Product
    signals = SignalBus()
    signals.connect("request_before_downloader", pace_download)
```

`AgenticSpider` is async; `spider_config_path` connects it to the YAML settings.
`Product` requires every field, a valid URL, and a price between zero and $30.
The spider validates records before emitting them and can keep drafts while
looking for missing fields on other pages.

The `pace_download` hook waits two seconds before each download.

## Configure the model

Before running the spider, configure a model that supports OpenAI-compatible
tool calls. For example, if you're using DeepSeek, add this
section to `webuse.yaml`:

```yaml
llm:
  base_url: https://api.deepseek.com
  model: deepseek-flash
```

Supply the API key through the `WEBUSE_LLM_API_KEY` environment variable, keeping
credentials out of project files.

For local models, omit explicit provider settings to let Webuse discover
Ollama or LM Studio. Explicit settings take precedence.

## Run your first crawl

From the project directory, run:

```bash
webuse crawl --spider apparel -o apparel.jsonl
```

The CLI loads `ApparelSpider`, starts its model loop, and writes emitted records
to `apparel.jsonl` immediately, flushing each line while the crawl is running.
An emitted record remains in the file if the crawl later hits a limit or fails.

The model is asked to include a short progress sentence with each turn. These
appear at INFO level alongside the action logs, for example:

```text
agent progress turn=8 Saved two matching products; next I'll check the remaining products on this page.
```

Each summary describes previous results and the next planned action. It uses
the model's ordinary response text, without another model request. Detailed
action logs still show whether those actions succeeded.

Watch the action logs while it runs. A possible sequence is:

1. Pop the apparel catalog request and inspect its links.
2. Queue relevant product and pagination links.
3. Pop the next request and check its current price, brand, and material.
4. Emit a validated record if the product matches the price filter, or exclude it
   if its current price is $30 or more.
5. Continue through the category's remaining listing pages and unique products.
6. Stop automatically when all queued requests have been processed.

The log names are runtime tools: `queue_push` adds links, `queue_pop` advances to
the next page, and `emit_record` submits a validated record. The model also keeps
working notes during the execution. See [Agentic Runtime](../../references/agentic/)
for the tool contract and memory behavior.

## Check the data

Open `apparel.jsonl`. Each line should be a separate JSON record. For example, a record
for the [Cat-Ear Beanie](https://web-scraping.dev/product/24) could look like this:

```json
{"name":"Cat-Ear Beanie","price_usd":14.99,"brand":"CatCozies","material":"High-quality, soft, and durable acrylic","url":"https://web-scraping.dev/product/24"}
```

A complete crawl of unchanged data should cover the same matching
product URLs. Review the action logs and follow the output URLs to check that:

- Every apparel listing page and product has been examined.
- Each price matches the displayed current price and is below $30.
- The brand and material match the product's Features table.

The schema validates record shape, not site coverage or the model's interpretation.
Even a `finished` execution can miss products if the model skipped a pagination link.
Check coverage against the site; the sample values above may change.

## If the crawl stops early

Check the final reason and preceding action logs:

| Reason | Next step |
| --- | --- |
| `incomplete` | Inspect download errors and unfinished drafts. |
| `model_error` | Check the endpoint, model identifier, and tool-call support. |
| `token_limit` | Review the model's progress before increasing `limits.max_tokens`. |

These executions return a nonzero CLI exit status, but emitted records remain in the
output file. Drafts are not written as complete items. Use a new output filename
when rerunning to preserve partial results. Restarting starts a new execution; durable
resume is not implemented.

See [Agentic Runtime](../../references/agentic/#limits-and-outcomes) for token
accounting and the [configuration reference](../../references/config/#agentic-configuration)
for optional request, turn, time, depth, and per-response limits.

## Try a different goal

Once the first crawl works, try collecting **every apparel product below $50**.
Change `Product.price_usd` in `spiders/apparel.py` to `Field(gt=0, lt=50)`, then
update the goal's price threshold in `spiders/apparel.yaml`.
Run it again with a new output file:

```bash
webuse crawl --spider apparel -o apparel-under-50.jsonl
```

Compare the records and action logs with the first execution. The higher threshold
should admit additional products if the catalog contains them.
