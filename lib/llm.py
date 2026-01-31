#!/usr/bin/env python3
"""LLM service for the daemon.

Currently supports summarization. Designed to grow (embeddings,
classification) without changing the Controller interface.
"""

from __future__ import annotations

import logging
import os

log = logging.getLogger(__name__)

try:
    from anthropic import Anthropic
except ImportError:
    Anthropic = None

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

_SUMMARIZE_PROMPT = (
    "Summarize the following content concisely, preserving key information "
    "like file paths, function names, error messages, and data structures. "
    "Keep under {max_length} characters.\n\nContent:\n{content}"
)

_ANTHROPIC_MODEL = "claude-haiku-4-20250414"
_OPENAI_MODEL = "gpt-4o-mini"


class LLMService:
    """LLM capabilities abstraction.

    Provider resolution (when provider="auto"):
        1. Anthropic if ANTHROPIC_API_KEY is set
        2. OpenAI if OPENAI_API_KEY is set
        3. Truncation fallback ("none")
    """

    def __init__(self, provider: str = "auto") -> None:
        self._provider: str
        self._client: object | None = None

        if provider == "auto":
            self._provider, self._client = self._auto_detect()
        elif provider == "anthropic":
            self._provider = "anthropic"
            self._client = self._make_anthropic()
        elif provider == "openai":
            self._provider = "openai"
            self._client = self._make_openai()
        else:
            self._provider = "none"
            self._client = None

    @property
    def provider(self) -> str:
        """Resolved provider name."""
        return self._provider

    def summarize(self, content: str, max_length: int = 2000) -> str:
        """Generate a concise summary of content.

        Never raises — always returns a string. Falls back to
        truncation if no API is available or the call fails.
        """
        if not content:
            return ""

        if len(content) <= max_length:
            return content

        if self._provider != "none" and self._client is not None:
            try:
                return self._call_api(content, max_length)
            except Exception as e:
                log.warning("LLM summarization failed, using truncation: %s", e)

        return self._truncate(content, max_length)

    def _call_api(self, content: str, max_length: int) -> str:
        """Call the LLM API for summarization."""
        prompt = _SUMMARIZE_PROMPT.format(content=content, max_length=max_length)
        max_tokens = max(100, max_length // 3)

        if self._provider == "anthropic":
            response = self._client.messages.create(
                model=_ANTHROPIC_MODEL,
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )
            return response.content[0].text if response.content else self._truncate(content, max_length)

        if self._provider == "openai":
            response = self._client.chat.completions.create(
                model=_OPENAI_MODEL,
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )
            return response.choices[0].message.content or self._truncate(content, max_length)

        return self._truncate(content, max_length)

    @staticmethod
    def _truncate(content: str, max_length: int) -> str:
        """Truncation fallback."""
        suffix = "\n\n... [truncated, full content available via content_id]"
        return content[: max_length - len(suffix)] + suffix

    @staticmethod
    def _auto_detect() -> tuple[str, object | None]:
        """Try Anthropic first, then OpenAI, then none."""
        client = LLMService._make_anthropic()
        if client is not None:
            return "anthropic", client
        client = LLMService._make_openai()
        if client is not None:
            return "openai", client
        return "none", None

    @staticmethod
    def _make_anthropic() -> object | None:
        if Anthropic is None:
            return None
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            return None
        return Anthropic(api_key=key)

    @staticmethod
    def _make_openai() -> object | None:
        if OpenAI is None:
            return None
        key = os.environ.get("OPENAI_API_KEY")
        if not key:
            return None
        return OpenAI(api_key=key)
