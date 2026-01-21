"""Service for summarizing large responses.

Stores full content in WorkflowStateService for later retrieval.
"""
import uuid
from typing import Any, TypedDict

from lib.workflow_state_service import WorkflowStateService


class SummarizationResult(TypedDict, total=False):
    """Result from summarization processing.

    Contains both the processed content and statistics.
    """
    content: Any  # The actual content to return (original or summary dict)
    was_summarized: bool
    original_size: int
    summary_size: int | None  # None if not summarized


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
        threshold: int = 2000
    ) -> None:
        self._workflow_state = workflow_state
        self._threshold = threshold
    
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
            }
        
        content_id = self._generate_content_id()
        self._workflow_state.store_content(content_id, content)
        
        summary = self._generate_summary(content_str)
        summary_dict = {
            "summary": summary,
            "content_id": content_id,
            "full_available": True,
        }
        
        return {
            "content": summary_dict,
            "was_summarized": True,
            "original_size": original_size,
            "summary_size": len(summary),
        }
    
    def _generate_content_id(self) -> str:
        """Generate unique content ID."""
        return f"c{uuid.uuid4().hex[:12]}"
    
    def _generate_summary(self, content: str) -> str:
        """Generate summary of content.
        
        Currently truncates. Future: use LLM summarization.
        """
        return content[:self._threshold] + "..."
