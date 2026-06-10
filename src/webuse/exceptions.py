class WebuseError(Exception):
    """Base exception for the package."""


class SmartSelectorError(WebuseError):
    """Raised when a smart selector cannot be resolved confidently."""


class ConfigError(WebuseError):
    """Raised when a webuse config file or config value is invalid."""


class SpiderError(WebuseError):
    """Raised when a spider definition or spider target is invalid."""


class PipelineError(WebuseError):
    """Raised when item pipeline configuration or execution is invalid."""


class PipelineStateError(PipelineError):
    """Raised when a pipeline is used before it is opened."""


class SignalError(WebuseError):
    """Raised when signal dispatch cannot complete."""


class DropItem(PipelineError):
    """Raised by pipelines to drop an item from the result."""

    def __init__(self, message: str = "", log_level: str | None = None):
        super().__init__(message)
        self.log_level = log_level


class IgnoreRequest(WebuseError):
    """Raised to skip processing a request or response."""


class CloseSpider(WebuseError):
    """Raised from spider callbacks to request that the crawl stops."""

    def __init__(self, reason: str = "cancelled"):
        super().__init__(reason)
        self.reason = reason


class NotConfigured(ConfigError):
    """Raised by components that are disabled or missing required configuration."""


class NotSupported(WebuseError):
    """Raised when a feature or operation is not supported."""
