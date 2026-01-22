"""Service for managing workflow state and content_id storage.

Stores full content for two-step retrieval pattern where:
1. Router returns summary + content_id
2. Client requests full content via content_id
3. Full content is returned and removed from storage
"""
from typing import Any


class WorkflowStateService:
    """Manages operational data for hooks and agents.
    
    Responsibilities:
    - Store/retrieve content_id -> full content mapping
    - One-time retrieval (content removed after access)
    """
    
    def __init__(self) -> None:
        self._content_store: dict[str, Any] = {}
    
    def store_content(self, content_id: str, content: Any) -> None:
        """Store full content for later retrieval."""
        self._content_store[content_id] = content
    
    def get_content(self, content_id: str) -> Any | None:
        """Retrieve and remove content by ID.
        
        Returns None if content_id not found.
        Content is removed after retrieval (one-time access).
        """
        return self._content_store.pop(content_id, None)
    
    def has_content(self, content_id: str) -> bool:
        """Check if content exists for given ID."""
        return content_id in self._content_store
