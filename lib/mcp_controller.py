"""Thin controller that orchestrates MCP tool calls.

Wires together:
- RoutingService: routes calls to backend servers
- SummarizationService: summarizes large responses
- TelemetryService: records events
- WorkflowStateService: manages content_id storage
"""
from typing import Any, Optional

from lib.summarization_service import SummarizationService
from lib.telemetry_service import TelemetryService
from lib.workflow_state_service import WorkflowStateService


class MCPController:
    """Thin orchestration layer for MCP tool calls.
    
    No business logic - just wiring services together.
    """
    
    def __init__(
        self,
        routing_service: Optional[Any] = None,
        summarization_service: Optional[SummarizationService] = None,
        telemetry_service: Optional[TelemetryService] = None,
        workflow_state_service: Optional[WorkflowStateService] = None,
    ) -> None:
        self._workflow_state = workflow_state_service or WorkflowStateService()
        self._routing = routing_service  # May be None until RoutingService exists
        self._summarization = summarization_service or SummarizationService(self._workflow_state)
        self._telemetry = telemetry_service
    
    def handle_call(self, tool: str, args: dict) -> Any:
        """Handle an MCP tool call.
        
        Flow: route -> summarize -> record -> return
        """
        if self._routing is None:
            return {"error": "RoutingService not configured"}
        
        # Route to backend
        result = self._routing.route(tool, args)
        
        # Summarize if needed and get stats
        processed_result = self._summarization.process(result)
        
        # Record telemetry (if service available)
        if self._telemetry:
            self._telemetry.insert_event({
                "tool": tool,
                "timestamp": "now",  # Will be properly formatted
                "session_id": "controller",
                "backend": tool.split("__")[0] if "__" in tool else "unknown",
                "duration_ms": 0,
                "status": "success",
                "was_summarized": processed_result["was_summarized"],
                "original_size": processed_result["original_size"],
                "summary_size": processed_result["summary_size"],
            })
            
            # Track content creation if summarization occurred
            if processed_result["was_summarized"]:
                content = processed_result["content"]
                if isinstance(content, dict) and "content_id" in content:
                    self._telemetry.record_content_creation(content["content_id"])
        
        return processed_result["content"]
    
    def get_full_content(self, content_id: str) -> Any:
        """Retrieve full content for two-step retrieval."""
        content = self._workflow_state.get_content(content_id)
        if content is None:
            return {"error": f"Content not found: {content_id}"}
        
        # Track successful content retrieval
        if self._telemetry:
            self._telemetry.record_content_retrieval(content_id)
        
        return content
