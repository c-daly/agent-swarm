"""Integration tests for workflow system components.

Tests interactions between WorkflowStateServer and WorkflowStateService,
including full workflow lifecycles, agent state management, and concurrent
multi-workflow scenarios.
"""
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy

import pytest

# Import the server class directly for integration testing
# (client requires router which isn't available in tests)
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "lib"))

from workflow_server import WorkflowStateServer
from workflow_state_service import WorkflowStateService


# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------

@pytest.fixture
def server():
    """Provide a fresh WorkflowStateServer instance."""
    return WorkflowStateServer()


@pytest.fixture
def content_service():
    """Provide a fresh WorkflowStateService instance."""
    return WorkflowStateService()


@pytest.fixture
def workflow_id():
    """Generate a unique workflow ID for each test."""
    return f"test-workflow-{uuid.uuid4().hex[:8]}"


@pytest.fixture
def initial_state():
    """Standard initial workflow state."""
    return {
        "phase": "intake",
        "task": "test task",
        "iteration": 0,
        "active": True,
    }


# -----------------------------------------------------------------------------
# Full Workflow Lifecycle Tests
# -----------------------------------------------------------------------------

class TestWorkflowLifecycle:
    """Test complete workflow lifecycle: start -> update -> get_state -> stop."""

    def test_complete_workflow_lifecycle(self, server, workflow_id, initial_state):
        """Test full start -> update -> query -> stop cycle."""
        # Start workflow
        state = server.workflow_start(workflow_id, initial_state)
        assert state == initial_state
        assert server.workflow_is_active(workflow_id)

        # Update workflow
        updated = server.workflow_update(workflow_id, {"phase": "implement", "iteration": 1})
        assert updated["phase"] == "implement"
        assert updated["iteration"] == 1
        assert updated["task"] == "test task"  # Original field preserved

        # Get full state
        full_state = server.workflow_get_state(workflow_id)
        assert full_state["phase"] == "implement"
        assert full_state["iteration"] == 1

        # Stop workflow
        success = server.workflow_stop(workflow_id)
        assert success is True
        assert server.workflow_is_active(workflow_id) is False

    def test_workflow_lifecycle_with_value_operations(self, server, workflow_id):
        """Test lifecycle using individual value get/set operations."""
        # Start with minimal state
        server.workflow_start(workflow_id, {"phase": "init"})

        # Set individual values
        server.workflow_set_value(workflow_id, "task", "implement feature")
        server.workflow_set_value(workflow_id, "iteration", 0)
        server.workflow_set_value(workflow_id, "files_modified", ["a.py", "b.py"])

        # Read individual values
        assert server.workflow_get_value(workflow_id, "phase") == "init"
        assert server.workflow_get_value(workflow_id, "task") == "implement feature"
        assert server.workflow_get_value(workflow_id, "files_modified") == ["a.py", "b.py"]

        # Update phase through set_value
        server.workflow_set_value(workflow_id, "phase", "verify")
        assert server.workflow_get_value(workflow_id, "phase") == "verify"

        # Clean up
        server.workflow_stop(workflow_id)

    def test_workflow_replace_state(self, server, workflow_id, initial_state):
        """Test workflow_set_state replaces entire state."""
        server.workflow_start(workflow_id, initial_state)

        # Replace with completely new state
        new_state = {"phase": "new", "completely": "different"}
        result = server.workflow_set_state(workflow_id, new_state)

        assert result == new_state
        assert server.workflow_get_value(workflow_id, "phase") == "new"
        assert server.workflow_get_value(workflow_id, "completely") == "different"
        # Old fields should be gone
        assert server.workflow_get_value(workflow_id, "task") is None
        assert server.workflow_get_value(workflow_id, "iteration") is None

        server.workflow_stop(workflow_id)

    def test_workflow_start_fails_if_exists(self, server, workflow_id, initial_state):
        """Starting a workflow that exists should raise ValueError."""
        server.workflow_start(workflow_id, initial_state)

        with pytest.raises(ValueError, match="already exists"):
            server.workflow_start(workflow_id, {"another": "state"})

        # Original state should be unchanged
        assert server.workflow_get_state(workflow_id) == initial_state

        server.workflow_stop(workflow_id)

    def test_workflow_stop_nonexistent_returns_false(self, server):
        """Stopping a non-existent workflow should return False."""
        result = server.workflow_stop("nonexistent-workflow")
        assert result is False

    def test_workflow_update_nonexistent_raises(self, server):
        """Updating a non-existent workflow should raise ValueError."""
        with pytest.raises(ValueError, match="not found"):
            server.workflow_update("nonexistent", {"phase": "test"})

    def test_workflow_set_value_nonexistent_raises(self, server):
        """Setting value on non-existent workflow should raise ValueError."""
        with pytest.raises(ValueError, match="not found"):
            server.workflow_set_value("nonexistent", "key", "value")


# -----------------------------------------------------------------------------
# Agent State Management Tests
# -----------------------------------------------------------------------------

class TestAgentStateManagement:
    """Test agent state operations and their interaction with workflows."""

    def test_agent_lifecycle(self, server):
        """Test full agent state lifecycle: set -> get -> delete."""
        agent_id = "agent-123"
        state = {"status": "running", "task": "implement", "progress": 0.5}

        # Set agent state
        result = server.agent_set_state(agent_id, state)
        assert result == state

        # Get agent state
        retrieved = server.agent_get_state(agent_id)
        assert retrieved == state

        # Update state
        updated_state = {"status": "completed", "task": "implement", "progress": 1.0}
        server.agent_set_state(agent_id, updated_state)
        assert server.agent_get_state(agent_id) == updated_state

        # Delete agent
        deleted = server.agent_delete(agent_id)
        assert deleted is True

        # Should be gone
        assert server.agent_get_state(agent_id) is None

    def test_list_agents(self, server):
        """Test listing multiple agents."""
        # Add several agents
        for i in range(5):
            server.agent_set_state(f"agent-{i}", {"index": i})

        agents = server.list_agents()
        assert len(agents) == 5
        assert all(f"agent-{i}" in agents for i in range(5))

        # Clean up
        for i in range(5):
            server.agent_delete(f"agent-{i}")

    def test_agent_delete_nonexistent_returns_false(self, server):
        """Deleting non-existent agent should return False."""
        result = server.agent_delete("nonexistent-agent")
        assert result is False

    def test_agent_get_nonexistent_returns_none(self, server):
        """Getting non-existent agent should return None."""
        result = server.agent_get_state("nonexistent-agent")
        assert result is None

    def test_agents_independent_of_workflows(self, server, workflow_id, initial_state):
        """Agent and workflow states should be independent."""
        # Create workflow
        server.workflow_start(workflow_id, initial_state)

        # Create agent with same ID (should work - different namespace)
        server.agent_set_state(workflow_id, {"agent_state": True})

        # Both should exist independently
        assert server.workflow_is_active(workflow_id)
        assert server.agent_get_state(workflow_id) == {"agent_state": True}
        assert server.workflow_get_state(workflow_id) == initial_state

        # Stop workflow - agent should still exist
        server.workflow_stop(workflow_id)
        assert server.workflow_is_active(workflow_id) is False
        assert server.agent_get_state(workflow_id) == {"agent_state": True}

        # Clean up
        server.agent_delete(workflow_id)


# -----------------------------------------------------------------------------
# Multi-Workflow Scenarios
# -----------------------------------------------------------------------------

class TestMultiWorkflowScenarios:
    """Test scenarios with multiple concurrent workflows."""

    def test_multiple_independent_workflows(self, server):
        """Multiple workflows should operate independently."""
        workflows = {}
        for name in ["iterate", "debug", "pr_comment"]:
            workflows[name] = {"phase": "init", "type": name}
            server.workflow_start(name, workflows[name])

        # Update each independently
        server.workflow_update("iterate", {"phase": "implement", "iteration": 1})
        server.workflow_update("debug", {"phase": "investigate", "bug": "NPE"})
        server.workflow_update("pr_comment", {"phase": "review", "comment_id": 123})

        # Verify independent state
        assert server.workflow_get_value("iterate", "phase") == "implement"
        assert server.workflow_get_value("debug", "phase") == "investigate"
        assert server.workflow_get_value("pr_comment", "phase") == "review"

        # Stop one, others continue
        server.workflow_stop("debug")
        assert server.workflow_is_active("debug") is False
        assert server.workflow_is_active("iterate") is True
        assert server.workflow_is_active("pr_comment") is True

        # Clean up
        server.workflow_stop("iterate")
        server.workflow_stop("pr_comment")

    def test_workflow_state_isolation(self, server):
        """Changing one workflow should not affect another."""
        server.workflow_start("wf1", {"shared_key": "value1"})
        server.workflow_start("wf2", {"shared_key": "value2"})

        # Update wf1
        server.workflow_set_value("wf1", "shared_key", "updated1")

        # wf2 should be unchanged
        assert server.workflow_get_value("wf2", "shared_key") == "value2"

        # Clean up
        server.workflow_stop("wf1")
        server.workflow_stop("wf2")

    def test_workflow_with_multiple_agents(self, server, workflow_id, initial_state):
        """Test workflow managing multiple agents."""
        server.workflow_start(workflow_id, initial_state)

        # Register multiple agents
        agent_ids = []
        for i in range(3):
            agent_id = f"sub-{uuid.uuid4().hex[:8]}"
            agent_ids.append(agent_id)
            server.agent_set_state(agent_id, {
                "workflow": workflow_id,
                "task": f"subtask-{i}",
                "status": "running",
            })

        # Track agents in workflow state
        server.workflow_set_value(workflow_id, "agents", agent_ids)

        # Verify all agents exist
        agents = server.list_agents()
        for agent_id in agent_ids:
            assert agent_id in agents

        # Update workflow phase
        server.workflow_update(workflow_id, {"phase": "verify"})

        # Update agent statuses
        for agent_id in agent_ids:
            server.agent_set_state(agent_id, {
                **server.agent_get_state(agent_id),
                "status": "completed",
            })

        # Verify agent updates
        for agent_id in agent_ids:
            assert server.agent_get_state(agent_id)["status"] == "completed"

        # Clean up
        for agent_id in agent_ids:
            server.agent_delete(agent_id)
        server.workflow_stop(workflow_id)


# -----------------------------------------------------------------------------
# Concurrent Operations Tests
# -----------------------------------------------------------------------------

class TestConcurrentOperations:
    """Test thread-safety with concurrent workflow operations."""

    def test_concurrent_workflow_updates(self, server, workflow_id):
        """Multiple threads updating same workflow should be safe."""
        server.workflow_start(workflow_id, {"counter": 0})

        num_updates = 100
        barrier = threading.Barrier(10)

        def increment():
            barrier.wait()
            for _ in range(num_updates // 10):
                current = server.workflow_get_value(workflow_id, "counter") or 0
                server.workflow_set_value(workflow_id, "counter", current + 1)

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(increment) for _ in range(10)]
            for f in as_completed(futures):
                f.result()

        # Due to race conditions, counter may not equal num_updates
        # but it should be > 0 and all operations should complete without error
        final = server.workflow_get_value(workflow_id, "counter")
        assert final > 0

        server.workflow_stop(workflow_id)

    def test_concurrent_multiple_workflows(self, server):
        """Multiple threads managing different workflows concurrently."""
        num_workflows = 20

        def workflow_lifecycle(index):
            wf_id = f"concurrent-wf-{index}"
            server.workflow_start(wf_id, {"index": index, "phase": "init"})

            for phase in ["implement", "verify", "review", "complete"]:
                server.workflow_update(wf_id, {"phase": phase})
                state = server.workflow_get_state(wf_id)
                assert state["phase"] == phase
                assert state["index"] == index

            server.workflow_stop(wf_id)
            return True

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(workflow_lifecycle, i) for i in range(num_workflows)]
            results = [f.result() for f in as_completed(futures)]

        assert all(results)

    def test_concurrent_agent_operations(self, server):
        """Multiple threads managing agents concurrently."""
        num_agents = 50

        def agent_lifecycle(index):
            agent_id = f"concurrent-agent-{index}"
            server.agent_set_state(agent_id, {"index": index, "status": "init"})

            for status in ["running", "paused", "completed"]:
                server.agent_set_state(agent_id, {"index": index, "status": status})
                state = server.agent_get_state(agent_id)
                assert state["status"] == status

            server.agent_delete(agent_id)
            return True

        with ThreadPoolExecutor(max_workers=20) as executor:
            futures = [executor.submit(agent_lifecycle, i) for i in range(num_agents)]
            results = [f.result() for f in as_completed(futures)]

        assert all(results)
        assert server.list_agents() == []


# -----------------------------------------------------------------------------
# Content Service Integration Tests
# -----------------------------------------------------------------------------

class TestContentServiceIntegration:
    """Test WorkflowStateService integration with workflow patterns."""

    def test_content_stored_and_retrieved_once(self, content_service):
        """Content should be retrievable exactly once."""
        content_id = f"content-{uuid.uuid4().hex[:8]}"
        content = {"large": "data" * 1000}

        content_service.store_content(content_id, content)
        assert content_service.has_content(content_id)

        retrieved = content_service.get_content(content_id)
        assert retrieved == content
        assert content_service.has_content(content_id) is False

        # Second retrieval returns None
        assert content_service.get_content(content_id) is None

    def test_workflow_with_content_storage(self, server, content_service, workflow_id):
        """Test workflow storing content IDs for later retrieval."""
        # Start workflow
        server.workflow_start(workflow_id, {
            "phase": "implement",
            "content_ids": [],
        })

        # Simulate storing large tool results
        content_ids = []
        for i in range(3):
            content_id = f"result-{uuid.uuid4().hex[:8]}"
            content_ids.append(content_id)
            content_service.store_content(content_id, {
                "tool_output": f"Large output {i}" * 100,
                "timestamp": time.time(),
            })

        # Track content IDs in workflow
        server.workflow_set_value(workflow_id, "content_ids", content_ids)

        # Retrieve stored content IDs from workflow
        stored_ids = server.workflow_get_value(workflow_id, "content_ids")
        assert stored_ids == content_ids

        # Retrieve actual content
        for cid in stored_ids:
            content = content_service.get_content(cid)
            assert content is not None
            assert "tool_output" in content

        # Content should now be gone
        for cid in stored_ids:
            assert content_service.has_content(cid) is False

        server.workflow_stop(workflow_id)

    def test_concurrent_content_operations(self, content_service):
        """Test thread-safe content operations."""
        num_items = 100
        stored_ids = []

        def store_content(index):
            cid = f"concurrent-{index}"
            content_service.store_content(cid, {"index": index})
            stored_ids.append(cid)

        with ThreadPoolExecutor(max_workers=20) as executor:
            list(executor.map(store_content, range(num_items)))

        # All should be stored
        assert len(stored_ids) == num_items

        # Retrieve all (each only once)
        retrieved = []

        def retrieve_content(cid):
            result = content_service.get_content(cid)
            if result is not None:
                retrieved.append(cid)

        with ThreadPoolExecutor(max_workers=20) as executor:
            list(executor.map(retrieve_content, stored_ids))

        # Each content retrieved exactly once
        assert len(retrieved) == num_items


# -----------------------------------------------------------------------------
# State Isolation Tests
# -----------------------------------------------------------------------------

class TestStateIsolation:
    """Test that state changes are properly isolated with deepcopy."""

    def test_workflow_state_isolated_from_external_mutation(self, server, workflow_id):
        """Mutations to returned state should not affect stored state."""
        original = {"data": [1, 2, 3], "nested": {"key": "value"}}
        server.workflow_start(workflow_id, original)

        # Get state and mutate it
        state = server.workflow_get_state(workflow_id)
        state["data"].append(4)
        state["nested"]["key"] = "mutated"

        # Original should be unchanged (due to deepcopy)
        stored = server.workflow_get_state(workflow_id)
        assert stored["data"] == [1, 2, 3]
        assert stored["nested"]["key"] == "value"

        server.workflow_stop(workflow_id)

    def test_initial_state_isolated(self, server, workflow_id):
        """Mutations to initial_state dict should not affect workflow."""
        initial = {"mutable": [1, 2, 3]}
        server.workflow_start(workflow_id, initial)

        # Mutate the original dict
        initial["mutable"].append(4)

        # Workflow state should be unchanged
        state = server.workflow_get_state(workflow_id)
        assert state["mutable"] == [1, 2, 3]

        server.workflow_stop(workflow_id)

    def test_update_dict_isolated(self, server, workflow_id):
        """Mutations to update dict should not affect workflow after update."""
        server.workflow_start(workflow_id, {"base": "state"})

        updates = {"added": [1, 2, 3]}
        server.workflow_update(workflow_id, updates)

        # Mutate the updates dict
        updates["added"].append(4)

        # Workflow should be unchanged
        state = server.workflow_get_state(workflow_id)
        assert state["added"] == [1, 2, 3]

        server.workflow_stop(workflow_id)

    def test_agent_state_isolated(self, server):
        """Agent state should be isolated from external mutations."""
        agent_id = "test-agent"
        original = {"data": {"nested": "value"}}
        server.agent_set_state(agent_id, original)

        # Mutate original
        original["data"]["nested"] = "mutated"

        # Stored state should be unchanged
        stored = server.agent_get_state(agent_id)
        assert stored["data"]["nested"] == "value"

        # Mutate retrieved state
        stored["data"]["nested"] = "also mutated"

        # Should still be original
        final = server.agent_get_state(agent_id)
        assert final["data"]["nested"] == "value"

        server.agent_delete(agent_id)


# -----------------------------------------------------------------------------
# Error Propagation Tests
# -----------------------------------------------------------------------------

class TestErrorPropagation:
    """Test proper error handling across components."""

    def test_workflow_errors_dont_corrupt_state(self, server, workflow_id, initial_state):
        """Errors should not leave state in inconsistent condition."""
        server.workflow_start(workflow_id, initial_state)

        # Try to start again (should fail)
        try:
            server.workflow_start(workflow_id, {"new": "state"})
        except ValueError:
            pass

        # State should still be valid
        assert server.workflow_get_state(workflow_id) == initial_state

        # Try invalid update (should fail)
        try:
            server.workflow_update("nonexistent", {"bad": "update"})
        except ValueError:
            pass

        # Original workflow still valid
        assert server.workflow_get_state(workflow_id) == initial_state

        server.workflow_stop(workflow_id)

    def test_multiple_operations_after_error(self, server, workflow_id, initial_state):
        """Server should continue working after errors."""
        server.workflow_start(workflow_id, initial_state)

        # Cause some errors
        for _ in range(5):
            try:
                server.workflow_start(workflow_id, {})
            except ValueError:
                pass
            try:
                server.workflow_update("nonexistent", {})
            except ValueError:
                pass

        # Operations should still work
        server.workflow_update(workflow_id, {"still": "works"})
        assert server.workflow_get_value(workflow_id, "still") == "works"

        server.workflow_stop(workflow_id)


# -----------------------------------------------------------------------------
# Complex Scenario Tests
# -----------------------------------------------------------------------------

class TestComplexScenarios:
    """Test realistic complex workflow scenarios."""

    def test_orchestrator_with_subagents_scenario(self, server, content_service):
        """Simulate orchestrator managing multiple subagent workflows."""
        # Start orchestrator
        server.workflow_start("orchestrate", {
            "phase": "intake",
            "task": "Implement feature X",
            "subagents": [],
        })

        # Orchestrator spawns implementer
        implementer_id = f"sub-{uuid.uuid4().hex[:8]}"
        server.agent_set_state(implementer_id, {
            "type": "implementer",
            "task": "Write code for feature X",
            "status": "running",
        })

        # Track in orchestrator
        subagents = server.workflow_get_value("orchestrate", "subagents")
        subagents.append(implementer_id)
        server.workflow_set_value("orchestrate", "subagents", subagents)
        server.workflow_update("orchestrate", {"phase": "implement"})

        # Implementer produces output
        output_id = f"output-{uuid.uuid4().hex[:8]}"
        content_service.store_content(output_id, {
            "files_modified": ["src/feature.py", "tests/test_feature.py"],
            "diff": "... large diff ...",
        })

        # Update agent with output reference
        server.agent_set_state(implementer_id, {
            "type": "implementer",
            "task": "Write code for feature X",
            "status": "completed",
            "output_id": output_id,
        })

        # Orchestrator retrieves output
        agent_state = server.agent_get_state(implementer_id)
        assert agent_state["status"] == "completed"

        output = content_service.get_content(agent_state["output_id"])
        assert output["files_modified"] == ["src/feature.py", "tests/test_feature.py"]

        # Orchestrator moves to verify phase
        server.workflow_update("orchestrate", {"phase": "verify"})

        # Clean up
        server.agent_delete(implementer_id)
        server.workflow_stop("orchestrate")

    def test_workflow_phase_transitions(self, server, workflow_id):
        """Test realistic phase transitions with state changes."""
        phases = [
            ("intake", {"task": "Build API endpoint"}),
            ("design", {"approach": "REST with JSON", "files": ["api.py"]}),
            ("implement", {"iteration": 1, "tests_passing": False}),
            ("implement", {"iteration": 2, "tests_passing": True}),
            ("verify", {"lint_clean": True, "coverage": 85}),
            ("review", {"pr_number": 123}),
            ("complete", {"merged": True}),
        ]

        server.workflow_start(workflow_id, {"phase": "init"})

        for phase, updates in phases:
            server.workflow_update(workflow_id, {"phase": phase, **updates})
            state = server.workflow_get_state(workflow_id)
            assert state["phase"] == phase
            for key, value in updates.items():
                assert state[key] == value

        final_state = server.workflow_get_state(workflow_id)
        assert final_state["phase"] == "complete"
        assert final_state["merged"] is True

        server.workflow_stop(workflow_id)
