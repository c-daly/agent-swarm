#!/usr/bin/env python3
"""Tests for combined-enforcement.py hook.

These tests verify the enforcement hook handles edge cases correctly.
"""

import importlib.util
import sys
from pathlib import Path


# Import module with hyphen in name
hooks_dir = Path(__file__).parent.parent / "hooks"
spec = importlib.util.spec_from_file_location(
    "combined_enforcement",
    hooks_dir / "combined-enforcement.py"
)
combined_enforcement = importlib.util.module_from_spec(spec)
sys.modules["combined_enforcement"] = combined_enforcement
spec.loader.exec_module(combined_enforcement)

check_phase_restrictions = combined_enforcement.check_phase_restrictions


class TestPhaseRestrictions:
    """Tests for check_phase_restrictions function."""

    def test_phase_none_does_not_crash(self):
        """Bug fix: state['phase'] = None should not cause AttributeError on .lower()

        When state has phase key set to None (not missing, but None),
        state.get("phase", "") returns None (not the default "").
        This caused: AttributeError: 'NoneType' object has no attribute 'lower'
        """
        state = {"phase": None}

        # Should not raise AttributeError
        result = check_phase_restrictions("Read", state, {})

        # None phase means no restrictions
        assert result is None

    def test_phase_missing_does_not_crash(self):
        """Missing phase key should not crash."""
        state = {}

        result = check_phase_restrictions("Read", state, {})

        # No phase means no restrictions
        assert result is None

    def test_phase_empty_string_does_not_crash(self):
        """Empty string phase should not crash."""
        state = {"phase": ""}

        result = check_phase_restrictions("Read", state, {})

        # Empty phase means no restrictions
        assert result is None

    def test_phase_valid_lowercase(self):
        """Valid phase in lowercase should work."""
        state = {"phase": "implement"}

        result = check_phase_restrictions("Read", state, {})

        # Read is allowed in implement phase
        assert result is None

    def test_phase_valid_uppercase(self):
        """Valid phase in uppercase should be normalized."""
        state = {"phase": "IMPLEMENT"}

        result = check_phase_restrictions("Read", state, {})

        # Read is allowed in implement phase
        assert result is None

    def test_phase_with_whitespace(self):
        """Phase with whitespace should be handled."""
        state = {"phase": "  implement  "}

        # Should not crash (may or may not strip, but shouldn't error)
        result = check_phase_restrictions("Read", state, {})

        # Result depends on implementation, just verify no crash
        assert result is None or isinstance(result, dict)


class TestNoneHandlingPattern:
    """Tests to verify the fix pattern: (value or default) instead of .get(key, default)

    The .get() method only uses the default if the key is MISSING.
    If the key exists but value is None, .get() returns None, not the default.
    """

    def test_get_with_none_value_returns_none(self):
        """Demonstrate the Python dict.get() behavior that caused the bug."""
        d = {"key": None}

        # This is the BUG: .get() returns None, not ""
        result = d.get("key", "")
        assert result is None, "dict.get() returns None when key exists but value is None"

    def test_or_pattern_handles_none(self):
        """Demonstrate the fix pattern."""
        d = {"key": None}

        # This is the FIX: or provides the default when value is falsy
        result = d.get("key") or ""
        assert result == "", "or pattern correctly returns default for None"

    def test_or_pattern_preserves_truthy_values(self):
        """Ensure the fix doesn't break truthy values."""
        d = {"key": "value"}

        result = d.get("key") or ""
        assert result == "value", "or pattern preserves truthy values"
