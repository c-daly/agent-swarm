#!/usr/bin/env python3
"""Error hierarchy for daemon and MCP router operations.

All errors inherit from RouterError, allowing callers to catch all
daemon errors with a single except clause if desired.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lib.permissions import BlockedResponse


class RouterError(Exception):
    """Base error for all daemon/router operations."""
    pass


class BackendNotFoundError(RouterError):
    """Raised when a requested backend is not registered."""
    pass


class ConnectionError(RouterError):
    """Raised when connection to a backend fails.

    Note: This shadows the builtin ConnectionError, but within the router
    context this is intentional - we want router-specific connection errors.
    """
    pass


class RequestTimeoutError(RouterError):
    """Raised when a request times out waiting for a response."""
    pass


class BackendOverloadedError(RouterError):
    """Raised when a backend is at maximum concurrent request capacity."""
    pass


# --- New errors for daemon architecture ---


class PermissionDeniedError(RouterError):
    """Tool call blocked by permission rules.

    Carries the BlockedResponse with the reason and rule that triggered the block.
    """
    def __init__(self, response: BlockedResponse) -> None:
        self.response = response
        super().__init__(response.reason)


class BackendConnectionError(RouterError):
    """Connection to backend subprocess failed."""
    pass


class BackendError(RouterError):
    """Generic error from a backend operation."""
    pass


class WorkflowError(RouterError):
    """Error in workflow state operations."""
    pass
