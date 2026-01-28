"""Shared LLM client module for OpenAI and Anthropic providers."""
import os
from typing import Optional, Literal, TypedDict

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

try:
    from anthropic import Anthropic
except ImportError:
    Anthropic = None


class LLMResponse(TypedDict, total=False):
    """Response from an LLM call including token usage."""

    text: str
    input_tokens: int
    output_tokens: int


class LLMClient:
    """Unified LLM client supporting OpenAI and Anthropic providers."""

    DEFAULT_MODELS = {
        "openai": "gpt-4o-mini",
        "anthropic": "claude-3-haiku-20240307",
    }

    API_KEY_ENV_VARS = {
        "openai": "OPENAI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
    }

    def __init__(
        self,
        provider: Literal["openai", "anthropic"] = "openai",
        model: Optional[str] = None,
    ):
        """Initialize LLM client.

        Args:
            provider: The LLM provider to use ("openai" or "anthropic").
            model: Optional model override. Uses provider defaults if not specified.
        """
        self.provider = provider
        self.model = model or self.DEFAULT_MODELS.get(provider, "gpt-4o-mini")
        self._client = self._create_client()

    def _create_client(self):
        """Create the appropriate client based on provider."""
        api_key = os.environ.get(self.API_KEY_ENV_VARS.get(self.provider, ""))

        if not api_key:
            return None

        if self.provider == "openai" and OpenAI:
            return OpenAI(api_key=api_key)
        elif self.provider == "anthropic" and Anthropic:
            return Anthropic(api_key=api_key)

        return None

    def call(self, prompt: str) -> LLMResponse:
        """Make a general LLM call.

        Args:
            prompt: The prompt to send to the LLM.

        Returns:
            LLMResponse with text and token usage, or empty response on failure.
        """
        empty: LLMResponse = {"text": "", "input_tokens": 0, "output_tokens": 0}

        if not self._client:
            return empty

        try:
            if self.provider == "openai":
                response = self._client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "user", "content": prompt}],
                )
                return {
                    "text": response.choices[0].message.content or "",
                    "input_tokens": response.usage.prompt_tokens if response.usage else 0,
                    "output_tokens": response.usage.completion_tokens if response.usage else 0,
                }

            elif self.provider == "anthropic":
                response = self._client.messages.create(
                    model=self.model,
                    max_tokens=1024,
                    messages=[{"role": "user", "content": prompt}],
                )
                return {
                    "text": response.content[0].text if response.content else "",
                    "input_tokens": response.usage.input_tokens if response.usage else 0,
                    "output_tokens": response.usage.output_tokens if response.usage else 0,
                }

        except Exception:
            return empty

        return empty

    def summarize(self, content: str) -> LLMResponse:
        """Summarize the given content.

        Args:
            content: The content to summarize.

        Returns:
            LLMResponse with summary text and token usage.
        """
        if not content:
            return {"text": "", "input_tokens": 0, "output_tokens": 0}

        prompt = (
            "Please summarize the following content concisely, "
            "capturing the key points and main ideas:\n\n"
            f"{content}"
        )
        return self.call(prompt)
