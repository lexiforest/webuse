import warnings
from typing import Any, Callable

from pydantic import BaseModel, ConfigDict, Field


ExtractCallback = Callable[[Any], Any]
FollowCallback = Callable[[Any], Any]
ErrorCallback = Callable[[Exception, "CrawlRequest"], None]


class WebuseModel(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)


warnings.filterwarnings(
    "ignore",
    message='Field name "json" in "RequestOptions" shadows an attribute in parent "WebuseModel"',
    category=UserWarning,
)


class RequestOptions(WebuseModel):
    method: str = "GET"
    headers: dict[str, str] | None = None
    cookies: dict[str, str] | None = None
    params: dict[str, Any] | None = None
    data: Any = None
    json: Any = None
    files: Any = None
    auth: tuple[str, str] | None = None
    timeout: float | tuple[float, float] | None = None
    follow_redirects: bool | None = None
    max_redirects: int | None = None
    proxy: str | None = None
    proxies: dict[str, str] | None = None
    proxy_auth: tuple[str, str] | None = None
    verify: bool | str | None = None
    impersonate: str | list[str] | None = "chrome"
    ja3: str | None = None
    akamai: str | None = None
    extra_fp: dict[str, Any] | None = None
    default_headers: bool | None = None
    http_version: Any = None
    interface: str | None = None
    cert: Any = None
    referer: str | None = None
    extra_kwargs: dict[str, Any] = Field(default_factory=dict)

    def to_request_kwargs(self) -> dict[str, Any]:
        values = {
            "headers": self.headers,
            "cookies": self.cookies,
            "params": self.params,
            "data": self.data,
            "json": self.json,
            "files": self.files,
            "auth": self.auth,
            "timeout": self.timeout,
            "follow_redirects": self.follow_redirects,
            "allow_redirects": self.follow_redirects,
            "max_redirects": self.max_redirects,
            "proxy": self.proxy,
            "proxies": self.proxies,
            "proxy_auth": self.proxy_auth,
            "verify": self.verify,
            "impersonate": self.impersonate,
            "ja3": self.ja3,
            "akamai": self.akamai,
            "extra_fp": self.extra_fp,
            "default_headers": self.default_headers,
            "http_version": self.http_version,
            "interface": self.interface,
            "cert": self.cert,
            "referer": self.referer,
        }
        return {
            key: value
            for key, value in {**values, **self.extra_kwargs}.items()
            if value is not None
        }


class CrawlRequest(WebuseModel):
    url: str
    method: str = "GET"
    options: RequestOptions = Field(default_factory=RequestOptions)
    category: str | None = None
    depth: int = 0
    parent_url: str | None = None
    meta: dict[str, Any] = Field(default_factory=dict)


class FollowRule(WebuseModel):
    css: str | None = None
    xpath: str | None = None
    attr: str = "href"
    include: str | None = None
    exclude: str | None = None
    same_domain: bool = False
    allowed_domains: set[str] | None = None
    max_depth: int | None = None
    predicate: Callable[[str, Any], bool] | None = None


class SmartSelectorRecord(WebuseModel):
    key: str
    prompt: str
    selectors: list[str] = Field(default_factory=list)
    xpath_selectors: list[str] = Field(default_factory=list)


class CrawlStats(WebuseModel):
    queued: int = 0
    fetched: int = 0
    extracted_items: int = 0
    followed_links: int = 0
    skipped_duplicates: int = 0
    skipped_rules: int = 0
    skipped_robots: int = 0
    skipped_ignored: int = 0
    errors: int = 0


class CrawlResult(WebuseModel):
    items: list[Any] = Field(default_factory=list)
    pages: list[Any] = Field(default_factory=list)
    errors: list[dict[str, Any]] = Field(default_factory=list)
    stats: CrawlStats = Field(default_factory=CrawlStats)
    visited: set[str] = Field(default_factory=set)
    close_reason: str | None = None
