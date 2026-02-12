"""Integration tests for the permission system.

Tests the full integration between:
- WorkflowEngine (workflow_base.py)
- PermissionStore (permission_store.py)
- Permission query interface (permission_query.py)
"""

import sys
from pathlib import Path

import pytest

# Add lib to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "lib"))

# ruff: noqa: E402
from permission_store import (
    PermissionStore,
    PhasePermissions,
    SubagentRestrictions,
    TaskConstraints,
)
from permission_query import get_permissions, is_tool_allowed, get_active_workflow_id
from workflow_base import (
    WorkflowEngine,
    WorkflowDefinition,
    WorkflowPhase,
    PhaseTransition,
)
import workflow_client


# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def simple_workflow_definition():
    """Create a simple two-phase workflow for testing."""
    return WorkflowDefinition(
        name="test_workflow",
        phases={
            "planning": WorkflowPhase(
                name="planning",
                blocked_tools=frozenset({"Edit", "Write"}),  # No editing in planning
            ),
            "implementing": WorkflowPhase(
                name="implementing",
                blocked_tools=frozenset(),  # All tools allowed
                allowed_file_patterns=frozenset({"*.py", "*.md"}),
            ),
            "done": WorkflowPhase(
                name="done",
                blocked_tools=frozenset({"Edit", "Write", "Task"}),
            ),
        },
        transitions={
            "planning": PhaseTransition(
                from_phase="planning",
                to_phase="implementing",
            ),
            "implementing": PhaseTransition(
                from_phase="implementing",
                to_phase="done",
            ),
        },
        initial_phase="planning",
    )


@pytest.fixture
def iterate_like_workflow():
    """Workflow similar to iterate with test_writing and orchestrate phases."""
    return WorkflowDefinition(
        name="iterate",
        phases={
            "test_writing": WorkflowPhase(
                name="test_writing",
                blocked_tools=frozenset(),  # Editing allowed
                allowed_file_patterns=frozenset({"tests/**/*.py", "test_*.py"}),
            ),
            "orchestrate": WorkflowPhase(
                name="orchestrate",
                blocked_tools=frozenset({"Edit", "Write", "NotebookEdit"}),  # No editing
            ),
            "implementation": WorkflowPhase(
                name="implementation",
                blocked_tools=frozenset(),
                allowed_file_patterns=frozenset({"**/*.py"}),
            ),
        },
        transitions={
            "test_writing": PhaseTransition(
                from_phase="test_writing",
                to_phase="orchestrate",
            ),
            "orchestrate": PhaseTransition(
                from_phase="orchestrate",
                to_phase="implementation",
            ),
        },
        initial_phase="test_writing",
    )


# =============================================================================
# Test: Workflow starts with correct permissions
# =============================================================================


class TestWorkflowStartPermissions:
    """Test that WorkflowEngine.start() sets up permissions correctly."""

    def test_workflow_start_creates_active_permission_store(
        self, simple_workflow_definition, mock_workflow_client
    ):
        """WorkflowEngine.start() should set up PermissionStore with active state."""
        engine = WorkflowEngine(simple_workflow_definition)
        engine.start("Test task")

        store = engine.get_permission_store()

        assert store is not None
        assert store.workflow_active is True
        assert store.workflow_type == "test_workflow"
        assert store.workflow_id == "test_workflow"
        assert store.phase == "planning"

    def test_workflow_start_initial_phase_permissions(
        self, simple_workflow_definition, mock_workflow_client
    ):
        """Initial phase should have correct permission restrictions."""
        engine = WorkflowEngine(simple_workflow_definition)
        engine.start("Test task")

        store = engine.get_permission_store()

        # Planning phase blocks Edit and Write
        assert store.phase_permissions is not None
        assert "Edit" in store.phase_permissions.blocked_tools
        assert "Write" in store.phase_permissions.blocked_tools

    def test_is_tool_allowed_reflects_initial_phase(
        self, simple_workflow_definition, mock_workflow_client
    ):
        """is_tool_allowed() should block tools per initial phase config."""
        engine = WorkflowEngine(simple_workflow_definition)
        engine.start("Test task")

        # Edit should be blocked in planning
        allowed, reason = engine.is_tool_allowed("Edit")
        assert allowed is False
        assert "blocked" in reason.lower()

        # Read should be allowed
        allowed, reason = engine.is_tool_allowed("Read")
        assert allowed is True


# =============================================================================
# Test: Phase transitions update permissions
# =============================================================================


class TestPhaseTransitionPermissions:
    """Test that phase transitions correctly update permissions."""

    def test_phase_advance_changes_permissions(
        self, simple_workflow_definition, mock_workflow_client
    ):
        """Advancing phase should update permission restrictions."""
        engine = WorkflowEngine(simple_workflow_definition)
        engine.start("Test task")

        # Initially in planning - Edit blocked
        allowed, _ = engine.is_tool_allowed("Edit")
        assert allowed is False

        # Advance to implementing
        result = engine.advance()
        assert result.success is True
        assert engine.get_phase() == "implementing"

        # Now Edit should be allowed
        allowed, _ = engine.is_tool_allowed("Edit")
        assert allowed is True

    def test_phase_permissions_update_file_patterns(
        self, simple_workflow_definition, mock_workflow_client
    ):
        """Phase transition should update allowed file patterns."""
        engine = WorkflowEngine(simple_workflow_definition)
        engine.start("Test task")

        # Advance to implementing
        engine.advance()

        store = engine.get_permission_store()
        assert store.phase_permissions is not None
        assert "*.py" in store.phase_permissions.allowed_file_patterns
        assert "*.md" in store.phase_permissions.allowed_file_patterns

    def test_multiple_transitions_track_phase(
        self, simple_workflow_definition, mock_workflow_client
    ):
        """Multiple transitions should properly update phase permissions."""
        engine = WorkflowEngine(simple_workflow_definition)
        engine.start("Test task")

        # planning -> implementing -> done
        engine.advance()
        assert engine.get_phase() == "implementing"

        engine.advance()
        assert engine.get_phase() == "done"

        # In done phase, Task should be blocked
        store = engine.get_permission_store()
        assert "Task" in store.phase_permissions.blocked_tools


# =============================================================================
# Test: Subagents get restricted permissions
# =============================================================================


class TestSubagentPermissions:
    """Test that subagents have appropriate restrictions."""

    def test_subagent_cannot_spawn_subagents(self, mock_workflow_client):
        """PermissionStore with is_subagent=True should block Task tool."""
        store = PermissionStore(
            workflow_active=True,
            is_subagent=True,
            subagent_restrictions=SubagentRestrictions(
                can_spawn_subagents=False,
            ),
        )

        allowed, reason = store.is_tool_allowed("Task")
        assert allowed is False
        assert "spawn" in reason.lower() or "subagent" in reason.lower()

    def test_subagent_cannot_modify_workflow_state(self, mock_workflow_client):
        """Subagents should not be able to modify workflow state."""
        store = PermissionStore(
            workflow_active=True,
            is_subagent=True,
            subagent_restrictions=SubagentRestrictions(
                can_modify_workflow_state=False,
            ),
        )

        # Check workflow control tools are blocked
        allowed, reason = store.is_tool_allowed("mcp__router__workflow__workflow_set_state")
        assert allowed is False
        assert "workflow" in reason.lower()

    def test_non_subagent_can_spawn(self, mock_workflow_client):
        """Non-subagent should be able to use Task tool."""
        store = PermissionStore(
            workflow_active=True,
            is_subagent=False,
        )

        allowed, reason = store.is_tool_allowed("Task")
        assert allowed is True

    def test_subagent_inherits_phase_permissions(
        self, simple_workflow_definition, mock_workflow_client
    ):
        """Subagent PermissionStore should reflect inherited phase restrictions."""
        engine = WorkflowEngine(simple_workflow_definition)
        engine.start("Test task")

        # Get base permissions
        base_store = engine.get_permission_store()

        # Create subagent store (simulating what would happen)
        subagent_store = PermissionStore(
            workflow_active=True,
            workflow_type=base_store.workflow_type,
            phase=base_store.phase,
            phase_permissions=base_store.phase_permissions,
            is_subagent=True,
            subagent_restrictions=SubagentRestrictions(
                can_spawn_subagents=False,
                inherits_phase=True,
            ),
        )

        # Should inherit the blocked tools from planning phase
        allowed, _ = subagent_store.is_tool_allowed("Edit")
        assert allowed is False


# =============================================================================
# Test: Permission query interface works
# =============================================================================


class TestPermissionQueryInterface:
    """Test the permission_query module functions."""

    def test_get_permissions_returns_store_for_active_workflow(
        self, mock_workflow_client
    ):
        """get_permissions() should return PermissionStore from active workflow."""
        # Set up workflow state directly
        workflow_client.workflow_start("iterate", {
            "active": True,
            "workflow_type": "iterate",
            "phase": "test_writing",
            "permissions": {
                "workflow_active": True,
                "workflow_type": "iterate",
                "workflow_id": "iterate",
                "phase": "test_writing",
            },
        })

        store = get_permissions("iterate")

        assert store is not None
        assert store.workflow_active is True
        assert store.phase == "test_writing"

    def test_get_permissions_returns_none_for_inactive(self, mock_workflow_client):
        """get_permissions() should return None when no workflow active."""
        store = get_permissions("nonexistent")
        assert store is None

    def test_get_active_workflow_id_finds_active(self, mock_workflow_client):
        """get_active_workflow_id() should find the active workflow."""
        workflow_client.workflow_start("iterate", {"active": True})

        active_id = get_active_workflow_id()
        assert active_id == "iterate"

    def test_get_active_workflow_id_returns_none_when_none_active(
        self, mock_workflow_client
    ):
        """get_active_workflow_id() should return None when no workflow active."""
        active_id = get_active_workflow_id()
        assert active_id is None

    def test_is_tool_allowed_uses_workflow_permissions(self, mock_workflow_client):
        """is_tool_allowed() should check against workflow permissions."""
        # Set up workflow with permissions that block Edit
        workflow_client.workflow_start("iterate", {
            "active": True,
            "phase": "orchestrate",
            "permissions": {
                "workflow_active": True,
                "workflow_id": "iterate",
                "phase": "orchestrate",
                "phase_permissions": {
                    "blocked_tools": ["Edit", "Write"],
                    "allowed_categories": [],
                    "allowed_file_patterns": [],
                    "blocked_file_patterns": [],
                    "blocked_commands": [],
                },
            },
        })

        allowed, reason = is_tool_allowed("Edit", workflow_id="iterate")
        assert allowed is False
        assert "blocked" in reason.lower()


# =============================================================================
# Test: Tool blocking works end-to-end
# =============================================================================


class TestToolBlockingEndToEnd:
    """Test full flow from workflow to permissions to is_tool_allowed."""

    def test_iterate_test_writing_allows_edit(
        self, iterate_like_workflow, mock_workflow_client
    ):
        """In test_writing phase, Edit should be allowed."""
        engine = WorkflowEngine(iterate_like_workflow, workflow_id="iterate")
        engine.start("Write tests for feature X")

        assert engine.get_phase() == "test_writing"

        allowed, reason = engine.is_tool_allowed("Edit")
        assert allowed is True

    def test_iterate_orchestrate_blocks_edit(
        self, iterate_like_workflow, mock_workflow_client
    ):
        """In orchestrate phase, Edit should be blocked."""
        engine = WorkflowEngine(iterate_like_workflow, workflow_id="iterate")
        engine.start("Write tests for feature X")

        # Advance to orchestrate
        result = engine.advance()
        assert result.success is True
        assert engine.get_phase() == "orchestrate"

        allowed, reason = engine.is_tool_allowed("Edit")
        assert allowed is False
        assert "blocked" in reason.lower()

    def test_full_workflow_permission_flow(
        self, iterate_like_workflow, mock_workflow_client
    ):
        """Test complete permission flow through workflow lifecycle."""
        engine = WorkflowEngine(iterate_like_workflow, workflow_id="iterate")
        engine.start("Build feature")

        # Phase 1: test_writing - can edit test files
        assert engine.is_tool_allowed("Edit")[0] is True
        assert engine.is_tool_allowed("Read")[0] is True
        assert engine.is_tool_allowed("Task")[0] is True

        # Phase 2: orchestrate - no editing
        engine.advance()
        assert engine.is_tool_allowed("Edit")[0] is False
        assert engine.is_tool_allowed("Read")[0] is True

        # Phase 3: implementation - can edit again
        engine.advance()
        assert engine.is_tool_allowed("Edit")[0] is True

    def test_no_workflow_allows_file_writes(self, mock_workflow_client):
        """Without active workflow, file writes should still be allowed.

        Agents can operate outside workflows based on their registration
        and role permissions, not solely on workflow presence.
        """
        store = PermissionStore(
            workflow_active=False,
        )

        allowed, reason = store.is_tool_allowed("Edit")
        assert allowed is True

        allowed, reason = store.is_tool_allowed("Write")
        assert allowed is True

    def test_protected_paths_always_blocked(
        self, simple_workflow_definition, mock_workflow_client
    ):
        """Protected paths should be blocked even in permissive phases."""
        engine = WorkflowEngine(simple_workflow_definition)
        engine.start("Test task")
        engine.advance()  # Move to implementing where Edit is allowed

        # Edit is allowed in implementing
        allowed, _ = engine.is_tool_allowed("Edit")
        assert allowed is True

        # But protected paths are still blocked
        allowed, reason = engine.is_tool_allowed("Edit", file_path=".state/secrets.json")
        assert allowed is False
        assert "protected" in reason.lower()


# =============================================================================
# Test: Serialization round-trip
# =============================================================================


class TestPermissionSerialization:
    """Test that permissions serialize/deserialize correctly."""

    def test_permission_store_round_trip(self, mock_workflow_client):
        """PermissionStore should survive to_dict/from_dict round trip."""
        original = PermissionStore(
            workflow_active=True,
            workflow_type="iterate",
            workflow_id="iterate",
            phase="implementing",
            phase_permissions=PhasePermissions(
                blocked_tools=frozenset({"Task"}),
                allowed_file_patterns=frozenset({"*.py", "tests/**"}),
            ),
            is_subagent=True,
            agent_id="agent-123",
            subagent_restrictions=SubagentRestrictions(
                can_spawn_subagents=False,
                can_modify_workflow_state=False,
            ),
        )

        # Round trip through dict
        data = original.to_dict()
        restored = PermissionStore.from_dict(data)

        assert restored.workflow_active == original.workflow_active
        assert restored.workflow_type == original.workflow_type
        assert restored.phase == original.phase
        assert restored.is_subagent == original.is_subagent
        assert restored.agent_id == original.agent_id
        assert restored.subagent_restrictions.can_spawn_subagents is False

        # Verify phase permissions
        assert restored.phase_permissions is not None
        assert "Task" in restored.phase_permissions.blocked_tools
        assert "*.py" in restored.phase_permissions.allowed_file_patterns

    def test_stored_permissions_work_after_restore(self, mock_workflow_client):
        """Permissions from state should work for is_tool_allowed checks."""
        # Create and serialize
        original = PermissionStore(
            workflow_active=True,
            phase="planning",
            phase_permissions=PhasePermissions(
                blocked_tools=frozenset({"Edit"}),
            ),
        )

        # Store in workflow state
        workflow_client.workflow_start("test", {
            "permissions": original.to_dict(),
        })

        # Retrieve and restore
        state = workflow_client.workflow_get_state("test")
        restored = PermissionStore.from_dict(state["permissions"])

        # Should still block Edit
        allowed, _ = restored.is_tool_allowed("Edit")
        assert allowed is False


# =============================================================================
# Test: Task constraints
# =============================================================================


class TestTaskConstraints:
    """Test Task tool constraints enforcement."""

    def test_max_agents_blocks_when_exceeded(self, mock_workflow_client):
        """Task should be blocked when max agents reached."""
        store = PermissionStore(
            workflow_active=True,
            task_constraints=TaskConstraints(max_agents=3),
            current_agents=3,  # At max
        )

        allowed, reason = store.is_tool_allowed("Task")
        assert allowed is False
        assert "max" in reason.lower()

    def test_max_agents_allows_when_under(self, mock_workflow_client):
        """Task should be allowed when under max agents."""
        store = PermissionStore(
            workflow_active=True,
            task_constraints=TaskConstraints(max_agents=3),
            current_agents=2,  # Under max
        )

        allowed, _ = store.is_tool_allowed("Task")
        assert allowed is True

    def test_require_background_blocks_foreground(self, mock_workflow_client):
        """When require_background=True, foreground Task should be blocked."""
        store = PermissionStore(
            workflow_active=True,
            task_constraints=TaskConstraints(require_background=True),
        )

        # Without run_in_background context
        allowed, reason = store.is_tool_allowed("Task")
        assert allowed is False
        assert "background" in reason.lower()

        # With run_in_background=True
        allowed, _ = store.is_tool_allowed("Task", run_in_background=True)
        assert allowed is True
