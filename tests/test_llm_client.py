"""Tests for LLM client module."""
from unittest.mock import patch, MagicMock

from lib.llm_client import LLMClient


class TestLLMClientInit:
    """Tests for LLMClient initialization."""

    def test_init_openai_provider(self):
        """Test initialization with OpenAI provider."""
        with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}):
            client = LLMClient(provider="openai")
            assert client.provider == "openai"
            assert client.model == "gpt-4o-mini"

    def test_init_anthropic_provider(self):
        """Test initialization with Anthropic provider."""
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
            client = LLMClient(provider="anthropic")
            assert client.provider == "anthropic"
            assert client.model == "claude-3-haiku-20240307"

    def test_init_custom_model(self):
        """Test initialization with custom model."""
        with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}):
            client = LLMClient(provider="openai", model="gpt-4")
            assert client.model == "gpt-4"

    def test_init_no_api_key(self):
        """Test initialization without API key sets client to None."""
        with patch.dict("os.environ", {}, clear=True):
            client = LLMClient(provider="openai")
            assert client._client is None


class TestLLMClientCall:
    """Tests for LLMClient.call method."""

    def test_call_openai_success(self):
        """Test successful OpenAI call."""
        with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}):
            with patch("lib.llm_client.OpenAI") as mock_openai:
                mock_client = MagicMock()
                mock_response = MagicMock()
                mock_response.choices = [MagicMock(message=MagicMock(content="test response"))]
                mock_response.usage.prompt_tokens = 10
                mock_response.usage.completion_tokens = 5
                mock_client.chat.completions.create.return_value = mock_response
                mock_openai.return_value = mock_client

                client = LLMClient(provider="openai")
                result = client.call("test prompt")

                assert result["text"] == "test response"
                assert result["input_tokens"] == 10
                assert result["output_tokens"] == 5
                mock_client.chat.completions.create.assert_called_once()

    def test_call_anthropic_success(self):
        """Test successful Anthropic call."""
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
            with patch("lib.llm_client.Anthropic") as mock_anthropic:
                mock_client = MagicMock()
                mock_response = MagicMock()
                mock_response.content = [MagicMock(text="test response")]
                mock_response.usage.input_tokens = 15
                mock_response.usage.output_tokens = 8
                mock_client.messages.create.return_value = mock_response
                mock_anthropic.return_value = mock_client

                client = LLMClient(provider="anthropic")
                result = client.call("test prompt")

                assert result["text"] == "test response"
                assert result["input_tokens"] == 15
                assert result["output_tokens"] == 8
                mock_client.messages.create.assert_called_once()

    def test_call_no_client_returns_empty(self):
        """Test call returns empty string when no client."""
        with patch.dict("os.environ", {}, clear=True):
            client = LLMClient(provider="openai")
            result = client.call("test prompt")
            assert result == ""

    def test_call_exception_returns_empty(self):
        """Test call returns empty string on exception."""
        with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}):
            with patch("lib.llm_client.OpenAI") as mock_openai:
                mock_client = MagicMock()
                mock_client.chat.completions.create.side_effect = Exception("API error")
                mock_openai.return_value = mock_client

                client = LLMClient(provider="openai")
                result = client.call("test prompt")

                assert result == ""


class TestLLMClientSummarize:
    """Tests for LLMClient.summarize method."""

    def test_summarize_calls_call_with_prompt(self):
        """Test summarize uses call method with summarization prompt."""
        with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}):
            with patch("lib.llm_client.OpenAI") as mock_openai:
                mock_client = MagicMock()
                mock_response = MagicMock()
                mock_response.choices = [MagicMock(message=MagicMock(content="summary"))]
                mock_client.chat.completions.create.return_value = mock_response
                mock_openai.return_value = mock_client

                client = LLMClient(provider="openai")
                result = client.summarize("long content here")

                assert result == "summary"
                # Verify the prompt contains summarization instruction
                call_args = mock_client.chat.completions.create.call_args
                messages = call_args[1]["messages"]
                assert any("summarize" in msg["content"].lower() for msg in messages)

    def test_summarize_empty_content_returns_empty(self):
        """Test summarize with empty content returns empty string."""
        with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}):
            client = LLMClient(provider="openai")
            result = client.summarize("")
            assert result == ""
