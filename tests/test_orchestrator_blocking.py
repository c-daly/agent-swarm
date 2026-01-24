"""Tests for orchestrator blocking of editing tools."""

import json
import subprocess
import tempfile
from pathlib import Path

HOOK_PATH = Path(__file__).parent.parent / "hooks" / "iterate-enforcement.py"
LIB_DIR = Path(__file__).parent.parent / "lib"

# Test runner script that mocks the workflow modules
TEST_RUNNER_TEMPLATE = '''#!/usr/bin/env python3
import sys
import json
from pathlib import Path
from types import ModuleType

# Create mock modules BEFORE they can be imported by the hook
mock_iterate_workflow = ModuleType("iterate_workflow")
mock_iterate_workflow.is_active = lambda: True
mock_iterate_workflow.is_tool_allowed = lambda tool, command=None: (True, "")
mock_iterate_workflow.get_phase = lambda: None
sys.modules["iterate_workflow"] = mock_iterate_workflow

mock_workflow_client = ModuleType("workflow_client")
mock_workflow_client.agent_get_state = lambda x: None
mock_workflow_client.workflow_get_state = lambda x: {{"active": True}}
sys.modules["workflow_client"] = mock_workflow_client

# Now exec the hook - it will use our mocked modules
hook_path = Path("{hook_path}")
hook_code = hook_path.read_text()

# Create namespace
namespace = {{
    "__name__": "__main__",
    "__file__": str(hook_path),
}}
exec(compile(hook_code, str(hook_path), "exec"), namespace)
'''


def run_hook_with_active_workflow(tool_name: str, agent_id: str | None = None, tool_input: dict | None = None) -> dict:
    """Run the iterate-enforcement hook with workflow mocked as active.
    
    Uses a temporary script file to properly mock the modules.
    """
    input_data = {
        "tool_name": tool_name,
        "tool_input": tool_input or {},
    }
    if agent_id is not None:
        input_data["agentId"] = agent_id
    
    # Write the test runner script
    test_script = TEST_RUNNER_TEMPLATE.format(hook_path=HOOK_PATH)
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
        f.write(test_script)
        script_path = f.name
    
    try:
        result = subprocess.run(
            ["python3", script_path],
            input=json.dumps(input_data),
            capture_output=True,
            text=True,
            timeout=10,
        )
        
        if result.returncode != 0 and not result.stdout:
            raise RuntimeError(f"Hook failed: {result.stderr}")
        
        # Get just stdout (skip stderr debug lines)
        return json.loads(result.stdout.strip())
    finally:
        Path(script_path).unlink(missing_ok=True)


def is_blocked(result: dict) -> bool:
    """Check if the hook blocked the tool."""
    return result.get("hookSpecificOutput", {}).get("permissionDecision") == "deny"


def get_reason(result: dict) -> str:
    """Get the block reason from result."""
    return result.get("hookSpecificOutput", {}).get("permissionDecisionReason", "")


class TestOrchestratorBlocking:
    """Test that orchestrator (no agent_id) cannot use editing tools."""

    def test_edit_blocked_when_no_agent_id(self):
        """Edit tool should be blocked when called without agent_id."""
        result = run_hook_with_active_workflow("Edit", agent_id=None)
        assert is_blocked(result), f"Edit should be blocked, got: {result}"
        assert "[ORCHESTRATOR]" in get_reason(result)
        assert "reserved for subagents" in get_reason(result)

    def test_write_blocked_when_no_agent_id(self):
        """Write tool should be blocked when called without agent_id."""
        result = run_hook_with_active_workflow("Write", agent_id=None)
        assert is_blocked(result), f"Write should be blocked, got: {result}"
        assert "[ORCHESTRATOR]" in get_reason(result)
        assert "reserved for subagents" in get_reason(result)

    def test_notebookedit_blocked_when_no_agent_id(self):
        """NotebookEdit tool should be blocked when called without agent_id."""
        result = run_hook_with_active_workflow("NotebookEdit", agent_id=None)
        assert is_blocked(result), f"NotebookEdit should be blocked, got: {result}"
        assert "[ORCHESTRATOR]" in get_reason(result)
        assert "reserved for subagents" in get_reason(result)

    def test_read_allowed_when_no_agent_id(self):
        """Read tool should NOT be blocked for orchestrator."""
        result = run_hook_with_active_workflow("Read", agent_id=None)
        assert not is_blocked(result), f"Read should be allowed, got: {result}"

    def test_edit_allowed_when_agent_id_present(self):
        """Edit tool should take different path when agent_id is present.
        
        Note: This tests that the orchestrator blocking doesn't apply when
        there's an agent_id. The actual permission depends on agent phase.
        """
        result = run_hook_with_active_workflow("Edit", agent_id="test-agent-123")
        # Should NOT contain orchestrator blocking message
        reason = get_reason(result)
        assert "[ORCHESTRATOR]" not in reason, f"Should not be orchestrator blocking: {reason}"


if __name__ == "__main__":
    # Run tests manually
    test = TestOrchestratorBlocking()
    
    print("Testing Edit blocked when no agent_id...")
    test.test_edit_blocked_when_no_agent_id()
    print("  PASSED")
    
    print("Testing Write blocked when no agent_id...")
    test.test_write_blocked_when_no_agent_id()
    print("  PASSED")
    
    print("Testing NotebookEdit blocked when no agent_id...")
    test.test_notebookedit_blocked_when_no_agent_id()
    print("  PASSED")
    
    print("Testing Read allowed when no agent_id...")
    test.test_read_allowed_when_no_agent_id()
    print("  PASSED")
    
    print("Testing Edit allowed when agent_id present...")
    test.test_edit_allowed_when_agent_id_present()
    print("  PASSED")
    
    print("\nAll tests passed!")
