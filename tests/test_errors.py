"""Tests for router error hierarchy."""


class TestRouterErrors:
    """Tests for the router error classes."""

    def test_router_error_is_base_exception(self):
        """RouterError should be the base for all router errors."""
        from lib.errors import RouterError
        
        err = RouterError("test error")
        assert isinstance(err, Exception)
        assert str(err) == "test error"

    def test_backend_not_found_error_inherits_from_router_error(self):
        """BackendNotFoundError should inherit from RouterError."""
        from lib.errors import RouterError, BackendNotFoundError
        
        err = BackendNotFoundError("unknown_backend")
        assert isinstance(err, RouterError)
        assert "unknown_backend" in str(err)

    def test_connection_error_inherits_from_router_error(self):
        """ConnectionError should inherit from RouterError."""
        from lib.errors import RouterError, ConnectionError
        
        err = ConnectionError("failed to connect")
        assert isinstance(err, RouterError)
        assert "failed to connect" in str(err)

    def test_request_timeout_error_inherits_from_router_error(self):
        """RequestTimeoutError should inherit from RouterError."""
        from lib.errors import RouterError, RequestTimeoutError
        
        err = RequestTimeoutError("request timed out after 60s")
        assert isinstance(err, RouterError)
        assert "60s" in str(err)

    def test_backend_overloaded_error_inherits_from_router_error(self):
        """BackendOverloadedError should inherit from RouterError."""
        from lib.errors import RouterError, BackendOverloadedError
        
        err = BackendOverloadedError("backend at capacity")
        assert isinstance(err, RouterError)
        assert "capacity" in str(err)

    def test_all_errors_can_be_caught_as_router_error(self):
        """All specific errors should be catchable as RouterError."""
        from lib.errors import (
            RouterError,
            BackendNotFoundError,
            ConnectionError,
            RequestTimeoutError,
            BackendOverloadedError,
        )
        
        errors = [
            BackendNotFoundError("test"),
            ConnectionError("test"),
            RequestTimeoutError("test"),
            BackendOverloadedError("test"),
        ]
        
        for err in errors:
            try:
                raise err
            except RouterError as caught:
                assert caught is err
