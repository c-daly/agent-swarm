#!/usr/bin/env python3
"""Tests for the LLM service."""

from unittest.mock import MagicMock, patch

import pytest

from lib.llm import LLMService


class TestProviderDetection:
    @patch.dict("os.environ", {}, clear=True)
    @patch("lib.llm.Anthropic", None)
    @patch("lib.llm.OpenAI", None)
    def test_no_providers_falls_back_to_none(self):
        svc = LLMService()
        assert svc.provider == "none"

    @patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-test"}, clear=True)
    def test_auto_prefers_anthropic(self):
        if LLMService._make_anthropic() is None:
            pytest.skip("anthropic package not installed")
        svc = LLMService()
        assert svc.provider == "anthropic"

    def test_explicit_none_provider(self):
        svc = LLMService(provider="none")
        assert svc.provider == "none"
        assert svc._client is None

    @patch.dict("os.environ", {}, clear=True)
    def test_explicit_anthropic_without_key(self):
        svc = LLMService(provider="anthropic")
        assert svc.provider == "anthropic"
        assert svc._client is None

    @patch.dict("os.environ", {}, clear=True)
    def test_explicit_openai_without_key(self):
        svc = LLMService(provider="openai")
        assert svc.provider == "openai"
        assert svc._client is None


class TestSummarize:
    def _make_svc(self, provider="none"):
        return LLMService(provider=provider)

    def test_empty_content(self):
        svc = self._make_svc()
        assert svc.summarize("") == ""

    def test_short_content_returned_as_is(self):
        svc = self._make_svc()
        result = svc.summarize("hello world", max_length=2000)
        assert result == "hello world"

    def test_truncation_fallback(self):
        svc = self._make_svc()
        content = "x" * 5000
        result = svc.summarize(content, max_length=200)
        assert len(result) <= 200 + 60  # suffix is ~55 chars
        assert "truncated" in result
        assert "content_id" in result

    def test_truncation_preserves_beginning(self):
        svc = self._make_svc()
        content = "IMPORTANT DATA " + "x" * 5000
        result = svc.summarize(content, max_length=200)
        assert result.startswith("IMPORTANT DATA")


class TestSummarizeWithMockAPI:
    def test_anthropic_summarize(self):
        svc = LLMService(provider="none")
        svc._provider = "anthropic"

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="Summary of the content")]
        mock_client.messages.create.return_value = mock_response
        svc._client = mock_client

        result = svc.summarize("x" * 5000, max_length=2000)
        assert result == "Summary of the content"
        mock_client.messages.create.assert_called_once()

    def test_openai_summarize(self):
        svc = LLMService(provider="none")
        svc._provider = "openai"

        mock_client = MagicMock()
        mock_choice = MagicMock()
        mock_choice.message.content = "OpenAI summary"
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_client.chat.completions.create.return_value = mock_response
        svc._client = mock_client

        result = svc.summarize("x" * 5000, max_length=2000)
        assert result == "OpenAI summary"
        mock_client.chat.completions.create.assert_called_once()

    def test_api_failure_falls_back_to_truncation(self):
        svc = LLMService(provider="none")
        svc._provider = "anthropic"

        mock_client = MagicMock()
        mock_client.messages.create.side_effect = RuntimeError("API down")
        svc._client = mock_client

        result = svc.summarize("x" * 5000, max_length=200)
        assert "truncated" in result

    def test_never_raises(self):
        svc = LLMService(provider="none")
        svc._provider = "anthropic"

        mock_client = MagicMock()
        mock_client.messages.create.side_effect = Exception("catastrophic")
        svc._client = mock_client

        # Should not raise, should return truncated string
        result = svc.summarize("x" * 5000)
        assert isinstance(result, str)
        assert len(result) > 0
