#!/usr/bin/env python3
"""Error hierarchy for MCP router operations.

All router-specific errors inherit from RouterError, allowing callers
to catch all router errors with a single except clause if desired.
"""


class RouterError(Exception):
    """Base error for all router operations.
    
    All specific router errors inherit from this class.
    """
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
