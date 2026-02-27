import os
import sys
import tempfile
from pathlib import Path
from copy import deepcopy
from typing import Any, Optional

import pytest

# Add directories to path for imports
# Add parent dir so 'lib' works as a package (from lib.config import X)
sys.path.insert(0, str(Path(__file__).parent.parent))
# Also add lib directly for legacy imports (from config import X)
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
# Workflow State Mock
# ============================================================================
# This mock replaces DaemonClient and workflow_client to avoid requiring
# the MCP router daemon. All tests get this mock automatically via autouse=True.

class MockWorkflowState:
    """In-memory mock for workflow state management."""

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
        # Auto-create workflow if not exists (lenient for tests)
        if workflow_id not in self.workflows:
            self.workflows[workflow_id] = {}
        self.workflows[workflow_id][key] = deepcopy(value)
        return deepcopy(value)

    def workflow_advance_phase(self, workflow_id: str, target_phase: str) -> dict:
        if workflow_id not in self.workflows:
            self.workflows[workflow_id] = {}
        self.workflows[workflow_id]["phase"] = target_phase
        return {"status": "advanced", "phase": target_phase}

    def workflow_pass_checkpoint(self, workflow_id: str) -> dict:
        if workflow_id not in self.workflows:
            raise ValueError(f"Workflow '{workflow_id}' not found")
        phase = self.workflows[workflow_id].get("phase", "")
        self.workflows[workflow_id][f"{phase}_checkpoint_passed"] = True
        return {"status": "passed", "phase": phase}

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


class MockDaemonClient:
    """Mock DaemonClient that delegates to MockWorkflowState.

    Supports context manager protocol (with DaemonClient() as dc:).
    """

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def connect(self):
        pass

    def close(self):
        pass

    def register(self, *args, **kwargs):
        return {"agent_id": "test", "roles": []}

    # Workflow operations
    def workflow_start(self, workflow_id, initial_state=None):
        return _mock_state.workflow_start(workflow_id, initial_state)

    def workflow_stop(self, workflow_id):
        return _mock_state.workflow_stop(workflow_id)

    def workflow_is_active(self, workflow_id):
        return _mock_state.workflow_is_active(workflow_id)

    def workflow_get_state(self, workflow_id):
        return _mock_state.workflow_get_state(workflow_id)

    def workflow_get_value(self, workflow_id, key, default=None):
        return _mock_state.workflow_get_value(workflow_id, key, default)

    def workflow_set_value(self, workflow_id, key, value):
        return _mock_state.workflow_set_value(workflow_id, key, value)

    def workflow_advance_phase(self, workflow_id, target_phase):
        return _mock_state.workflow_advance_phase(workflow_id, target_phase)

    def workflow_pass_checkpoint(self, workflow_id):
        return _mock_state.workflow_pass_checkpoint(workflow_id)

    def workflow_set_state(self, workflow_id, state):
        """Test convenience: bulk set state (not on real DaemonClient)."""
        return _mock_state.workflow_set_state(workflow_id, state)

    def workflow_update(self, workflow_id, updates):
        """Test convenience: update state (not on real DaemonClient)."""
        return _mock_state.workflow_update(workflow_id, updates)

    # Agent operations
    def agent_get_state(self, agent_id):
        return _mock_state.agent_get_state(agent_id)

    def agent_set_state(self, agent_id, state):
        return _mock_state.agent_set_state(agent_id, state)

    def agent_delete(self, agent_id):
        return _mock_state.agent_delete(agent_id)

    def list_agents(self):
        return _mock_state.list_agents()

    def list_tools(self):
        return []


# Modules that import DaemonClient at module level and need patching
_DAEMON_CLIENT_MODULES = [
    "daemon_client",
    "workflow_base", "debug_workflow", "pr_comment_workflow",
    "implementer_workflow", "develop_workflow", "iterate_workflow",
    "orchestrate", "permission_query", "agent_recovery",
    "review_gate", "worker_pool", "protocol_assembly",
]


@pytest.fixture(autouse=True)
def mock_workflow_client(monkeypatch):
    """Mock DaemonClient and workflow_client to avoid requiring daemon.

    This fixture is autouse=True, so all tests get mocked state
    automatically. Each test gets isolated state via reset().
    """
    # Reset state before each test
    _mock_state.reset()

    # Patch DaemonClient in all modules that import it
    # Check both bare names (e.g. "review_gate") and lib-prefixed names
    # (e.g. "lib.review_gate") since tests may import either way
    for mod_name in _DAEMON_CLIENT_MODULES:
        for variant in (mod_name, f"lib.{mod_name}"):
            mod = sys.modules.get(variant)
            if mod and hasattr(mod, "DaemonClient"):
                monkeypatch.setattr(mod, "DaemonClient", MockDaemonClient)

    yield _mock_state


# ============================================================================
# Parallel Orchestration Fixtures
# ============================================================================
# These fixtures support tests for the parallel-orchestrate subsystem
# (manifest-driven CLI orchestration, separate from MCP router workflows).

@pytest.fixture
def tmp_state_dir(tmp_path):
    """Provide an isolated state directory for parallel orchestration tests."""
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    old = os.environ.get("ORCHESTRATION_STATE_DIR")
    os.environ["ORCHESTRATION_STATE_DIR"] = str(state_dir)
    yield state_dir
    if old is None:
        os.environ.pop("ORCHESTRATION_STATE_DIR", None)
    else:
        os.environ["ORCHESTRATION_STATE_DIR"] = old


@pytest.fixture
def tmp_manifest_file(tmp_path):
    """Create a temporary YAML manifest file."""
    def _create(content: str) -> str:
        path = tmp_path / "manifest.yaml"
        path.write_text(content)
        return str(path)
    return _create


@pytest.fixture
def sample_manifest_yaml():
    """Return a valid manifest YAML string."""
    return """\
project: test-project
base_branch: main
tasks:
  - name: stack
    description: "Implement a stack data structure"
    target_dir: src/stack
    test_dir: tests/test_stack
    min_tests: 10
  - name: queue
    description: "Implement a queue data structure"
    target_dir: src/queue
    test_dir: tests/test_queue
    min_tests: 10
"""
