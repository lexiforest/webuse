from __future__ import annotations

import re as re_module
from typing import Any, Iterable
from urllib.parse import urljoin

from pydantic import BaseModel, ConfigDict
from selectolax.lexbor import LexborHTMLParser, LexborNode

from ..selection import validate_selector
from .resolver import AsyncLlmSelector, LlmSelector
from .structured import aextract_structured, extract_structured
from .urls import make_links_absolute


class Selection:
    """Select nodes, read their values, or explicitly transform content with an LLM."""

    def find_all(
        self,
        *,
        css: str | None = None,
        llm: str | None = None,
        selector: LlmSelector | None = None,
    ) -> list["Element"]:
        validate_selector(css, llm)
        if css is not None:
            if selector is not None:
                raise ValueError("selector is only valid with llm")
            return self._css_all(css)
        return (selector or LlmSelector()).select(llm, self)

    def find(
        self,
        *,
        css: str | None = None,
        llm: str | None = None,
        selector: LlmSelector | None = None,
    ) -> "Element | None":
        validate_selector(css, llm)
        if css is not None:
            if selector is not None:
                raise ValueError("selector is only valid with llm")
            return self._css_first(css)
        matches = self.find_all(llm=llm, selector=selector)
        return matches[0] if matches else None

    async def afind_all(
        self,
        *,
        css: str | None = None,
        llm: str | None = None,
        selector: AsyncLlmSelector | None = None,
    ) -> list["Element"]:
        validate_selector(css, llm)
        if css is not None:
            return self.find_all(css=css, selector=selector)
        return await (selector or AsyncLlmSelector()).select(llm, self)

    async def afind(
        self,
        *,
        css: str | None = None,
        llm: str | None = None,
        selector: AsyncLlmSelector | None = None,
    ) -> "Element | None":
        validate_selector(css, llm)
        if css is not None:
            return self.find(css=css, selector=selector)
        matches = await self.afind_all(llm=llm, selector=selector)
        return matches[0] if matches else None

    def llm_extract(self, prompt: str, *, schema: Any, **kwargs: Any) -> Any:
        """Transform content into a validated Python type or JSON Schema value."""
        return extract_structured(self, prompt, schema=schema, **kwargs)

    async def allm_extract(self, prompt: str, *, schema: Any, **kwargs: Any) -> Any:
        return await aextract_structured(self, prompt, schema=schema, **kwargs)


class Element(Selection, BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    element: LexborNode
    base_url: str | None = None

    def __init__(self, element: LexborNode, base_url: str | None = None):
        super().__init__(element=element, base_url=base_url)

    @property
    def tag(self) -> str:
        return self.element.tag

    @property
    def attrs(self) -> dict[str, str]:
        return {key: value or "" for key, value in self.element.attributes.items()}

    def attr(self, name: str, default: str | None = None) -> str | None:
        return self.attrs.get(name, default)

    def html(self) -> str:
        return self.element.html

    def text(self, separator: str = " ", strip: bool = True) -> str:
        text = self.element.text(separator=separator, strip=strip)
        return " ".join(text.split()) if strip and separator == " " else text

    def _css_all(self, selector: str) -> list["Element"]:
        return [Element(node, self.base_url) for node in self.element.css(selector)]

    def _css_first(self, selector: str) -> "Element | None":
        """Return the first CSS match, or None."""
        node = self.element.css_first(selector)
        return Element(node, self.base_url) if node is not None else None

    def iter_elements(self) -> Iterable["Element"]:
        for node in self.element.traverse():
            yield Element(node, self.base_url)

    def links(self, attr: str = "href") -> list[str]:
        urls: list[str] = []
        for node in self.find_all(css=f"[{attr}]"):
            value = node.attr(attr)
            if value:
                urls.append(urljoin(self.base_url or "", value))
        return urls

    def re(self, pattern: str | re_module.Pattern[str], flags: int = 0) -> list[Any]:
        return re_module.findall(pattern, self.html(), flags)

    def re_first(
        self,
        pattern: str | re_module.Pattern[str],
        default: Any = None,
        flags: int = 0,
    ) -> Any:
        matches = self.re(pattern, flags)
        return matches[0] if matches else default


class Document(Selection):
    def __init__(self, content: str | bytes, url: str | None = None):
        self._raw = content
        self.url = url
        self._tree = None

    @property
    def text(self) -> str:
        if isinstance(self._raw, bytes):
            return self._raw.decode("utf-8", errors="replace")
        return self._raw

    def _get_tree(self) -> LexborHTMLParser:
        if self._tree is None:
            self._tree = LexborHTMLParser(self.text)
            make_links_absolute(self._tree, self.url)
        return self._tree

    def _css_all(self, selector: str) -> list[Element]:
        return [Element(node, self.url) for node in self._get_tree().css(selector)]

    def _css_first(self, selector: str) -> Element | None:
        """Return the first CSS match, or None, without using an LLM."""
        node = self._get_tree().css_first(selector)
        return Element(node, self.url) if node is not None else None

    def text_content(self, separator: str = " ", strip: bool = True) -> str:
        text = self._get_tree().text(separator=separator, strip=strip)
        return " ".join(text.split()) if strip and separator == " " else text

    def links(self, selector: str = "a[href]", attr: str = "href") -> list[str]:
        links: list[str] = []
        for element in self.find_all(css=selector):
            value = element.attr(attr)
            if value:
                links.append(urljoin(self.url or "", value))
        return links

    def re(self, pattern: str | re_module.Pattern[str], flags: int = 0) -> list[Any]:
        return re_module.findall(pattern, self.text, flags)

    def re_first(
        self,
        pattern: str | re_module.Pattern[str],
        default: Any = None,
        flags: int = 0,
    ) -> Any:
        matches = self.re(pattern, flags)
        return matches[0] if matches else default

    def iter_elements(self) -> Iterable[Element]:
        for node in self._get_tree().root.traverse():
            yield Element(node, self.url)
