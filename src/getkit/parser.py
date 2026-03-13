from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable
from urllib.parse import urljoin

from lxml import etree
from lxml import html as lxml_html


@dataclass(slots=True)
class Element:
    _element: object
    base_url: str | None = None

    @property
    def tag(self) -> str:
        return getattr(self._element, "tag", "")

    @property
    def attrs(self) -> dict[str, str]:
        return dict(getattr(self._element, "attrib", {}) or {})

    def attr(self, name: str, default: str | None = None) -> str | None:
        return self.attrs.get(name, default)

    def html(self) -> str:
        return etree.tostring(self._element, encoding="unicode")

    def text(self, separator: str = " ", strip: bool = True) -> str:
        text = " ".join(part.strip() if strip else part for part in self._element.itertext())
        return separator.join(filter(None, text.split())) if strip and separator == " " else text

    def css(self, selector: str) -> list["Element"]:
        return [Element(node, self.base_url) for node in self._element.cssselect(selector)]

    def css_first(self, selector: str) -> "Element | None":
        results = self.css(selector)
        return results[0] if results else None

    def xpath(self, selector: str) -> list["Element"]:
        results = self._element.xpath(selector)
        return [Element(node, self.base_url) for node in results if hasattr(node, "tag")]

    def xpath_first(self, selector: str) -> "Element | None":
        results = self.xpath(selector)
        return results[0] if results else None

    def links(self, attr: str = "href") -> list[str]:
        urls: list[str] = []
        for node in self.css(f"[{attr}]"):
            value = node.attr(attr)
            if value:
                urls.append(urljoin(self.base_url or "", value))
        return urls


class Document:
    def __init__(self, content: str | bytes, base_url: str | None = None):
        self._raw = content
        self.base_url = base_url
        self._tree = None

    @property
    def raw_text(self) -> str:
        if isinstance(self._raw, bytes):
            return self._raw.decode("utf-8", errors="replace")
        return self._raw

    def _get_tree(self):
        if self._tree is None:
            self._tree = lxml_html.fromstring(self.raw_text or "")
            if self.base_url:
                self._tree.make_links_absolute(self.base_url, resolve_base_href=True)
        return self._tree

    def css(self, selector: str) -> list[Element]:
        return [Element(node, self.base_url) for node in self._get_tree().cssselect(selector)]

    def css_first(self, selector: str) -> Element | None:
        results = self.css(selector)
        return results[0] if results else None

    def xpath(self, selector: str) -> list[Element]:
        results = self._get_tree().xpath(selector)
        return [Element(node, self.base_url) for node in results if hasattr(node, "tag")]

    def xpath_first(self, selector: str) -> Element | None:
        results = self.xpath(selector)
        return results[0] if results else None

    def text_content(self, separator: str = " ", strip: bool = True) -> str:
        text = " ".join(part.strip() if strip else part for part in self._get_tree().itertext())
        return separator.join(filter(None, text.split())) if strip and separator == " " else text

    def links(self, selector: str = "a[href]", attr: str = "href") -> list[str]:
        links: list[str] = []
        for element in self.css(selector):
            value = element.attr(attr)
            if value:
                links.append(urljoin(self.base_url or "", value))
        return links

    def iter_elements(self) -> Iterable[Element]:
        for node in self._get_tree().iter():
            if hasattr(node, "tag"):
                yield Element(node, self.base_url)
