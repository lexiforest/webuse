import json

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


def generate_xpath(element: Element) -> str:
    attrs = element.attrs
    element_id = attrs.get("id")
    if element_id:
        return f"//*[@id='{element_id}']"
    classes = attrs.get("class", "").split()
    if classes:
        predicates = " and ".join(
            f"contains(concat(' ', normalize-space(@class), ' '), ' {value} ')"
            for value in classes[:3]
        )
        return f"//{element.tag}[{predicates}]"
    href = attrs.get("href")
    if href:
        return f"//{element.tag}[@href={json.dumps(href)}]"
    return f"//{element.tag}"
