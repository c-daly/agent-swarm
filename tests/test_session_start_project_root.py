"""Tests for project_root in session state."""
"""Tests for project_root in session state."""
import importlib
import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
import sys
import os

# Add hooks dir to path so we can import session-start.py (hyphenated filename)
hooks_dir = Path(__file__).parent.parent / "hooks"
lib_dir = Path(__file__).parent.parent / "lib"
sys.path.insert(0, str(hooks_dir))
sys.path.insert(0, str(lib_dir))

# Import hyphenated module using importlib
_loader = importlib.machinery.SourceFileLoader("session_start", str(hooks_dir / "session-start.py"))
_spec = importlib.util.spec_from_loader("session_start", _loader)
session_start = importlib.util.module_from_spec(_spec)
sys.modules["session_start"] = session_start
_loader.exec_module(session_start)


class TestProjectRootInSessionState:
    """Test that reset_enforcement_counters includes project_root in session state."""

    @patch.object(session_start, "workflow_set_state", return_value=None)
    @patch.object(session_start, "find_project_root")
    def test_project_root_included_in_state(self, mock_find_root, mock_wf_set):
        """When find_project_root returns a path, it should be in the state."""
        mock_find_root.return_value = Path("/home/user/myproject")

        session_start.reset_enforcement_counters()

        # workflow_set_state should have been called with state containing project_root
        mock_wf_set.assert_called_once()
        state = mock_wf_set.call_args[0][1]
        assert "project_root" in state
        assert state["project_root"] == "/home/user/myproject"

    @patch.object(session_start, "workflow_set_state", return_value=None)
    @patch.object(session_start, "find_project_root", None)
    def test_project_root_absent_when_find_is_none(self, mock_wf_set):
        """When find_project_root is None, project_root should not be in state."""
        session_start.reset_enforcement_counters()

        mock_wf_set.assert_called_once()
        state = mock_wf_set.call_args[0][1]
        assert "project_root" not in state

    @patch.object(session_start, "workflow_set_state", return_value=None)
    @patch.object(session_start, "find_project_root")
    def test_project_root_absent_on_exception(self, mock_find_root, mock_wf_set):
        """When find_project_root raises, project_root should not be in state."""
        mock_find_root.side_effect = RuntimeError("no git repo")

        session_start.reset_enforcement_counters()

        mock_wf_set.assert_called_once()
        state = mock_wf_set.call_args[0][1]
        assert "project_root" not in state
