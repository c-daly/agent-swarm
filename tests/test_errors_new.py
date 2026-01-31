#!/usr/bin/env python3
"""Tests for the extended error hierarchy (daemon architecture)."""

import pytest

from lib.errors import (
    RouterError,
    BackendNotFoundError,
    ConnectionError as RouterConnectionError,
    RequestTimeoutError,
    BackendOverloadedError,
    PermissionDeniedError,
    BackendConnectionError,
    BackendError,
    WorkflowError,
)


class TestErrorHierarchy:
    """All errors inherit from RouterError."""

    @pytest.mark.parametrize("cls", [
        BackendNotFoundError,
        RouterConnectionError,
        RequestTimeoutError,
        BackendOverloadedError,
        PermissionDeniedError,
        BackendConnectionError,
        BackendError,
        WorkflowError,
    ])
    def test_subclass_of_router_error(self, cls):
        assert issubclass(cls, RouterError)

    def test_router_error_is_exception(self):
        assert issubclass(RouterError, Exception)


class TestPermissionDeniedError:
    """PermissionDeniedError carries a BlockedResponse."""

    def _make_blocked(self, reason="tool not allowed"):
        """Create a fake BlockedResponse-like object."""
        class FakeBlocked:
            pass
        obj = FakeBlocked()
        obj.reason = reason
        return obj

    def test_stores_response(self):
        response = self._make_blocked("tool not allowed")
        err = PermissionDeniedError(response)
        assert err.response is response
        assert str(err) == "tool not allowed"

    def test_message_from_reason(self):
        response = self._make_blocked("Bash blocked for explorer role")
        err = PermissionDeniedError(response)
        assert "Bash blocked for explorer role" in str(err)

    def test_catchable_as_router_error(self):
        response = self._make_blocked("blocked")
        with pytest.raises(RouterError):
            raise PermissionDeniedError(response)


class TestBackendConnectionError:
    def test_message(self):
        err = BackendConnectionError("serena failed to start")
        assert str(err) == "serena failed to start"
        assert isinstance(err, RouterError)

    def test_distinct_from_legacy_connection_error(self):
        """BackendConnectionError is separate from the legacy ConnectionError."""
        assert BackendConnectionError is not RouterConnectionError


class TestBackendError:
    def test_message(self):
        err = BackendError("serena returned invalid JSON")
        assert str(err) == "serena returned invalid JSON"
        assert isinstance(err, RouterError)


class TestWorkflowError:
    def test_message(self):
        err = WorkflowError("workflow not active")
        assert str(err) == "workflow not active"
        assert isinstance(err, RouterError)
