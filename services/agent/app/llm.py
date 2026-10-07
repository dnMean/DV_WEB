"""LLM client interface + OpenAI implementation (Chat Completions API)."""
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx
import openai
from openai import OpenAI

from app.config import Settings

logger = logging.getLogger(__name__)


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: str  # raw JSON string produced by the model


@dataclass
class LLMResponse:
    content: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0

    def assistant_message(self) -> dict[str, Any]:
        msg: dict[str, Any] = {"role": "assistant", "content": self.content}
        if self.tool_calls:
            msg["tool_calls"] = [
                {"id": tc.id, "type": "function", "function": {"name": tc.name, "arguments": tc.arguments}}
                for tc in self.tool_calls
            ]
        return msg


class LLMError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class LLMClient(Protocol):
    def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None) -> LLMResponse: ...


class OpenAIClient:
    def __init__(self, settings: Settings, http_client: httpx.Client | None = None):
        self._client = OpenAI(
            api_key=settings.OPENAI_API_KEY or "missing",
            base_url=settings.OPENAI_BASE_URL,
            timeout=settings.LLM_TIMEOUT_SECONDS,
            max_retries=0,  # retries handled below so they are visible in logs
            http_client=http_client,
        )
        self._model = settings.OPENAI_MODEL
        self._retries = settings.LLM_RETRIES
        self._backoff = settings.LLM_BACKOFF_SECONDS

    def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None) -> LLMResponse:
        kwargs: dict[str, Any] = {"model": self._model, "messages": messages, "temperature": 0}
        if tools:
            kwargs.update(tools=tools, tool_choice="auto")

        for attempt in range(self._retries + 1):
            try:
                resp = self._client.chat.completions.create(**kwargs)
                break
            except openai.AuthenticationError as exc:
                raise LLMError("llm_auth", "OpenAI từ chối API key (kiểm tra OPENAI_API_KEY)") from exc
            except (openai.RateLimitError, openai.InternalServerError, openai.APIConnectionError) as exc:
                if attempt == self._retries:
                    raise LLMError("llm_unavailable", f"OpenAI không phản hồi: {type(exc).__name__}") from exc
                delay = self._backoff * 2 ** attempt
                logger.warning("LLM call failed (%s), retry %s in %.1fs", type(exc).__name__, attempt + 1, delay)
                time.sleep(delay)
            except openai.APIStatusError as exc:
                raise LLMError("llm_error", f"OpenAI trả lỗi {exc.status_code}") from exc

        msg = resp.choices[0].message
        usage = resp.usage
        return LLMResponse(
            content=msg.content,
            tool_calls=[
                ToolCall(id=tc.id, name=tc.function.name, arguments=tc.function.arguments or "{}")
                for tc in (msg.tool_calls or [])
            ],
            prompt_tokens=usage.prompt_tokens if usage else 0,
            completion_tokens=usage.completion_tokens if usage else 0,
        )
