"""Service for summarizing large responses.

Stores full content in WorkflowStateService for later retrieval.
"""
import uuid
from typing import Any, TypedDict

from lib.llm_client import LLMClient
from lib.workflow_state_service import WorkflowStateService


class SummarizationResult(TypedDict, total=False):
    """Result from summarization processing.

    Contains both the processed content and statistics.
    """
    content: Any  # The actual content to return (original or summary dict)
    was_summarized: bool
    original_size: int
    summary_size: int | None  # None if not summarized
    input_tokens: int | None  # Tokens in original content (from LLM)
    output_tokens: int | None  # Tokens in summary (from LLM)


class SummarizationService:
    """Handles response summarization and content storage.
    
    Responsibilities:
    - Determine if response needs summarization (size threshold)
    - Generate summaries for large responses
    - Store full content via WorkflowStateService
    """
    
    def __init__(
        self, 
        workflow_state: WorkflowStateService, 
        threshold: int = 2000,
        llm_client: LLMClient | None = None,
    ) -> None:
        self._workflow_state = workflow_state
        self._threshold = threshold
        self._llm_client = llm_client
    
    def process(self, content: Any) -> SummarizationResult:
        """Process content, summarizing if over threshold.

        Returns:
            SummarizationResult with content and statistics
        """
        content_str = str(content) if not isinstance(content, str) else content
        original_size = len(content_str)

        if original_size <= self._threshold:
            return {
                "content": content,
                "was_summarized": False,
                "original_size": original_size,
                "summary_size": None,
                "input_tokens": None,
                "output_tokens": None,
            }

        content_id = self._generate_content_id()
        self._workflow_state.store_content(content_id, content)

        summary_text, input_tokens, output_tokens = self._generate_summary(content_str)
        summary_dict = {
            "summary": summary_text,
            "content_id": content_id,
            "full_available": True,
        }

        return {
            "content": summary_dict,
            "was_summarized": True,
            "original_size": original_size,
            "summary_size": len(summary_text),
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
        }
    
    def _generate_content_id(self) -> str:
        """Generate unique content ID."""
        return f"c{uuid.uuid4().hex[:12]}"
    
    def _generate_summary(self, content: str) -> tuple[str, int | None, int | None]:
        """Generate summary of content.

        Uses LLM summarization if available, otherwise truncates.

        Returns:
            Tuple of (summary_text, input_tokens, output_tokens)
        """
        if self._llm_client:
            response = self._llm_client.summarize(content)
            if response["text"]:
                return (
                    response["text"],
                    response.get("input_tokens"),
                    response.get("output_tokens"),
                )

        # Fallback to truncation (no token counts available)
        return content[:self._threshold] + "...", None, None
