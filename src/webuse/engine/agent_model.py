"""Small OpenAI-compatible tool-call transport using curl_cffi."""

from typing import Any

from curl_cffi.requests import AsyncSession

from ..agent import AgentModelError
from ..llm import OpenAISettings


class CurlAgentModel:
    def __init__(self, settings: OpenAISettings):
        if not settings.model:
            raise ValueError("AgenticSpider requires a configured model")
        self.settings = settings
        # Separate from the crawl session: never send model credentials to pages.
        self.session = AsyncSession()

    async def complete(self, *, messages, tools, max_tokens) -> dict[str, Any]:
        headers = {}
        if self.settings.api_key:
            headers["Authorization"] = f"Bearer {self.settings.api_key}"
        payload = {
            "model": self.settings.model,
            "messages": messages,
            "tools": tools,
            "tool_choice": "auto",
            "stream": False,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens

        try:
            response = await self.session.post(
                f"{(self.settings.base_url or 'https://api.openai.com/v1').rstrip('/')}/chat/completions",
                headers=headers,
                json=payload,
                timeout=None,
                allow_redirects=False,
            )
        except Exception as exc:
            raise AgentModelError("Model connection failed", retryable=True) from exc
        if not 200 <= response.status_code < 300:
            raise AgentModelError(
                f"Model returned HTTP {response.status_code}",
                retryable=response.status_code == 429 or response.status_code >= 500,
            )
        try:
            return response.json()
        except ValueError as exc:
            raise AgentModelError("Model returned invalid JSON") from exc

    async def close(self):
        await self.session.close()
