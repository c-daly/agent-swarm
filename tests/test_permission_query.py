"""Tests for permission_query.py"""

import sys
from pathlib import Path
from unittest.mock import patch

# Add lib to path
lib_dir = Path(__file__).parent.parent.parent / "lib"
sys.path.insert(0, str(lib_dir))

from permission_query import (  # noqa: E402
    get_permissions,
    is_tool_allowed,
    get_active_workflow_id,
    _KNOWN_WORKFLOWS,
)
from permission_store import PermissionStore  # noqa: E402


class TestGetActiveWorkflowId:
    """Test get_active_workflow_id function."""

    def test_no_active_workflow(self):
        """Should return None when no workflow is active."""
        with patch("permission_query.workflow_client") as mock_client:
            mock_client.workflow_is_active.return_value = False
            
            result = get_active_workflow_id()
            
            assert result is None
            # Should have checked all known workflows
            assert mock_client.workflow_is_active.call_count == len(_KNOWN_WORKFLOWS)

    def test_first_active_workflow_returned(self):
        """Should return the first active workflow found."""
        with patch("permission_query.workflow_client") as mock_client:
            # First two inactive, third active
            mock_client.workflow_is_active.side_effect = [False, False, True, False]
            
            result = get_active_workflow_id()
            
            assert result == _KNOWN_WORKFLOWS[2]  # Third workflow
            # Should stop after finding first active
            assert mock_client.workflow_is_active.call_count == 3

    def test_iterate_workflow_active(self):
        """Should detect iterate workflow as active."""
        with patch("permission_query.workflow_client") as mock_client:
            mock_client.workflow_is_active.side_effect = lambda wf_id: wf_id == "iterate"
            
            result = get_active_workflow_id()
            
            assert result == "iterate"


class TestGetPermissions:
    """Test get_permissions function."""

    def test_returns_none_when_no_workflow(self):
        """Should return None when no workflow is active."""
        with patch("permission_query.workflow_client") as mock_client:
            mock_client.workflow_is_active.return_value = False
            
            result = get_permissions()
            
            assert result is None

    def test_returns_none_for_inactive_specific_workflow(self):
        """Should return None when specific workflow is not active."""
        with patch("permission_query.workflow_client") as mock_client:
            mock_client.workflow_is_active.return_value = False
            
            result = get_permissions("nonexistent")
            
            assert result is None
            mock_client.workflow_is_active.assert_called_with("nonexistent")

    def test_returns_none_when_state_unavailable(self):
        """Should return None when workflow state cannot be retrieved."""
        with patch("permission_query.workflow_client") as mock_client:
            mock_client.workflow_is_active.return_value = True
            mock_client.workflow_get_state.return_value = None
            
            result = get_permissions("iterate")
            
            assert result is None

    def test_returns_minimal_store_when_no_permissions_key(self):
        """Should return minimal PermissionStore when state has no permissions key."""
        with patch("permission_query.workflow_client") as mock_client:
            mock_client.workflow_is_active.return_value = True
            mock_client.workflow_get_state.return_value = {
                "workflow_type": "iterate",
                "phase": "implement",
                # No "permissions" key
            }
            
            result = get_permissions("iterate")
            
            assert result is not None
            assert isinstance(result, PermissionStore)
            assert result.workflow_active is True
            assert result.workflow_id == "iterate"
            assert result.workflow_type == "iterate"
            assert result.phase == "implement"

    def test_returns_deserialized_permission_store(self):
        """Should deserialize PermissionStore from workflow state."""
        permissions_data = {
            "workflow_active": True,
            "workflow_type": "iterate",
            "workflow_id": "iterate",
            "phase": "test",
            "phase_permissions": {
                "blocked_tools": ["Edit", "Write"],
                "allowed_categories": ["FILE_READ", "FILE_SEARCH"],
                "allowed_file_patterns": ["**/*"],
                "blocked_file_patterns": [],
                "blocked_commands": [],
            },
            "is_subagent": False,
        }
        
        with patch("permission_query.workflow_client") as mock_client:
            mock_client.workflow_is_active.return_value = True
            mock_client.workflow_get_state.return_value = {
                "permissions": permissions_data,
            }
            
            result = get_permissions("iterate")
            
            assert result is not None
            assert result.workflow_active is True
            assert result.phase == "test"
            assert "Edit" in result.phase_permissions.blocked_tools

    def test_auto_detects_active_workflow(self):
        """Should auto-detect active workflow when no ID given."""
        with patch("permission_query.workflow_client") as mock_client:
            # Only debug workflow is active
            mock_client.workflow_is_active.side_effect = lambda wf: wf == "debug"
            mock_client.workflow_get_state.return_value = {
                "workflow_type": "debug",
                "phase": "triage",
            }
            
            result = get_permissions()
            
            assert result is not None
            assert result.workflow_type == "debug"


class TestIsToolAllowed:
    """Test is_tool_allowed function."""

    def test_allowed_when_no_workflow(self):
        """Should allow all tools when no workflow is active."""
        with patch("permission_query.workflow_client") as mock_client:
            mock_client.workflow_is_active.return_value = False
            
            allowed, reason = is_tool_allowed("Edit")
            
            assert allowed is True
            assert reason == ""

    def test_delegates_to_permission_store(self):
        """Should delegate to PermissionStore.is_tool_allowed()."""
        permissions_data = {
            "workflow_active": True,
            "phase": "test",
            "phase_permissions": {
                "blocked_tools": ["Edit"],
                "allowed_categories": [],
                "allowed_file_patterns": ["**/*"],
                "blocked_file_patterns": [],
                "blocked_commands": [],
            },
        }
        
        with patch("permission_query.workflow_client") as mock_client:
            mock_client.workflow_is_active.return_value = True
            mock_client.workflow_get_state.return_value = {
                "permissions": permissions_data,
            }
            
            # Edit should be blocked
            allowed, reason = is_tool_allowed("Edit", "iterate")
            assert allowed is False
            assert "blocked" in reason.lower()
            
            # Read should be allowed
            allowed, reason = is_tool_allowed("Read", "iterate")
            assert allowed is True

    def test_passes_context_to_permission_store(self):
        """Should pass context kwargs to PermissionStore."""
        permissions_data = {
            "workflow_active": True,
            "phase": "implement",
            "protected_paths": [".env", ".state/"],
        }
        
        with patch("permission_query.workflow_client") as mock_client:
            mock_client.workflow_is_active.return_value = True
            mock_client.workflow_get_state.return_value = {
                "permissions": permissions_data,
            }
            
            # Protected path should be blocked
            allowed, reason = is_tool_allowed(
                "Edit",
                "iterate",
                file_path=".env"
            )
            assert allowed is False
            assert "protected" in reason.lower()

    def test_handles_no_workflow_gracefully(self):
        """Should handle missing workflow gracefully."""
        with patch("permission_query.workflow_client") as mock_client:
            mock_client.workflow_is_active.return_value = False
            
            # Should not raise, should allow
            allowed, reason = is_tool_allowed("Edit", "nonexistent")
            
            assert allowed is True
            assert reason == ""


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_empty_state_dict(self):
        """Should handle empty state dict."""
        with patch("permission_query.workflow_client") as mock_client:
            mock_client.workflow_is_active.return_value = True
            mock_client.workflow_get_state.return_value = {}
            
            result = get_permissions("iterate")
            
            # Should return minimal store
            assert result is not None
            assert result.workflow_active is True
            assert result.phase == "none"

    def test_partial_permissions_data(self):
        """Should handle partial permissions data."""
        with patch("permission_query.workflow_client") as mock_client:
            mock_client.workflow_is_active.return_value = True
            mock_client.workflow_get_state.return_value = {
                "permissions": {
                    "workflow_active": True,
                    # Minimal data, missing most fields
                }
            }
            
            result = get_permissions("iterate")
            
            assert result is not None
            assert result.workflow_active is True

    def test_known_workflows_list(self):
        """Should have expected workflow IDs in known list."""
        assert "iterate" in _KNOWN_WORKFLOWS
        assert "debug" in _KNOWN_WORKFLOWS
        assert "pr_comment" in _KNOWN_WORKFLOWS
        assert "implementer" in _KNOWN_WORKFLOWS
