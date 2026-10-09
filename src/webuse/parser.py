from __future__ import annotations

import re as re_module
from typing import TYPE_CHECKING, Any, Iterable
from urllib.parse import urljoin

from pydantic import BaseModel, ConfigDict
from selectolax.lexbor import LexborHTMLParser, LexborNode

from .smart import extract_smart, resolve_smart

if TYPE_CHECKING:
    from .smart import SmartResolver, SmartSelectorStore


class Element(BaseModel):
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

    def css(self, selector: str) -> list["Element"]:
        return [Element(node, self.base_url) for node in self.element.css(selector)]

    def css_first(self, selector: str) -> "Element | None":
        node = self.element.css_first(selector)
        return Element(node, self.base_url) if node is not None else None

    def links(self, attr: str = "href") -> list[str]:
        urls: list[str] = []
        for node in self.css(f"[{attr}]"):
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


class Document:
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
            base = self._tree.css_first("base[href]")
            link_base = self.url or ""
            if base is not None:
                link_base = urljoin(link_base, base.attributes.get("href") or "")
            if link_base:
                for node in self._tree.root.traverse():
                    for attr, value in node.attributes.items():
                        if value and attr in {
                            "href",
                            "src",
                            "action",
                            "formaction",
                            "poster",
                            "cite",
                            "background",
                            "data",
                            "longdesc",
                        }:
                            if attr == "data" and node.tag != "object":
                                continue
                            if node.tag == "base" and attr == "href":
                                node.attrs[attr] = urljoin(self.url or "", value)
                                continue
                            node.attrs[attr] = urljoin(link_base, value)
        return self._tree

    def css(self, selector: str) -> list[Element]:
        return [Element(node, self.url) for node in self._get_tree().css(selector)]

    def css_first(self, selector: str) -> Element | None:
        node = self._get_tree().css_first(selector)
        return Element(node, self.url) if node is not None else None

    def text_content(self, separator: str = " ", strip: bool = True) -> str:
        text = self._get_tree().text(separator=separator, strip=strip)
        return " ".join(text.split()) if strip and separator == " " else text

    def links(self, selector: str = "a[href]", attr: str = "href") -> list[str]:
        links: list[str] = []
        for element in self.css(selector):
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

    def smart(self, prompt: str, **kwargs: Any) -> list[Any]:
        return extract_smart(self, prompt, first=False, **kwargs)

    def smart_first(self, prompt: str, **kwargs: Any) -> Any:
        return extract_smart(self, prompt, first=True, **kwargs)

    def smart_all(self, prompts: list[str], **kwargs: Any) -> dict[str, list[Any]]:
        return {prompt: self.smart(prompt, **kwargs) for prompt in prompts}

    def find_element(
        self,
        prompt: str,
        *,
        key: str | None = None,
        use_llm: bool = False,
        resolver: SmartResolver | None = None,
        store: SmartSelectorStore | None = None,
    ) -> Element:
        return resolve_smart(
            self,
            prompt,
            key=key,
            use_llm=use_llm,
            resolver=resolver,
            store=store,
        )
