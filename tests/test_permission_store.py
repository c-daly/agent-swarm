"""Tests for permission_store.py"""

import pytest
import sys
from pathlib import Path

# Add lib to path
lib_dir = Path(__file__).parent.parent.parent / "lib"
sys.path.insert(0, str(lib_dir))

from permission_store import (
    PermissionStore, PhasePermissions, TaskConstraints, SubagentRestrictions,
    ToolCategory, TOOL_CATEGORIES, get_tool_category,
    FILE_WRITE_TOOLS, WORKFLOW_CONTROL_TOOLS,
)


class TestToolCategories:
    """Test tool category mapping."""

    def test_file_write_tools_defined(self):
        """FILE_WRITE_TOOLS should include editing tools."""
        assert "Edit" in FILE_WRITE_TOOLS
        assert "Write" in FILE_WRITE_TOOLS
        assert "NotebookEdit" in FILE_WRITE_TOOLS

    def test_workflow_control_tools_defined(self):
        """WORKFLOW_CONTROL_TOOLS should include workflow mutation tools."""
        assert "workflow_set_state" in WORKFLOW_CONTROL_TOOLS
        assert "mcp__router__workflow__workflow_set_state" in WORKFLOW_CONTROL_TOOLS

    def test_get_tool_category(self):
        """get_tool_category should return correct category."""
        assert get_tool_category("Read") == ToolCategory.FILE_READ
        assert get_tool_category("Edit") == ToolCategory.FILE_WRITE
        assert get_tool_category("Bash") == ToolCategory.SHELL_DANGEROUS
        assert get_tool_category("Task") == ToolCategory.SUBAGENT
        assert get_tool_category("unknown_tool") is None


class TestPhasePermissions:
    """Test PhasePermissions dataclass."""

    def test_default_values(self):
        """Default permissions should be permissive."""
        perms = PhasePermissions()
        assert perms.allowed_categories == frozenset()
        assert perms.blocked_tools == frozenset()
        assert "**/*" in perms.allowed_file_patterns

    def test_with_blocked_tools(self):
        """Should accept blocked tools."""
        perms = PhasePermissions(blocked_tools=frozenset({"Bash", "Edit"}))
        assert "Bash" in perms.blocked_tools
        assert "Edit" in perms.blocked_tools


class TestPermissionStoreSerialization:
    """Test PermissionStore serialization."""

    def test_to_dict_basic(self):
        """Should serialize to dict."""
        store = PermissionStore(
            workflow_active=True,
            workflow_type="iterate",
            phase="implement",
        )

        data = store.to_dict()

        assert data["workflow_active"] is True
        assert data["workflow_type"] == "iterate"
        assert data["phase"] == "implement"

    def test_to_dict_with_phase_permissions(self):
        """Should serialize phase permissions."""
        store = PermissionStore(
            workflow_active=True,
            phase="test",
            phase_permissions=PhasePermissions(
                blocked_tools=frozenset({"Edit", "Write"}),
                allowed_categories=frozenset({ToolCategory.FILE_READ, ToolCategory.FILE_SEARCH}),
            ),
        )

        data = store.to_dict()

        assert "Edit" in data["phase_permissions"]["blocked_tools"]
        assert "FILE_READ" in data["phase_permissions"]["allowed_categories"]

    def test_from_dict_basic(self):
        """Should deserialize from dict."""
        data = {
            "workflow_active": True,
            "workflow_type": "debug",
            "phase": "triage",
        }

        store = PermissionStore.from_dict(data)

        assert store.workflow_active is True
        assert store.workflow_type == "debug"
        assert store.phase == "triage"

    def test_from_dict_with_phase_permissions(self):
        """Should deserialize phase permissions."""
        data = {
            "workflow_active": True,
            "phase": "implement",
            "phase_permissions": {
                "blocked_tools": ["Bash"],
                "allowed_categories": ["FILE_READ", "FILE_WRITE"],
                "allowed_file_patterns": ["**/*.py"],
                "blocked_file_patterns": [],
                "blocked_commands": ["rm", "git push"],
            },
        }

        store = PermissionStore.from_dict(data)

        assert "Bash" in store.phase_permissions.blocked_tools
        assert ToolCategory.FILE_READ in store.phase_permissions.allowed_categories
        assert "**/*.py" in store.phase_permissions.allowed_file_patterns

    def test_roundtrip(self):
        """Serialization should be reversible."""
        original = PermissionStore(
            workflow_active=True,
            workflow_type="iterate",
            workflow_id="test-123",
            phase="implement",
            phase_permissions=PhasePermissions(
                blocked_tools=frozenset({"Bash"}),
                allowed_categories=frozenset({ToolCategory.FILE_READ}),
            ),
            task_constraints=TaskConstraints(
                require_background=True,
                max_agents=3,
            ),
            is_subagent=True,
            agent_id="agent-456",
            subagent_restrictions=SubagentRestrictions(
                can_spawn_subagents=False,
            ),
        )

        data = original.to_dict()
        restored = PermissionStore.from_dict(data)

        assert restored.workflow_active == original.workflow_active
        assert restored.workflow_type == original.workflow_type
        assert restored.phase == original.phase
        assert restored.is_subagent == original.is_subagent
        assert restored.agent_id == original.agent_id
        assert restored.task_constraints.require_background == original.task_constraints.require_background
        assert restored.task_constraints.max_agents == original.task_constraints.max_agents


class TestIsToolAllowed:
    """Test is_tool_allowed method."""

    def test_no_workflow_blocks_writes(self):
        """Should block write tools when no workflow active."""
        store = PermissionStore(workflow_active=False)

        allowed, reason = store.is_tool_allowed("Read")
        assert allowed is True

        allowed, reason = store.is_tool_allowed("Edit")
        assert allowed is False
        assert "No active workflow" in reason

    def test_blocked_tools_in_phase(self):
        """Should block tools listed in phase permissions."""
        store = PermissionStore(
            workflow_active=True,
            phase="test",
            phase_permissions=PhasePermissions(
                blocked_tools=frozenset({"Edit", "Write"}),
            ),
        )

        allowed, reason = store.is_tool_allowed("Edit")
        assert allowed is False
        assert "blocked" in reason.lower()

        allowed, reason = store.is_tool_allowed("Read")
        assert allowed is True

    def test_category_restrictions(self):
        """Should block tools not in allowed categories."""
        store = PermissionStore(
            workflow_active=True,
            phase="research",
            phase_permissions=PhasePermissions(
                allowed_categories=frozenset({ToolCategory.FILE_READ, ToolCategory.FILE_SEARCH}),
            ),
        )

        allowed, reason = store.is_tool_allowed("Read")
        assert allowed is True

        allowed, reason = store.is_tool_allowed("Edit")
        assert allowed is False
        assert "Category" in reason

    def test_protected_paths(self):
        """Should block access to protected paths."""
        store = PermissionStore(
            workflow_active=True,
            protected_paths=frozenset({".state/", ".env"}),
        )

        allowed, reason = store.is_tool_allowed("Edit", file_path=".state/workflow.json")
        assert allowed is False
        assert "protected" in reason.lower()

        allowed, reason = store.is_tool_allowed("Edit", file_path="src/main.py")
        assert allowed is True

    def test_subagent_workflow_restriction(self):
        """Subagents should not modify workflow state."""
        store = PermissionStore(
            workflow_active=True,
            is_subagent=True,
            subagent_restrictions=SubagentRestrictions(
                can_modify_workflow_state=False,
            ),
        )

        allowed, reason = store.is_tool_allowed("mcp__router__workflow__workflow_set_state")
        assert allowed is False
        assert "Subagents cannot modify" in reason

    def test_subagent_spawn_restriction(self):
        """Subagents should not spawn additional agents by default."""
        store = PermissionStore(
            workflow_active=True,
            is_subagent=True,
            subagent_restrictions=SubagentRestrictions(
                can_spawn_subagents=False,
            ),
        )

        allowed, reason = store.is_tool_allowed("Task")
        assert allowed is False
        assert "cannot spawn" in reason.lower()

    def test_max_agents_constraint(self):
        """Should enforce max agents limit."""
        store = PermissionStore(
            workflow_active=True,
            task_constraints=TaskConstraints(max_agents=3),
            current_agents=3,
        )

        allowed, reason = store.is_tool_allowed("Task")
        assert allowed is False
        assert "Max agents" in reason

    def test_require_background_constraint(self):
        """Should enforce require_background for Task tool."""
        store = PermissionStore(
            workflow_active=True,
            task_constraints=TaskConstraints(require_background=True),
        )

        allowed, reason = store.is_tool_allowed("Task", run_in_background=False)
        assert allowed is False
        assert "run_in_background" in reason

        allowed, reason = store.is_tool_allowed("Task", run_in_background=True)
        assert allowed is True

    def test_blocked_commands(self):
        """Should block specific commands."""
        store = PermissionStore(
            workflow_active=True,
            phase="implement",
            phase_permissions=PhasePermissions(
                blocked_commands=frozenset({"rm", "git"}),
            ),
        )

        allowed, reason = store.is_tool_allowed("Bash", command="rm -rf /")
        assert allowed is False
        assert "blocked" in reason.lower()

        allowed, reason = store.is_tool_allowed("Bash", command="pytest tests/")
        assert allowed is True


class TestTaskConstraints:
    """Test TaskConstraints dataclass."""

    def test_defaults(self):
        """Default constraints should be reasonable."""
        tc = TaskConstraints()
        assert tc.require_background is False
        assert tc.max_agents == 5
        assert tc.allowed_agent_types == frozenset()


class TestSubagentRestrictions:
    """Test SubagentRestrictions dataclass."""

    def test_defaults(self):
        """Default restrictions should be secure."""
        sr = SubagentRestrictions()
        assert sr.can_modify_workflow_state is False
        assert sr.can_modify_own_agent_state is True
        assert sr.can_spawn_subagents is False
        assert sr.inherits_phase is True
