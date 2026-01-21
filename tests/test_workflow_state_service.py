"""Tests for WorkflowStateService."""
from lib.workflow_state_service import WorkflowStateService


def test_store_and_retrieve_content():
    """Can store content by ID and retrieve it."""
    service = WorkflowStateService()
    content_id = "test-123"
    content = {"data": "full response content here"}
    
    service.store_content(content_id, content)
    retrieved = service.get_content(content_id)
    
    assert retrieved == content


def test_get_content_removes_it():
    """Retrieving content removes it from storage (one-time access)."""
    service = WorkflowStateService()
    content_id = "test-456"
    content = {"data": "one-time content"}
    
    service.store_content(content_id, content)
    service.get_content(content_id)
    
    # Second retrieval should return None
    assert service.get_content(content_id) is None


def test_has_content():
    """Can check if content exists without retrieving."""
    service = WorkflowStateService()
    content_id = "test-789"
    
    assert not service.has_content(content_id)
    service.store_content(content_id, {"data": "test"})
    assert service.has_content(content_id)


def test_get_nonexistent_content_returns_none():
    """Getting non-existent content returns None."""
    service = WorkflowStateService()
    assert service.get_content("nonexistent") is None
