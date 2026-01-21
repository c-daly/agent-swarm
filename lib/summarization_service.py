"""Service for summarizing large responses.

Stores full content in WorkflowStateService for later retrieval.
"""
import uuid
from typing import Any

from lib.workflow_state_service import WorkflowStateService


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
    
    def process(self, content: Any) -> Any:
        """Process content, summarizing if over threshold.
        
        Returns:
            Original content if under threshold, or
            {summary, content_id, full_available} if over threshold
        """
        content_str = str(content) if not isinstance(content, str) else content
        
        if len(content_str) <= self._threshold:
            return content
        
        content_id = self._generate_content_id()
        self._workflow_state.store_content(content_id, content)
        
        summary = self._generate_summary(content_str)
        
        return {
            "summary": summary,
            "content_id": content_id,
            "full_available": True,
        }
    
    def _generate_content_id(self) -> str:
        """Generate unique content ID."""
        return f"c{uuid.uuid4().hex[:12]}"
    
    def _generate_summary(self, content: str) -> str:
        """Generate summary of content.
        
        Currently truncates. Future: use LLM summarization.
        """
        return content[:self._threshold] + "..."
