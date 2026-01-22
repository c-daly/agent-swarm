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

        Args:
            tool: Tool name in format "backend__tool_name" or just "tool_name"
            args: Tool arguments dict
        """
        if self._routing is None:
            return {"error": "RoutingService not configured"}

        # Parse tool string to extract destination and tool name
        # Format: "backend__tool_name" or just "tool_name"
        if "__" in tool:
            parts = tool.split("__", 1)
            destination = parts[0]
            tool_name = parts[1] if len(parts) > 1 else tool
        else:
            destination = "native"  # Default backend
            tool_name = tool

        # Route to backend
        result = self._routing.route(destination, tool_name, args)

        # Summarize if needed and get stats
        processed_result = self._summarization.process(result)

        # Determine status from result
        is_error = isinstance(result, dict) and "error" in result
        status = "error" if is_error else "success"

        # Record telemetry (if service available)
        if self._telemetry:
            self._telemetry.insert_event({
                "tool": tool,
                "timestamp": "now",  # Will be properly formatted
                "session_id": "controller",
                "backend": destination,
                "duration_ms": 0,
                "status": status,
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
