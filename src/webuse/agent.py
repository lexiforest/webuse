"""Public contracts for bounded, tool-driven crawler runs."""

from dataclasses import dataclass
from typing import Any, Callable, Protocol

from pydantic import BaseModel, ConfigDict, Field


class AgentLimits(BaseModel):
    """Total token budget, optional execution caps, and context paging settings."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    max_requests: int | None = Field(default=None, gt=0)
    max_turns: int | None = Field(default=None, gt=0)
    max_tokens: int = Field(gt=0)
    max_seconds: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    max_output_tokens: int | None = Field(default=None, gt=0)
    max_page_bytes: int | None = Field(default=None, gt=0)
    observation_chars: int = Field(default=8000, ge=256)
    memory_chars: int = Field(default=4000, ge=256)


class AgentRunInfo(BaseModel):
    turns: int = 0
    tokens: int = 0
    completion_reason: str | None = None
    drafts: dict[str, dict[str, Any]] = Field(default_factory=dict)
    sources: dict[str, dict[str, list[str]]] = Field(default_factory=dict)
    emitted_ids: list[str] = Field(default_factory=list)
    memory: dict[str, str] = Field(default_factory=dict)
    progress: str | None = None


class AgentModel(Protocol):
    async def complete(
        self,
        *,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_tokens: int | None,
    ) -> dict[str, Any]:
        """Return usage.total_tokens; max_tokens=None uses the provider's default."""
        ...


@dataclass(frozen=True)
class AgentTool:
    """A trusted project tool. The handler receives validated Pydantic arguments.

    Async handlers are recommended for cancellable I/O. Additional tools are
    trusted Python code and must account for any extra network/model usage.
    """

    name: str
    description: str
    arguments: type[BaseModel]
    handler: Callable[[Any], Any]

    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.arguments.model_json_schema(),
            },
        }


class AgentModelError(Exception):
    def __init__(self, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable
