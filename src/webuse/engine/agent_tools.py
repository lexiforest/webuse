"""Crawler operations available to the agent; state stays outside model context."""

import inspect
import json
from itertools import islice
from typing import Any, Literal
from urllib.parse import urljoin, urlparse

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..agent import AgentTool
from ..log import logger
from ..models import CrawlRequest
from .policy import domain, normalize_url, robots_parser_from_response, robots_url
from .state import (
    DefaultRequestHasher,
    MemoryRequestQueue,
    MemoryRequestSeen,
    state_info,
)


class ToolError(ValueError):
    """An actionable error returned to the model without ending the execution."""


class LimitReached(Exception):
    pass


class Arguments(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class RequestURL(Arguments):
    url: str


class Inspect(Arguments):
    view: Literal["text", "html", "links", "state", "urls"] = "text"
    page_id: str | None = None
    offset: int = Field(default=0, ge=0)


class Extract(Arguments):
    page_id: str
    css: str
    attr: str | None = None
    offset: int = Field(default=0, ge=0)


class UpdateRecord(Arguments):
    record_id: str = Field(min_length=1)
    fields: dict[str, Any]
    sources: dict[str, list[str]]


class EmitRecord(Arguments):
    record_id: str


class UpdateMemory(Arguments):
    findings: str | None = None
    completed: str | None = None
    next_steps: str | None = None


class CrawlTools:
    def __init__(
        self,
        *,
        seeds,
        item_model,
        limits,
        result,
        client,
        signals,
        allowed_domains,
        max_depth,
        robots_txt,
        user_agent,
        process_item,
        request_queue=None,
        request_seen=None,
        request_hasher=None,
    ):
        self.item_model = item_model
        self.limits = limits
        self.result = result
        self.info = result.agent
        self.client = client
        self.signals = signals
        self.allowed_domains = allowed_domains
        self.max_depth = max_depth
        self.robots_txt = robots_txt
        self.user_agent = user_agent
        self.process_item = process_item
        self.seeds = [r.model_copy(update={"url": normalize_url(r.url)}) for r in seeds]
        self.known = {request.url: request for request in self.seeds}
        self.seed_urls = list(self.known)
        self.pages = {}
        self.fetched = {}
        self.robots = {}
        self.hasher = (
            request_hasher if request_hasher is not None else DefaultRequestHasher()
        )
        self.queue = (
            request_queue if request_queue is not None else MemoryRequestQueue()
        )
        self.seen = request_seen if request_seen is not None else MemoryRequestSeen()
        self.enqueued = MemoryRequestSeen()
        self.current = None
        self.current_page = None

    async def start(self):
        await self.signals.asend("state_loaded", **state_info(self.queue, self.seen))
        for request in self.seeds:
            await self._enqueue(request, source="start")

    async def _state_updated(self):
        await self.signals.asend("state_updated", **state_info(self.queue, self.seen))

    def idle(self):
        return self.current is None and self.queue.empty()

    def _request(self, url):
        request = self.known.get(normalize_url(url))
        if request is None:
            raise ToolError(
                "URL must be a seed or a link returned by inspect(view='links')"
            )
        self._admit(request.url, request.depth)
        return request

    async def _enqueue(self, request, *, source):
        key = self.hasher.hash(request)
        if self.seen.contains(key) or not self.enqueued.add(key):
            self.result.stats.skipped_duplicates += 1
            await self.signals.asend(
                "request_skipped", request=request, reason="duplicate"
            )
            return {"url": request.url, "queued": False, "duplicate": True}
        self.queue.put(request)
        await self.signals.asend("request_queued", request=request, source=source)
        await self._state_updated()
        return {"url": request.url, "queued": True}

    async def queue_push(self, args):
        return await self._enqueue(self._request(args.url), source="follow")

    def seen_exist(self, args):
        return {"seen": self.seen.contains(self.hasher.hash(self._request(args.url)))}

    async def seen_add(self, args):
        request = self._request(args.url)
        added = self.seen.add(self.hasher.hash(request))
        await self._state_updated()
        return {"url": request.url, "added": added}

    async def queue_pop(self, args):
        # A pop is the callback-return boundary: all preceding extraction and
        # pipeline work has been awaited before the next request is selected.
        self.current = None
        self.current_page = None
        while not self.queue.empty():
            request = self.queue.pop()
            if request is None:
                break
            self.known.setdefault(normalize_url(request.url), request)
            if not self.seen.add(self.hasher.hash(request)):
                self.result.stats.skipped_duplicates += 1
                await self.signals.asend(
                    "request_skipped", request=request, reason="duplicate"
                )
                continue
            self.current = request
            await self._state_updated()
            try:
                self.current_page = await self._fetch(request)
                return self.current_page
            except ToolError as exc:
                self.result.errors.append(
                    {"url": request.url, "error": str(exc), "stage": "request"}
                )
                logger.warning("agent request failed url={} error={}", request.url, exc)
                self.current = None
        await self._state_updated()
        return {"queue_empty": True, "current_request": None}

    def tools(self):
        return [
            AgentTool(
                "queue_push",
                "Queue a relevant seed or observed link for later processing. Preserves request depth and deduplicates.",
                RequestURL,
                self.queue_push,
            ),
            AgentTool(
                "queue_pop",
                "Complete processing of the current request, then pop and download the next unseen request. "
                "Save items and queue relevant links first. Call this last in a batch. "
                "The engine stops automatically when there is no next request.",
                Arguments,
                self.queue_pop,
            ),
            AgentTool(
                "seen_add",
                "Mark an observed URL as handled or deliberately excluded. Queued requests for it will be skipped. "
                "Popped requests are marked seen automatically; do not mark a URL before queueing it for download.",
                RequestURL,
                self.seen_add,
            ),
            AgentTool(
                "seen_exist",
                "Check whether a request URL has been handled or excluded, using the crawler's request hasher.",
                RequestURL,
                self.seen_exist,
            ),
            AgentTool(
                "inspect",
                "Read text, HTML, links, state, or the discovered URL ledger (urls). "
                "The ledger includes fetched page IDs; null means not fetched. "
                "Use next_offset to read more.",
                Inspect,
                self.inspect,
            ),
            AgentTool(
                "extract",
                "Extract text or an attribute using CSS on a fetched page.",
                Extract,
                self.extract,
            ),
            AgentTool(
                "update_record",
                "Merge declared fields into a draft. sources maps each updated field to fetched page IDs.",
                UpdateRecord,
                self.update_record,
            ),
            AgentTool(
                "emit_record",
                "Validate a draft against the output schema and send it through pipelines once.",
                EmitRecord,
                self.emit_record,
            ),
            AgentTool(
                "update_memory",
                "Save compact working memory included in every future turn. "
                "Replace only supplied fields: findings, completed, next_steps. "
                "Preserve important earlier facts when replacing a field. "
                "Use page ranges and cursors for large catalogs, not URL lists. "
                "Keep the combined JSON within limits.memory_chars; empty strings clear fields.",
                UpdateMemory,
                self.update_memory,
            ),
        ]

    def _admit(self, url, depth):
        parsed = urlparse(url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
        ):
            raise ToolError(
                "Only HTTP(S) URLs without embedded credentials are allowed"
            )
        if self.allowed_domains and domain(url) not in self.allowed_domains:
            raise ToolError("URL is outside allowed_domains")
        if self.max_depth is not None and depth > self.max_depth:
            raise ToolError("URL exceeds max_depth")

    async def _download(self, request):
        self._admit(request.url, request.depth)
        if (
            self.limits.max_requests is not None
            and self.result.stats.queued >= self.limits.max_requests
        ):
            raise LimitReached("request_limit")
        self.result.stats.queued += 1
        await self.signals.asend("request_before_downloader", request=request)
        body = bytearray()

        def receive(chunk):
            if len(body) + len(chunk) > self.limits.max_page_bytes:
                return 0  # curl aborts the transfer; do not retain an oversized body.
            body.extend(chunk)
            return len(chunk)

        options = request.options.to_request_kwargs()
        options.update(allow_redirects=False, stream=False)
        if self.limits.max_page_bytes is not None:
            options["content_callback"] = receive
        try:
            response = await self.client.request(request.method, request.url, **options)
            if body:
                response.content = bytes(body)
            if (
                self.limits.max_page_bytes is not None
                and len(response.content) > self.limits.max_page_bytes
            ):
                raise ToolError("Response exceeds max_page_bytes")
        except Exception as exc:
            await self.signals.asend(
                "request_after_downloader", request=request, success=False
            )
            await self.signals.asend("request_error", request=request, error=exc)
            raise ToolError("Download failed") from exc
        await self.signals.asend(
            "request_after_downloader", request=request, success=True
        )
        response.crawl_request = request
        self.result.visited.add(request.url)
        logger.info("agent fetch url={} status={}", request.url, response.status_code)
        return response

    async def _robots_allowed(self, request):
        if not self.robots_txt:
            return True
        url = robots_url(request.url)
        if url not in self.robots:
            current = url
            for _ in range(6):
                response = await self._download(CrawlRequest(url=current))
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("location")
                    if not location:
                        raise ToolError("robots.txt redirect has no location")
                    current = normalize_url(urljoin(current, location))
                    continue
                if response.status_code >= 500:
                    raise ToolError("robots.txt is unavailable")
                self.robots[url] = robots_parser_from_response(url, response)
                break
            else:
                raise ToolError("Too many robots.txt redirects")
        return self.robots[url].can_fetch(self.user_agent, request.url)

    async def _fetch(self, request):
        original_hash = self.hasher.hash(request)
        for redirect in range(11):
            try:
                self._admit(request.url, request.depth)
            except ToolError:
                self.result.stats.skipped_rules += 1
                await self.signals.asend(
                    "request_skipped", request=request, reason="rules"
                )
                raise
            key = self.hasher.hash(request)
            if redirect and not self.seen.add(key) and key not in self.fetched:
                raise ToolError("Redirect target was already handled")
            if key in self.fetched:
                self.result.stats.skipped_duplicates += 1
                self.fetched[original_hash] = self.fetched[key]
                return {"page_id": self.fetched[key], "cached": True}
            if not await self._robots_allowed(request):
                self.result.stats.skipped_robots += 1
                await self.signals.asend(
                    "request_skipped", request=request, reason="robots"
                )
                raise ToolError("robots.txt disallows this URL")
            response = await self._download(request)
            if response.status_code in {301, 302, 303, 307, 308}:
                location = response.headers.get("location")
                if not location:
                    raise ToolError("Redirect has no location")
                request = request.model_copy(
                    update={"url": normalize_url(urljoin(request.url, location))}
                )
                continue
            page_id = f"p{len(self.pages) + 1}"
            self.pages[page_id] = response
            self.fetched[key] = self.fetched[original_hash] = page_id
            self.result.pages.append(response)
            self.result.stats.fetched += 1
            if request.parent_url:
                self.result.stats.followed_links += 1
            await self.signals.asend(
                "response_received", response=response, request=request
            )
            return {
                "page_id": page_id,
                "url": response.url,
                "status": response.status_code,
                "text": self._chunk(response.text_content(), 0),
            }
        raise ToolError("Too many redirects")

    def _page(self, page_id):
        if page_id not in self.pages:
            raise ToolError("Unknown page_id")
        return self.pages[page_id]

    def _chunk(self, text, offset):
        end = offset + self.limits.observation_chars
        return {
            "content": text[offset:end],
            "next_offset": end if end < len(text) else None,
            "total_chars": len(text),
        }

    def usage(self):
        return {
            "requests": self.result.stats.queued,
            "turns": self.info.turns,
            "tokens": self.info.tokens,
        }

    def prompt_state(self):
        """Bounded working context without copying the entire crawl history."""
        return {
            "queue": state_info(self.queue, self.seen),
            "current_request": (
                {
                    "url": self.current.url,
                    "depth": self.current.depth,
                    "page": self.current_page,
                }
                if self.current is not None
                else None
            ),
            "pages": [
                {"page_id": key, "url": page.url}
                for key, page in reversed(list(islice(reversed(self.pages.items()), 5)))
            ],
            "page_count": len(self.pages),
            "known_url_count": len(self.known),
            "draft_ids": list(reversed(list(islice(reversed(self.info.drafts), 20)))),
            "draft_count": len(self.info.drafts),
            "emitted_count": len(self.info.emitted_ids),
            "memory": self.info.memory,
            "progress": self.info.progress,
            "usage": self.usage(),
        }

    def state(self):
        return {
            "queue": state_info(self.queue, self.seen),
            "current_request": self.current.url if self.current is not None else None,
            "pages": [
                {"page_id": key, "url": page.url} for key, page in self.pages.items()
            ],
            "seeds": self.seed_urls,
            "drafts": self.info.drafts,
            "sources": self.info.sources,
            "emitted_ids": self.info.emitted_ids,
            "memory": self.info.memory,
            "progress": self.info.progress,
            "known_url_count": len(self.known),
            "usage": self.usage(),
        }

    def inspect(self, args):
        if args.view == "state":
            return self._chunk(json.dumps(self.state(), ensure_ascii=True), args.offset)
        if args.view == "urls":
            urls = [
                {
                    "url": url,
                    "page_id": self.fetched.get(self.hasher.hash(request)),
                    "depth": request.depth,
                    "seen": self.seen.contains(self.hasher.hash(request)),
                }
                for url, request in islice(
                    self.known.items(), args.offset, args.offset + 20
                )
            ]
            end = args.offset + len(urls)
            return {
                "urls": urls,
                "next_offset": end if end < len(self.known) else None,
                "total_urls": len(self.known),
            }
        page = self._page(args.page_id)
        if args.view == "links":
            elements = page.find_all(css="a[href]")
            links = []
            # Link offsets count elements, unlike text/HTML offsets.
            end = args.offset
            for element in elements[args.offset : args.offset + 20]:
                url = normalize_url(urljoin(page.url, element.attr("href")))
                candidate = CrawlRequest(
                    url=url, depth=page.crawl_request.depth + 1, parent_url=page.url
                )
                end += 1
                try:
                    self._admit(url, candidate.depth)
                except ToolError:
                    continue
                previous = self.known.get(url)
                if previous is None or candidate.depth < previous.depth:
                    self.known[url] = candidate
                links.append({"url": url, "text": element.text()[:200]})
            return {"links": links, "next_offset": end if end < len(elements) else None}
        text = page.text if args.view == "html" else page.text_content()
        return self._chunk(text, args.offset)

    def extract(self, args):
        page = self._page(args.page_id)
        try:
            elements = page.find_all(css=args.css)
        except Exception as exc:
            raise ToolError("Invalid CSS selector") from exc
        values = [e.attr(args.attr) if args.attr else e.text() for e in elements]
        return self._chunk(json.dumps(values, ensure_ascii=True), args.offset)

    def update_memory(self, args):
        fields = args.model_dump(exclude_none=True)
        if not fields:
            raise ToolError("Supply at least one memory field to update")
        memory = {**self.info.memory, **fields}
        if len(json.dumps(memory, ensure_ascii=True)) > self.limits.memory_chars:
            raise ToolError(
                "Working memory exceeds memory_chars; condense completed work "
                "into ranges and keep pending-work cursors before retrying"
            )
        self.info.memory = memory
        return {"memory": memory}

    def update_record(self, args):
        if args.record_id in self.info.emitted_ids:
            raise ToolError("Record has already been emitted")
        properties = self.item_model.model_json_schema().get("properties", {})
        if args.fields.keys() - properties.keys():
            raise ToolError("Record contains undeclared fields")
        if args.sources.keys() != args.fields.keys():
            raise ToolError("Supply source page IDs for each updated field")
        for page_ids in args.sources.values():
            if not page_ids or any(page_id not in self.pages for page_id in page_ids):
                raise ToolError("Sources must reference fetched pages")
        draft = {**self.info.drafts.get(args.record_id, {}), **args.fields}
        self.info.drafts[args.record_id] = draft
        self.info.sources.setdefault(args.record_id, {}).update(
            {
                field: [self.pages[p].url for p in pages]
                for field, pages in args.sources.items()
            }
        )
        return {"record_id": args.record_id, "draft": draft}

    async def emit_record(self, args):
        if args.record_id in self.info.emitted_ids:
            return {"record_id": args.record_id, "already_emitted": True}
        if args.record_id not in self.info.drafts:
            raise ToolError("Unknown record_id")
        try:
            item = self.item_model.model_validate(self.info.drafts[args.record_id])
        except ValidationError as exc:
            raise ToolError(str(exc)) from exc
        if self.process_item:
            items = self.process_item(item)
            items = await items if inspect.isawaitable(items) else items
        else:
            await self.signals.asend("item_extracted", item=item)
            await self.signals.asend("item_processed", item=item)
            items = [item]
        self.result.items.extend(items)
        self.info.emitted_ids.append(args.record_id)
        del self.info.drafts[args.record_id]
        return {"record_id": args.record_id, "emitted": len(items)}
