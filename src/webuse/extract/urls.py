"""Resolve known HTML URL locations without guessing at arbitrary strings."""

import re
from urllib.parse import urljoin, urlsplit

_SPACE = " \t\n\r\f"
_SINGLE = frozenset(
    {
        "href",
        "src",
        "action",
        "formaction",
        "poster",
        "cite",
        "background",
        "longdesc",
        "usemap",
        "manifest",
        "codebase",
        "classid",
        "itemid",
        "xlink:href",
    }
)
_LIST = frozenset({"ping", "archive", "profile", "itemtype"})
_META_URL = frozenset(
    {
        "og:url",
        "og:image",
        "og:image:url",
        "og:image:secure_url",
        "og:video",
        "og:video:url",
        "og:video:secure_url",
        "og:audio",
        "og:audio:url",
        "og:audio:secure_url",
        "twitter:url",
        "twitter:image",
        "twitter:image:src",
        "twitter:player",
        "twitter:player:stream",
    }
)
_REFRESH = re.compile(
    r"^(\s*[0-9]+(?:\.[0-9]+)?\s*[;,]\s*(?:url\s*=\s*)?)(.*)$", re.I | re.S
)


def absolute_url(value: str, base: str) -> str:
    if not value.strip(_SPACE):
        return value
    try:
        return urljoin(base, value.strip(_SPACE))
    except ValueError:
        # One malformed link must not prevent extraction of the rest of a page.
        return value


def srcset_urls(value: str, base: str) -> str:
    """Rewrite URL spans, preserving descriptors and commas inside URLs (data:)."""
    result = []
    position = 0
    copied = 0
    while position < len(value):
        while position < len(value) and value[position] in _SPACE + ",":
            position += 1
        start = position
        while position < len(value) and value[position] not in _SPACE:
            position += 1
        end = position
        while end > start and value[end - 1] == ",":
            end -= 1
        if end > start:
            result.extend((value[copied:start], absolute_url(value[start:end], base)))
            copied = end
        if end < position:
            continue
        # A comma inside a parenthesized descriptor does not start a candidate.
        depth = 0
        while position < len(value):
            char = value[position]
            position += 1
            if char == "(":
                depth += 1
            elif char == ")" and depth:
                depth -= 1
            elif char == "," and not depth:
                break
    return "".join(result) + value[copied:]


def attribute_url(
    tag: str, attrs: dict, name: str, value: str, base: str, document_url: str
) -> str:
    if name in {"srcset", "imagesrcset"}:
        return srcset_urls(value, base)
    if tag in {"object", "applet"} and name in {"data", "classid", "code", "archive"}:
        try:
            base = urljoin(base, attrs.get("codebase") or base)
        except ValueError:
            pass
    if tag == "applet" and name == "archive":
        return re.sub(r"[^, \t\n\r\f]+", lambda m: absolute_url(m[0], base), value)
    if name in _LIST:
        return re.sub(r"[^ \t\n\r\f]+", lambda m: absolute_url(m[0], base), value)
    if (
        name in _SINGLE
        or (name == "data" and tag == "object")
        or (name == "code" and tag == "applet")
    ):
        return absolute_url(value, document_url if tag == "base" else base)
    if (
        tag == "param"
        and name == "value"
        and (attrs.get("valuetype") or "").lower() == "ref"
    ):
        return absolute_url(value, base)
    if tag == "meta" and name == "content":
        if (attrs.get("http-equiv") or "").lower() == "refresh":
            match = _REFRESH.match(value)
            if match:
                url = match[2].strip(_SPACE)
                quote = url[:1] if url[:1] in {"'", '"'} and url[-1:] == url[:1] else ""
                url = url[1:-1] if quote else url
                return match[1] + quote + absolute_url(url, base) + quote
        if (attrs.get("property") or attrs.get("name") or "").lower() in _META_URL:
            return absolute_url(value, base)
        if set((attrs.get("itemprop") or "").split()) & {
            "url",
            "image",
            "contentUrl",
            "embedUrl",
            "thumbnailUrl",
            "sameAs",
        }:
            return absolute_url(value, base)
    return value


def make_links_absolute(tree, document_url: str | None) -> None:
    base_node = tree.css_first("base[href]")
    base = document_url or ""
    if base_node is not None:
        try:
            candidate = urljoin(base, base_node.attributes.get("href") or "")
            if urlsplit(candidate).scheme.lower() not in {"data", "javascript"}:
                base = candidate
        except ValueError:
            pass
    if not base:
        return
    for node in tree.root.traverse():
        attrs = node.attributes
        for name, value in attrs.items():
            if value:
                resolved = attribute_url(
                    node.tag, attrs, name, value, base, document_url or ""
                )
                if resolved != value:
                    node.attrs[name] = resolved
