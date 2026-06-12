from typing import Any

from pydantic import ConfigDict, Field

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
    concurrency: int | None = None
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
    concurrency: int = 10
    dedupe: bool = True
    robots_txt: bool = False
    user_agent: str = "webuse"
    allowed_domains: Any = None
    request_defaults: dict[str, Any] | None = None


__all__ = ["EffectiveSpiderSettings", "ProjectConfig", "SpiderConfig"]
