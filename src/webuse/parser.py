from html.parser import HTMLParser
import re as re_module
from typing import Any, Iterable
from urllib.parse import urljoin

from lxml import etree
from lxml import html as lxml_html
from pydantic import BaseModel, ConfigDict


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        _ = attrs
        if tag.lower() in {"script", "style", "noscript"}:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style", "noscript"} and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            self.parts.append(data)


def _text_without_tree(content: str, separator: str = " ", strip: bool = True) -> str:
    parser = _TextExtractor()
    parser.feed(content)
    text = " ".join(part.strip() if strip else part for part in parser.parts)
    return (
        separator.join(filter(None, text.split()))
        if strip and separator == " "
        else text
    )


class Element(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    element: Any
    base_url: str | None = None

    def __init__(self, element: object, base_url: str | None = None):
        super().__init__(element=element, base_url=base_url)

    @property
    def tag(self) -> str:
        return getattr(self.element, "tag", "")

    @property
    def attrs(self) -> dict[str, str]:
        return dict(getattr(self.element, "attrib", {}) or {})

    def attr(self, name: str, default: str | None = None) -> str | None:
        return self.attrs.get(name, default)

    def html(self) -> str:
        return etree.tostring(self.element, encoding="unicode")

    def text(self, separator: str = " ", strip: bool = True) -> str:
        text = " ".join(
            part.strip() if strip else part for part in self.element.itertext()
        )
        return (
            separator.join(filter(None, text.split()))
            if strip and separator == " "
            else text
        )

    def css(self, selector: str) -> list["Element"]:
        return [
            Element(node, self.base_url) for node in self.element.cssselect(selector)
        ]

    def css_first(self, selector: str) -> "Element | None":
        results = self.css(selector)
        return results[0] if results else None

    def xpath(self, selector: str) -> list["Element"]:
        results = self.element.xpath(selector)
        return [
            Element(node, self.base_url) for node in results if hasattr(node, "tag")
        ]

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
        return [
            Element(node, self.base_url)
            for node in self._get_tree().cssselect(selector)
        ]

    def css_first(self, selector: str) -> Element | None:
        results = self.css(selector)
        return results[0] if results else None

    def xpath(self, selector: str) -> list[Element]:
        results = self._get_tree().xpath(selector)
        return [
            Element(node, self.base_url) for node in results if hasattr(node, "tag")
        ]

    def xpath_first(self, selector: str) -> Element | None:
        results = self.xpath(selector)
        return results[0] if results else None

    def text_content(self, separator: str = " ", strip: bool = True) -> str:
        text = " ".join(
            part.strip() if strip else part for part in self._get_tree().itertext()
        )
        return (
            separator.join(filter(None, text.split()))
            if strip and separator == " "
            else text
        )

    def links(self, selector: str = "a[href]", attr: str = "href") -> list[str]:
        links: list[str] = []
        for element in self.css(selector):
            value = element.attr(attr)
            if value:
                links.append(urljoin(self.base_url or "", value))
        return links

    def re(self, pattern: str | re_module.Pattern[str], flags: int = 0) -> list[Any]:
        return re_module.findall(pattern, self.raw_text, flags)

    def re_first(
        self,
        pattern: str | re_module.Pattern[str],
        default: Any = None,
        flags: int = 0,
    ) -> Any:
        matches = self.re(pattern, flags)
        return matches[0] if matches else default

    def iter_elements(self) -> Iterable[Element]:
        for node in self._get_tree().iter():
            if hasattr(node, "tag"):
                yield Element(node, self.base_url)
