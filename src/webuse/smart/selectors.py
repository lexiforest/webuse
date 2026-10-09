from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..parser import Element


def generate_selector(element: Element) -> str:
    attrs = element.attrs
    element_id = attrs.get("id")
    if element_id:
        return f"#{element_id}"
    classes = attrs.get("class", "").split()
    if classes:
        return f"{element.tag}." + ".".join(classes[:3])
    return element.tag
