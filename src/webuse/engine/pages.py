"""Compile page routing, follow rules, and extraction for spiders and engines."""

import re
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from ..exceptions import ConfigError
from ..extract.schema import ExtractionRules, compile_extraction
from ..models import FollowRule
from .policy import PagePattern, coerce_domains


@dataclass
class CompiledPages:
    follow: list[FollowRule] | None = None
    extract: ExtractionRules | None = None
    patterns: list[PagePattern] = field(default_factory=list)


def follow_rule_from_config(value: Any, *, same_domain: bool = False) -> FollowRule:
    if isinstance(value, FollowRule):
        return value
    if isinstance(value, str):
        return FollowRule(css=value, same_domain=same_domain)
    if not isinstance(value, dict):
        raise ConfigError(f"Unsupported follow rule: {value!r}")
    options = dict(value)
    options.setdefault("same_domain", same_domain)
    if "allowed_domains" in options:
        options["allowed_domains"] = coerce_domains(options["allowed_domains"])
    try:
        return FollowRule.model_validate(options)
    except ValidationError as exc:
        raise ConfigError(f"Invalid follow rule: {exc}") from exc


def _patterns(value: Any, path: str) -> tuple[re.Pattern, ...]:
    if not isinstance(value, list):
        raise ConfigError(f"{path} must be a list of regex strings")
    patterns = []
    for pattern in value:
        if not isinstance(pattern, str) or not pattern.strip():
            raise ConfigError(f"{path} requires nonempty regex strings")
        try:
            patterns.append(re.compile(pattern))
        except re.error as exc:
            raise ConfigError(f"Invalid {path}: {exc}") from exc
    return tuple(patterns)


def compile_pages_config(pages: Any, *, same_domain: bool = False) -> CompiledPages:
    if isinstance(pages, CompiledPages):
        return pages
    result = CompiledPages()
    if pages is None:
        return result
    if not isinstance(pages, dict):
        raise ConfigError("pages must be a mapping")
    extract: dict[str, Any] = {}
    for page_type, page in pages.items():
        if not isinstance(page_type, str) or not page_type.strip():
            raise ConfigError("pages requires nonempty page_type names")
        path = f"pages.{page_type}"
        if not isinstance(page, dict):
            raise ConfigError(f"{path} must be a mapping")
        unknown = page.keys() - {
            "url_patterns",
            "exclude_patterns",
            "follow",
            "extract",
        }
        if unknown:
            raise ConfigError(f"Unknown {path} options: {', '.join(map(str, unknown))}")
        include = _patterns(page.get("url_patterns", []), f"{path}.url_patterns")
        exclude = _patterns(
            page.get("exclude_patterns", []), f"{path}.exclude_patterns"
        )
        if page_type == "*" and (include or exclude):
            raise ConfigError("pages.* is a fallback and cannot have URL patterns")
        if include or exclude:
            result.patterns.append(PagePattern(page_type, include, exclude))
        page_follow = page.get("follow")
        if page_follow is not None:
            if result.follow is None:
                result.follow = []
            rules = page_follow if isinstance(page_follow, list) else [page_follow]
            for rule in rules:
                if isinstance(rule, dict) and "source_page_type" in rule:
                    raise ConfigError(
                        f"{path}.follow source page_type is implied by the page key"
                    )
                parsed = follow_rule_from_config(rule, same_domain=same_domain)
                result.follow.append(
                    parsed.model_copy(update={"source_page_type": page_type})
                )
        if "extract" in page:
            if not isinstance(page["extract"], dict):
                raise ConfigError(f"{path}.extract must be a mapping")
            extract[page_type] = page["extract"]
    result.extract = compile_extraction(extract) if extract else None
    return result
