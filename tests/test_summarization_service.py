"""Tests for SummarizationService."""
from lib.summarization_service import SummarizationService
from lib.workflow_state_service import WorkflowStateService


def test_large_content_is_summarized():
    """Content over threshold returns summary with content_id."""
    workflow_state = WorkflowStateService()
    service = SummarizationService(workflow_state, threshold=100)
    
    large_content = "x" * 500  # Over threshold
    result = service.process(large_content)
    
    # Check result structure
    assert isinstance(result, dict)
    assert "content" in result
    assert "was_summarized" in result
    assert "original_size" in result
    assert "summary_size" in result
    
    # Check stats
    assert result["was_summarized"] is True
    assert result["original_size"] == 500
    assert result["summary_size"] == 103  # threshold + "..."
    
    # Check content structure
    content = result["content"]
    assert isinstance(content, dict)
    assert "summary" in content
    assert "content_id" in content
    assert content["full_available"] is True
    assert len(content["summary"]) < len(large_content)


def test_small_content_passes_through():
    """Content under threshold passes through unchanged."""
    workflow_state = WorkflowStateService()
    service = SummarizationService(workflow_state, threshold=100)
    
    small_content = "small response"
    result = service.process(small_content)
    
    # Check result structure
    assert isinstance(result, dict)
    assert "content" in result
    assert "was_summarized" in result
    assert "original_size" in result
    assert "summary_size" in result
    
    # Check stats
    assert result["was_summarized"] is False
    assert result["original_size"] == 14
    assert result["summary_size"] is None
    
    # Check content
    assert result["content"] == small_content


def test_content_retrievable_via_workflow_state():
    """Full content stored in workflow state is retrievable."""
    workflow_state = WorkflowStateService()
    service = SummarizationService(workflow_state, threshold=100)
    
    large_content = "x" * 500
    result = service.process(large_content)
    
    content_id = result["content"]["content_id"]
    retrieved = workflow_state.get_content(content_id)
    
    assert retrieved == large_content


def test_dict_content_is_handled():
    """Dict content is properly serialized for size check."""
    workflow_state = WorkflowStateService()
    service = SummarizationService(workflow_state, threshold=50)
    
    large_dict = {"data": "x" * 100}
    result = service.process(large_dict)
    
    # Should be summarized because str(dict) is > 50 chars
    assert isinstance(result, dict)
    assert result["was_summarized"] is True
    assert "content_id" in result["content"]


def test_content_id_is_unique():
    """Each call generates a unique content_id."""
    workflow_state = WorkflowStateService()
    service = SummarizationService(workflow_state, threshold=10)
    
    result1 = service.process("x" * 50)
    result2 = service.process("y" * 50)
    
    assert result1["content"]["content_id"] != result2["content"]["content_id"]


def test_summarization_stats_accuracy():
    """Summarization stats are accurate."""
    workflow_state = WorkflowStateService()
    service = SummarizationService(workflow_state, threshold=100)
    
    # Test with content that will be summarized
    content = "a" * 200
    result = service.process(content)
    
    assert result["was_summarized"] is True
    assert result["original_size"] == 200
    assert result["summary_size"] == 103  # 100 + "..."
    
    # Test with content that won't be summarized
    small_content = "test"
    result2 = service.process(small_content)
    
    assert result2["was_summarized"] is False
    assert result2["original_size"] == 4
    assert result2["summary_size"] is None
