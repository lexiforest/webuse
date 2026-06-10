import re

from ..exceptions import SmartSelectorError
from ..models import SmartSelectorRecord
from ..parser import Document, Element
from .resolver import LlmSmartResolver, SmartResolver
from .selectors import generate_selector, generate_xpath
from .store import SmartSelectorStore, prompt_key


def _tokenize(prompt: str) -> set[str]:
    return {
        token for token in re.findall(r"[a-z0-9]+", prompt.lower()) if len(token) > 1
    }


def _score(prompt_tokens: set[str], element: Element) -> float:
    haystack = " ".join(
        [
            element.tag,
            element.text(),
            " ".join(f"{key} {value}" for key, value in element.attrs.items()),
        ]
    ).lower()
    score = sum(2.0 for token in prompt_tokens if token in haystack)
    if element.attr("aria-label"):
        score += 1.5
    if element.attr("href"):
        score += 0.5
    if len(element.text()) > 120:
        score -= 0.5
    return score


def resolve_smart(
    document: Document,
    prompt: str,
    *,
    key: str | None = None,
    store: SmartSelectorStore | None = None,
    use_llm: bool = False,
    resolver: SmartResolver | None = None,
) -> Element:
    store = store or SmartSelectorStore()
    record_key = prompt_key(prompt, key)
    record = store.get(record_key)
    candidates = list(document.iter_elements())
    if record:
        for selector in record.selectors:
            match = document.css_first(selector)
            if match:
                return match
        for selector in record.xpath_selectors:
            match = document.xpath_first(selector)
            if match:
                return match

    prompt_tokens = _tokenize(prompt)
    ranked = sorted(
        candidates, key=lambda item: _score(prompt_tokens, item), reverse=True
    )
    match = ranked[0] if ranked and _score(prompt_tokens, ranked[0]) > 0 else None

    if match is None and use_llm:
        resolver = resolver or LlmSmartResolver()
        match = resolver.resolve(prompt, document, ranked[:20])

    if match is None:
        raise SmartSelectorError(
            f"Unable to resolve smart selector for prompt: {prompt!r}"
        )

    store.save(_record_for_match(record_key, prompt, match))
    return match


def _record_for_match(
    record_key: str, prompt: str, match: Element
) -> SmartSelectorRecord:
    return SmartSelectorRecord(
        key=record_key,
        prompt=prompt,
        selectors=[generate_selector(match)],
        xpath_selectors=[generate_xpath(match)],
    )
