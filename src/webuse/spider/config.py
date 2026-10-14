from collections.abc import Callable
from typing import Any

from pydantic import ConfigDict, Field, ValidationError, field_validator

from ..agent import AgentLimits
from ..engine.policy import coerce_domains
from ..exceptions import ConfigError
from ..extract.schema import ExtractionRules
from ..models import FollowRule, WebuseModel


class ProjectConfig(WebuseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    name: str | None = None
    user_agent: str | None = None
    llm: dict[str, Any] = Field(default_factory=dict)
    robots_txt: bool | None = None
    concurrency: dict[str, Any] = Field(default_factory=dict)
    log: dict[str, Any] = Field(default_factory=dict)
    spiders: dict[str, Any] = Field(default_factory=dict)

    @field_validator("concurrency")
    @classmethod
    def validate_concurrency(cls, value: dict[str, Any]) -> dict[str, Any]:
        if value.keys() - {"limit", "per_domain"}:
            raise ValueError("concurrency supports only limit and per_domain")
        for key, limit in value.items():
            if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
                raise ValueError(f"concurrency.{key} must be a positive integer")
        return value


class SpiderConfig(WebuseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    name: str | None = None
    start_urls: Any = None
    goal: str | None = None
    limits: AgentLimits | None = None
    pages: Any = None
    max_depth: int | None = None
    max_requests: int | None = None
    concurrency: int | None = Field(default=None, ge=1)
    per_domain: int | None = Field(default=None, ge=1)
    dedupe: bool | None = None
    robots_txt: bool | None = None
    user_agent: str | None = None
    allowed_domains: Any = None
    request_defaults: dict[str, Any] | None = None
    same_domain: bool = False
    items: dict[str, Any] = Field(default_factory=dict)

    def pipeline_specs(self) -> Any:
        pipelines = self.items.get("pipelines")
        if isinstance(pipelines, dict):
            return pipelines.get("default")
        return pipelines


class EffectiveSpiderSettings(WebuseModel):
    name: str | None = None
    start_urls: Any = ()
    follow: Any = None
    extract: ExtractionRules | Callable[..., Any] | None = None
    max_depth: int = 0
    max_requests: int | None = None
    concurrency: int = Field(default=10, ge=1)
    per_domain: int | None = Field(default=None, ge=1)
    dedupe: bool = True
    robots_txt: bool = False
    user_agent: str = "webuse"
    allowed_domains: Any = None
    request_defaults: dict[str, Any] | None = None


class EffectiveAgenticSettings(EffectiveSpiderSettings):
    max_depth: int | None = None
    goal: str = Field(min_length=1)
    limits: AgentLimits

    @field_validator("goal")
    @classmethod
    def validate_goal(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("goal must not be blank")
        return value


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


def compile_pages_config(
    pages: Any, *, same_domain: bool = False
) -> tuple[list[FollowRule] | None, dict[str, Any] | None]:
    if pages is None:
        return None, None
    if not isinstance(pages, dict):
        raise ConfigError("pages must be a mapping")
    follow: list[FollowRule] = []
    extract: dict[str, Any] = {}
    for category, page in pages.items():
        category_name = str(category)
        if not isinstance(page, dict):
            raise ConfigError(f"pages.{category_name} must be a mapping")
        page_follow = page.get("follow")
        if page_follow is not None:
            rules = page_follow if isinstance(page_follow, list) else [page_follow]
            for rule in rules:
                if isinstance(rule, dict) and "source_category" in rule:
                    raise ConfigError(
                        f"pages.{category_name}.follow source category is implied by the page key"
                    )
                parsed = follow_rule_from_config(rule, same_domain=same_domain)
                parsed.source_category = category_name
                follow.append(parsed)
        if "extract" in page:
            page_extract = page["extract"]
            if not isinstance(page_extract, dict):
                raise ConfigError(f"pages.{category_name}.extract must be a mapping")
            extract[category_name] = page_extract
    return follow or None, extract or None


__all__ = ["EffectiveSpiderSettings", "ProjectConfig", "SpiderConfig"]
