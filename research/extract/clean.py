"""
HTML cleaner for reducing page size before sending to LLMs.

Uses lxml.html.Cleaner for safe, robust HTML sanitization, plus
additional passes for attribute stripping and wrapper collapsing.

Typical reduction: 70-90% on real-world pages.

Usage:
    from clean import clean_html
    small = clean_html(big_html, target_kb=80)
"""

from __future__ import annotations

import re

from lxml import etree
from lxml import html as lxml_html
from lxml_html_clean import Cleaner

# Attributes worth keeping
KEEP_ATTRS = {
    "href",
    "src",
    "alt",
    "id",
    "class",
    "type",
    "datetime",
    "content",
    "name",
    "property",
}

# Regex for CSS-hash class names like "sc-1a2b3c" or "css-xyz123"
CSS_HASH_RE = re.compile(r"^(?:sc|css|styled|emotion|_)-?[a-zA-Z0-9]{4,}$")


def _make_cleaner(strip_boilerplate: bool = True) -> Cleaner:
    """Build an lxml Cleaner with aggressive but content-safe settings."""
    return Cleaner(
        # remove these tag types entirely
        scripts=True,
        javascript=True,
        style=True,
        embedded=True,  # object/embed/applet
        frames=True,  # iframe/frame
        forms=False,  # keep forms (may contain content)
        # strip these tags but keep their text content
        remove_tags=None,
        # remove these tags along with all children
        kill_tags=["svg", "canvas", "map", "area", "noscript"]
        + (["nav", "footer", "header", "aside"] if strip_boilerplate else []),
        comments=True,
        processing_instructions=True,
        meta=False,  # keep meta tags (may have useful structured data)
        links=False,  # keep <link> tags
        page_structure=False,  # keep html/head/body
        annoying_tags=True,  # blink, marquee
        remove_unknown_tags=False,
        safe_attrs_only=False,  # we handle attrs ourselves in a later pass
    )


def clean_html(
    raw_html: str,
    *,
    keep_json_ld: bool = True,
    strip_boilerplate: bool = True,
    strip_attrs: bool = True,
    collapse_wrappers: bool = True,
    target_kb: int | None = None,
) -> str:
    """Clean HTML for LLM consumption.

    Args:
        raw_html: the raw HTML string.
        keep_json_ld: preserve <script type="application/ld+json"> content.
        strip_boilerplate: remove nav/footer/header/aside.
        strip_attrs: remove non-essential attributes.
        collapse_wrappers: unwrap <div>s that have exactly one child element.
        target_kb: if set, apply aggressive trimming to stay under this size (KB).
    """
    # preserve json-ld before the cleaner strips all scripts
    json_ld_blocks: list[str] = []
    if keep_json_ld:
        try:
            pre_tree = lxml_html.fromstring(raw_html)
            for el in pre_tree.xpath('//script[@type="application/ld+json"]'):
                text = el.text_content().strip()
                if text:
                    json_ld_blocks.append(text)
        except Exception:
            pass

    # parse and clean with lxml Cleaner
    try:
        tree = lxml_html.fromstring(raw_html)
    except Exception:
        return raw_html

    cleaner = _make_cleaner(strip_boilerplate)
    cleaner(tree)

    # --- remove hidden elements ---
    for el in tree.xpath("//*[@style]"):
        style = (el.get("style") or "").replace(" ", "")
        if "display:none" in style or "visibility:hidden" in style:
            el.getparent().remove(el)
    for el in tree.xpath('//*[@aria-hidden="true"]'):
        parent = el.getparent()
        if parent is not None:
            parent.remove(el)

    # --- strip non-essential attributes ---
    if strip_attrs:
        for el in tree.iter():
            if not isinstance(el.tag, str):
                continue
            removable = [a for a in el.attrib if a not in KEEP_ATTRS]
            for a in removable:
                del el.attrib[a]
            # clean css-hash class names
            cls = el.get("class", "")
            if cls:
                cleaned = " ".join(c for c in cls.split() if not CSS_HASH_RE.match(c))
                if cleaned:
                    el.set("class", cleaned)
                else:
                    del el.attrib["class"]

    # --- remove data: URIs ---
    for el in tree.xpath("//*[@src]"):
        if (el.get("src") or "").startswith("data:"):
            del el.attrib["src"]

    # --- collapse wrapper divs ---
    if collapse_wrappers:
        _collapse_wrappers(tree)

    # --- remove empty elements ---
    _remove_empty(tree)

    # serialize
    result = etree.tostring(tree, encoding="unicode", method="html")

    # normalize whitespace: collapse runs of blank lines
    result = re.sub(r"\n\s*\n", "\n", result)

    # re-insert json-ld as plain text block
    if json_ld_blocks:
        ld_text = "\n".join(
            f'<script type="application/ld+json">{block}</script>'
            for block in json_ld_blocks
        )
        insert_point = result.find("</head>")
        if insert_point == -1:
            insert_point = result.find(">") + 1
        result = result[:insert_point] + "\n" + ld_text + "\n" + result[insert_point:]

    # --- optional: aggressive trimming to hit target size ---
    if target_kb and len(result) > target_kb * 1024:
        result = _aggressive_trim(result, target_kb)

    return result


def _collapse_wrappers(tree) -> None:
    """Unwrap <div>/<span> elements that wrap a single child with no meaningful text."""
    changed = True
    while changed:
        changed = False
        for el in tree.xpath("//div | //span"):
            children = list(el)
            if len(children) != 1:
                continue
            text = (el.text or "").strip()
            tail = (children[0].tail or "").strip()
            if text or tail:
                continue
            parent = el.getparent()
            if parent is None:
                continue
            child = children[0]
            child.tail = (child.tail or "") + (el.tail or "")
            idx = list(parent).index(el)
            parent.remove(el)
            parent.insert(idx, child)
            changed = True


def _remove_empty(tree) -> None:
    """Remove elements that have no text and no children."""
    SKIP = {"br", "hr", "img", "input", "meta", "link"}
    changed = True
    while changed:
        changed = False
        for el in tree.iter():
            if not isinstance(el.tag, str):
                continue
            if el.tag in SKIP:
                continue
            if (
                len(el) == 0
                and not (el.text or "").strip()
                and not (el.tail or "").strip()
            ):
                parent = el.getparent()
                if parent is not None:
                    parent.remove(el)
                    changed = True


def _aggressive_trim(html_str: str, target_kb: int) -> str:
    """Last-resort: strip remaining class/id attrs, then truncate from middle."""
    # re-parse and strip all class/id
    try:
        tree = lxml_html.fromstring(html_str)
        for el in tree.iter():
            if not isinstance(el.tag, str):
                continue
            for attr in ("class", "id"):
                if attr in el.attrib:
                    del el.attrib[attr]
        html_str = etree.tostring(tree, encoding="unicode", method="html")
    except Exception:
        pass

    if len(html_str) > target_kb * 1024:
        budget = target_kb * 1024
        head_size = budget * 2 // 3
        tail_size = budget - head_size - 50
        html_str = (
            html_str[:head_size]
            + "\n<!-- ... content trimmed for size ... -->\n"
            + html_str[-tail_size:]
        )
    return html_str


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python clean.py <file.html> [target_kb]")
        sys.exit(1)

    path = sys.argv[1]
    target = int(sys.argv[2]) if len(sys.argv) > 2 else None

    raw = open(path, encoding="utf-8").read()
    cleaned = clean_html(raw, target_kb=target)

    orig_kb = len(raw) / 1024
    clean_kb = len(cleaned) / 1024
    reduction = (1 - clean_kb / orig_kb) * 100

    print(f"Original:  {orig_kb:,.0f} KB", file=sys.stderr)
    print(f"Cleaned:   {clean_kb:,.0f} KB", file=sys.stderr)
    print(f"Reduction: {reduction:.0f}%", file=sys.stderr)

    print(cleaned)
