---
title: "Agentic Runtime"
description: "Tools, working memory, and execution limits for agentic crawls."
---

:::caution[Warning]
**This is highly experimental.**
:::

`AgenticSpider` and `agentic_crawl()` let a model choose navigation and extraction
actions during a crawl. These tools run inside the Python process. Start with the
[agentic spider tutorial](../../advanced/agentic/) for project setup and a complete
example; see [Configuration Reference](../config/#agentic-configuration) for settings.

## Navigation and Records

<figure>
  <a href="../../diagrams/agentic-runtime.png">
    <img src="../../diagrams/agentic-runtime.png" width="1536" height="1024" loading="lazy" decoding="async" alt="The engine sends page state to the model, which chooses Python tools. Tools update the queue and drafts or emit records for saving during the loop. The engine finishes when the queue is empty and no request is active." />
  </a>
  <figcaption>Tools are model-selected actions; configured output saves emitted records during the crawl.</figcaption>
</figure>

| Tool | Behavior |
| --- | --- |
| `queue_push` | Add an observed link to the request queue, subject to crawl policy. |
| `queue_pop` | Release the current request and download the next unseen request. |
| `seen_exist` | Check whether a URL has been handled or excluded. |
| `seen_add` | Mark a URL as excluded without downloading it. |
| `inspect` | Read page content, links, or discovered URLs. |
| `extract` | Read values with CSS selectors without a nested model call. |
| `update_record` | Save fields in a draft record, including across pages. |
| `emit_record` | Validate a complete record and send it through item pipelines. |
| `update_memory` | Update working notes for subsequent turns. |

Queue follow-up links and save records before calling `queue_pop`. Popped requests
are marked seen automatically; marking a URL seen before queueing it prevents its
download. Request identity, deduplication, scope, and depth use the existing
queue, seen set, and request hasher.

Inspecting or extracting content does not emit a record; the model must call
`emit_record`. The final log's `records` count reports records that passed the
pipelines; `drafts` counts unfinished records.

The engine stops when the queue is empty and no request is active. An empty
waiting queue alone does not end processing of the current page. There is no
`finish` tool or model decision about whether the crawl is complete.

## Working Memory

Each turn receives the goal, output schema, queue/seen counts, current request,
recent page IDs, record counts, progress summary, and working notes. The notes
have three fields: `findings`, `completed`, and `next_steps`. `update_memory`
changes only the supplied fields, preserving the others after earlier tool
responses leave the recent conversation.

For a large catalog, the model can record "pages 1-120 checked; continue at page
121" and unresolved products. Discovered URLs are stored separately.
`inspect(view="urls", offset=...)` returns up to 20 entries with fetched page IDs;
a null ID means the URL has not been fetched. Older pages remain accessible by ID.

Working memory defaults to 4,000 serialized characters, controlled by
`limits.memory_chars`. Oversized updates are rejected without replacing existing
notes. Normal prompts include only the latest five page references and 20 draft
IDs, rather than the full history.

Notes are available in Python as `result.agent.memory`. Memory, pages, and records
last only for the current process; durable resume is not implemented. Notes help
navigation but do not prove site coverage.

## Limits and Outcomes

| Reason | Meaning |
| --- | --- |
| `finished` | The queue drained and the last request finished processing. |
| `incomplete` | The queue drained with request errors or unfinished drafts. |
| `model_error` | The provider failed or returned an invalid response. |
| `token_limit` | The total model token budget was exhausted. |

`finished` reports queue exhaustion, not proof that every relevant page was
discovered. Inspect page evidence and output coverage when validating a crawl.

`limits.max_tokens` counts the provider's reported `usage.total_tokens` after
each response. Webuse does not reserve tokens using prompt-size estimates. A
response can exceed the remaining budget; the runtime then stops before executing
that response's tools or making another model call. This is not an exact dollar
budget because provider prices vary by token type.

There is no per-response output cap unless `limits.max_output_tokens` is set.
When set, the requested cap is the smaller of that value and the remaining total
token budget. Optional request, turn, duration, and depth limits are described in
the [configuration reference](../config/#agentic-configuration).

Incomplete executions return a nonzero CLI exit status. Records already emitted remain
in the output file; unfinished drafts are not written as complete items.
