import os
import sys
import tempfile
from pathlib import Path
from copy import deepcopy
from typing import Any, Optional
from unittest.mock import MagicMock

import pytest

# Add directories to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))
sys.path.insert(0, str(Path(__file__).parent.parent / "hooks"))
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

# Create isolated state directory for tests BEFORE importing iterate_workflow
# This prevents tests from destroying production state (WORKFLOW.11 fix)
_test_state_dir = tempfile.mkdtemp(prefix="iterate_test_state_")
os.environ["ITERATE_STATE_DIR"] = _test_state_dir


@pytest.fixture(scope="session", autouse=True)
def cleanup_test_state_dir():
    """Clean up the test state directory after all tests complete."""
    yield
    # Cleanup after all tests
    import shutil
    if os.path.exists(_test_state_dir):
        shutil.rmtree(_test_state_dir, ignore_errors=True)


# ============================================================================
# Workflow Client Mock
# ============================================================================
# This mock replaces workflow_client functions to avoid requiring MCP router.
# All tests get this mock automatically via autouse=True.

class MockWorkflowState:
    """In-memory mock for workflow_client state management."""

    def __init__(self):
        self.workflows: dict[str, dict[str, Any]] = {}
        self.agents: dict[str, dict[str, Any]] = {}

    def reset(self):
        """Reset all state."""
        self.workflows.clear()
        self.agents.clear()

    # Workflow operations
    def workflow_start(self, workflow_id: str, initial_state: Optional[dict] = None) -> dict:
        if workflow_id in self.workflows:
            raise ValueError(f"Workflow '{workflow_id}' already exists")
        self.workflows[workflow_id] = deepcopy(initial_state) if initial_state else {}
        return deepcopy(self.workflows[workflow_id])

    def workflow_stop(self, workflow_id: str) -> bool:
        if workflow_id in self.workflows:
            del self.workflows[workflow_id]
            return True
        return False

    def workflow_is_active(self, workflow_id: str) -> bool:
        return workflow_id in self.workflows

    def workflow_get_state(self, workflow_id: str) -> Optional[dict]:
        if workflow_id not in self.workflows:
            return None
        return deepcopy(self.workflows[workflow_id])

    def workflow_set_state(self, workflow_id: str, state: dict) -> dict:
        self.workflows[workflow_id] = deepcopy(state)
        return deepcopy(self.workflows[workflow_id])

    def workflow_update(self, workflow_id: str, updates: dict) -> dict:
        if workflow_id not in self.workflows:
            raise ValueError(f"Workflow '{workflow_id}' not found")
        self.workflows[workflow_id].update(deepcopy(updates))
        return deepcopy(self.workflows[workflow_id])

    def workflow_get_value(self, workflow_id: str, key: str, default: Any = None) -> Any:
        if workflow_id not in self.workflows:
            return default
        return deepcopy(self.workflows[workflow_id].get(key, default))

    def workflow_set_value(self, workflow_id: str, key: str, value: Any) -> Any:
        if workflow_id not in self.workflows:
            raise ValueError(f"Workflow '{workflow_id}' not found")
        self.workflows[workflow_id][key] = deepcopy(value)
        return deepcopy(value)

    # Agent operations
    def agent_get_state(self, agent_id: str) -> Optional[dict]:
        if agent_id not in self.agents:
            return None
        return deepcopy(self.agents[agent_id])

    def agent_set_state(self, agent_id: str, state: dict) -> dict:
        self.agents[agent_id] = deepcopy(state)
        return deepcopy(self.agents[agent_id])

    def agent_delete(self, agent_id: str) -> bool:
        if agent_id in self.agents:
            del self.agents[agent_id]
            return True
        return False

    def list_agents(self) -> list[str]:
        return list(self.agents.keys())


# Global mock state instance
_mock_state = MockWorkflowState()


@pytest.fixture(autouse=True)
def mock_workflow_client(monkeypatch):
    """Mock workflow_client functions to avoid requiring MCP router.

    This fixture is autouse=True, so all tests get mocked workflow_client
    automatically. Each test gets isolated state via reset().
    """
    # Reset state before each test
    _mock_state.reset()

    # Import workflow_client to patch it
    import workflow_client

    # Patch all workflow_client functions
    monkeypatch.setattr(workflow_client, "workflow_start", _mock_state.workflow_start)
    monkeypatch.setattr(workflow_client, "workflow_stop", _mock_state.workflow_stop)
    monkeypatch.setattr(workflow_client, "workflow_is_active", _mock_state.workflow_is_active)
    monkeypatch.setattr(workflow_client, "workflow_get_state", _mock_state.workflow_get_state)
    monkeypatch.setattr(workflow_client, "workflow_set_state", _mock_state.workflow_set_state)
    monkeypatch.setattr(workflow_client, "workflow_update", _mock_state.workflow_update)
    monkeypatch.setattr(workflow_client, "workflow_get_value", _mock_state.workflow_get_value)
    monkeypatch.setattr(workflow_client, "workflow_set_value", _mock_state.workflow_set_value)
    monkeypatch.setattr(workflow_client, "agent_get_state", _mock_state.agent_get_state)
    monkeypatch.setattr(workflow_client, "agent_set_state", _mock_state.agent_set_state)
    monkeypatch.setattr(workflow_client, "agent_delete", _mock_state.agent_delete)
    monkeypatch.setattr(workflow_client, "list_agents", _mock_state.list_agents)

    yield _mock_state
