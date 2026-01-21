"""Tests for SummarizationService."""
from lib.summarization_service import SummarizationService
from lib.workflow_state_service import WorkflowStateService


def test_large_content_is_summarized():
    """Content over threshold returns summary with content_id."""
    workflow_state = WorkflowStateService()
    service = SummarizationService(workflow_state, threshold=100)
    
    large_content = "x" * 500  # Over threshold
    result = service.process(large_content)
    
    assert isinstance(result, dict)
    assert "summary" in result
    assert "content_id" in result
    assert result["full_available"] is True
    assert len(result["summary"]) < len(large_content)


def test_small_content_passes_through():
    """Content under threshold passes through unchanged."""
    workflow_state = WorkflowStateService()
    service = SummarizationService(workflow_state, threshold=100)
    
    small_content = "small response"
    result = service.process(small_content)
    
    assert result == small_content


def test_content_retrievable_via_workflow_state():
    """Full content stored in workflow state is retrievable."""
    workflow_state = WorkflowStateService()
    service = SummarizationService(workflow_state, threshold=100)
    
    large_content = "x" * 500
    result = service.process(large_content)
    
    content_id = result["content_id"]
    retrieved = workflow_state.get_content(content_id)
    
    assert retrieved == large_content


def test_dict_content_is_handled():
    """Dict content is properly serialized for size check."""
    workflow_state = WorkflowStateService()
    service = SummarizationService(workflow_state, threshold=50)
    
    large_dict = {"data": "x" * 100}
    result = service.process(large_dict)
    
    assert isinstance(result, dict)
    assert "content_id" in result


def test_content_id_is_unique():
    """Each call generates a unique content_id."""
    workflow_state = WorkflowStateService()
    service = SummarizationService(workflow_state, threshold=10)
    
    result1 = service.process("x" * 50)
    result2 = service.process("y" * 50)
    
    assert result1["content_id"] != result2["content_id"]
