from typing import Any

from pydantic import ConfigDict, Field, field_validator

from ..models import WebuseModel


class ProjectConfig(WebuseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    name: str | None = None
    user_agent: str | None = None
    llm: dict[str, Any] = Field(default_factory=dict)
    robots_txt: bool | None = None
    concurrency: dict[str, Any] = Field(default_factory=dict)
    items: dict[str, Any] = Field(default_factory=dict)
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

    def pipeline_specs(self) -> Any:
        pipelines = self.items.get("pipelines")
        if isinstance(pipelines, dict):
            return pipelines.get("default")
        return pipelines


class SpiderConfig(WebuseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    name: str | None = None
    start_urls: Any = None
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


class EffectiveSpiderSettings(WebuseModel):
    name: str | None = None
    start_urls: Any = ()
    follow: Any = None
    extract: Any = None
    max_depth: int = 0
    max_requests: int | None = None
    concurrency: int = Field(default=10, ge=1)
    per_domain: int | None = Field(default=None, ge=1)
    dedupe: bool = True
    robots_txt: bool = False
    user_agent: str = "webuse"
    allowed_domains: Any = None
    request_defaults: dict[str, Any] | None = None


__all__ = ["EffectiveSpiderSettings", "ProjectConfig", "SpiderConfig"]
