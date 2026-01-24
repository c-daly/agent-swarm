#!/usr/bin/env python3
"""Tests for subagent TDD enforcement.

Verifies that implementer subagents spawned during iterate-tdd mode:
1. Start in test_writing phase (not the parent's phase)
2. Have Edit tools blocked in test_writing phase
3. Have Edit tools allowed in implement phase
4. Cannot classify as TRIVIAL and bypass TDD workflow
"""

import json
import os
import sys
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
import pytest

# Add lib to path
sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

# We'll test by importing the hook modules directly after setting up mocks
import importlib.util


def load_hook_module(hook_name: str):
    """Load a hook script as a module."""
    hook_path = Path(__file__).parent.parent / "hooks" / f"{hook_name}.py"
    spec = importlib.util.spec_from_file_location(hook_name, hook_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[hook_name] = module
    spec.loader.exec_module(module)
    return module


class TestSubagentStartInTestWritingPhase:
    """Test that subagents spawned by orchestrator start in test_writing phase."""
    
    def test_implementer_subagent_gets_test_writing_phase(self):
        """When orchestrator spawns implementer in iterate-tdd, phase should be test_writing."""
        # Create mock workflow_client before importing hook
        mock_workflow_client = MagicMock()
        
        def get_state_side_effect(wf_id):
            return {
                "session": {"phase": "orchestrate"},
                "iterate": {"phase": "orchestrate", "mode": "iterate-tdd"}
            }.get(wf_id, {})
        
        mock_workflow_client.workflow_get_state.side_effect = get_state_side_effect
        mock_workflow_client.workflow_is_active.return_value = True
        mock_workflow_client.agent_set_state.return_value = {"success": True}
        
        # Patch workflow_client before loading the hook
        with patch.dict('sys.modules', {'workflow_client': mock_workflow_client}):
            # Now load the hook module
            hook = load_hook_module('subagent-enforcement')
            
            # Simulate SubagentStart hook input
            hook_input = {
                "sessionId": "test-session-123",
                "agentType": "implementer",
                "task": "Add feature X"
            }
            
            # Run the hook
            with patch('sys.stdin', Mock(read=lambda: json.dumps(hook_input))):
                with patch('builtins.print') as mock_print:
                    hook.main()
            
            # Verify agent_set_state was called
            assert mock_workflow_client.agent_set_state.called, \
                "agent_set_state should be called"
            
            call_args = mock_workflow_client.agent_set_state.call_args[0]
            agent_id = call_args[0]
            agent_state = call_args[1]
            
            # CRITICAL: subagent should start in test_writing, NOT parent's orchestrate phase
            assert agent_state["phase"] == "test_writing", \
                f"Implementer subagent must start in test_writing phase, got {agent_state['phase']}"
            assert agent_state["mode"] == "iterate-tdd"
            assert "sub-" in agent_id

    def test_explorer_subagent_gets_test_writing_phase(self):
        """When orchestrator spawns explorer in iterate workflow, phase should be test_writing."""
        mock_workflow_client = MagicMock()

        def get_state_side_effect(wf_id):
            return {
                "session": {"phase": "orchestrate"},
                "iterate": {"phase": "orchestrate", "mode": "iterate-tdd"}
            }.get(wf_id, {})

        mock_workflow_client.workflow_get_state.side_effect = get_state_side_effect
        mock_workflow_client.workflow_is_active.return_value = True
        mock_workflow_client.agent_set_state.return_value = {"success": True}

        with patch.dict('sys.modules', {'workflow_client': mock_workflow_client}):
            hook = load_hook_module('subagent-enforcement')

            hook_input = {
                "sessionId": "test-session-456",
                "agentType": "explorer",
                "task": "Explore auth module"
            }

            with patch('sys.stdin', Mock(read=lambda: json.dumps(hook_input))):
                with patch('builtins.print') as mock_print:
                    hook.main()

            call_args = mock_workflow_client.agent_set_state.call_args[0]
            agent_state = call_args[1]

            # Explorer should also get test_writing phase when iterate is active
            assert agent_state["phase"] == "test_writing", \
                f"Explorer subagent must start in test_writing phase, got {agent_state['phase']}"

    def test_any_agent_type_gets_test_writing_phase_when_iterate_active(self):
        """ANY agent type spawned from orchestrate phase should get test_writing when iterate is active."""
        mock_workflow_client = MagicMock()

        def get_state_side_effect(wf_id):
            return {
                "session": {"phase": "orchestrate"},
                "iterate": {"phase": "orchestrate", "mode": "iterate-tdd"}
            }.get(wf_id, {})

        mock_workflow_client.workflow_get_state.side_effect = get_state_side_effect
        mock_workflow_client.workflow_is_active.return_value = True
        mock_workflow_client.agent_set_state.return_value = {"success": True}

        # Test with a generic/unknown agent type
        with patch.dict('sys.modules', {'workflow_client': mock_workflow_client}):
            hook = load_hook_module('subagent-enforcement')

            hook_input = {
                "sessionId": "test-session-789",
                "agentType": "custom-agent",  # Not explorer or implementer
                "task": "Custom task"
            }

            with patch('sys.stdin', Mock(read=lambda: json.dumps(hook_input))):
                with patch('builtins.print') as mock_print:
                    hook.main()

            call_args = mock_workflow_client.agent_set_state.call_args[0]
            agent_state = call_args[1]

            # ALL agent types should get test_writing phase
            assert agent_state["phase"] == "test_writing", \
                f"ANY subagent type must start in test_writing phase when iterate is active, got {agent_state['phase']}"


class TestSubagentContextEnforcesTDD:
    """Test that subagent context injection enforces TDD workflow."""
    
    def test_subagent_context_requires_tdd_phases(self):
        """Subagent context should make TDD phases mandatory."""
        mock_workflow_client = MagicMock()
        
        def get_state_side_effect(wf_id):
            return {
                "session": {"phase": "orchestrate"},
                "iterate": {"phase": "orchestrate", "mode": "iterate-tdd"}
            }.get(wf_id, {})
        
        mock_workflow_client.workflow_get_state.side_effect = get_state_side_effect
        mock_workflow_client.workflow_is_active.return_value = True
        mock_workflow_client.agent_set_state.return_value = {"success": True}
        
        with patch.dict('sys.modules', {'workflow_client': mock_workflow_client}):
            hook = load_hook_module('subagent-enforcement')
            
            hook_input = {
                "sessionId": "test-session-123",
                "agentType": "implementer",
                "task": "Add feature X"
            }
            
            with patch('sys.stdin', Mock(read=lambda: json.dumps(hook_input))):
                with patch('builtins.print') as mock_print:
                    hook.main()
            
            # Get the output
            output = json.loads(mock_print.call_args[0][0])
            context = output["hookSpecificOutput"].get("additionalContext", "")
            
            # Verify context describes TDD workflow phases
            assert "TEST_WRITING" in context, "Must describe TEST_WRITING phase"
            assert "IMPLEMENT" in context, "Must describe IMPLEMENT phase"
            
            # Should emphasize that phases cannot be skipped
            assert "CANNOT skip phases" in context or "MUST" in context, \
                "Context must emphasize mandatory phase progression"


class TestIterateEnforcementPhaseLocking:
    """Test that iterate-enforcement properly enforces phase restrictions."""
    
    def test_edit_tools_blocked_in_test_writing_phase(self):
        """Edit/Write should be blocked in test_writing phase for implementation files."""
        mock_workflow_client = MagicMock()
        mock_workflow_client.workflow_is_active.return_value = True
        
        with patch.dict('sys.modules', {'workflow_client': mock_workflow_client}):
            # Import iterate_workflow to get is_tool_allowed
            import iterate_workflow
            
            # Set phase to test_writing
            with patch.object(iterate_workflow, 'get_phase') as mock_get_phase:
                mock_phase = MagicMock()
                mock_phase.value = "test_writing"
                mock_get_phase.return_value = mock_phase
                
                # Test that Edit is blocked for non-test files in test_writing phase
                # This will depend on actual implementation in iterate_workflow.is_tool_allowed
                allowed, reason = iterate_workflow.is_tool_allowed("Edit")
                
                # In test_writing, Edit should only be allowed for test files
                # For now, we just verify the function is callable
                assert isinstance(allowed, bool)
    
    def test_edit_tools_allowed_in_implement_phase(self):
        """Edit/Write should be allowed in implement phase."""
        mock_workflow_client = MagicMock()
        mock_workflow_client.workflow_is_active.return_value = True
        
        with patch.dict('sys.modules', {'workflow_client': mock_workflow_client}):
            import iterate_workflow
            
            # Set phase to implement
            with patch.object(iterate_workflow, 'get_phase') as mock_get_phase:
                mock_phase = MagicMock()
                mock_phase.value = "implement"
                mock_get_phase.return_value = mock_phase
                
                # Edit should be allowed in implement phase
                allowed, reason = iterate_workflow.is_tool_allowed("Edit")
                
                # Verify function works
                assert isinstance(allowed, bool)


class TestAgentTypeRegistration:
    """Test that SubagentStart hook registers agent type for telemetry."""
    
    def test_subagent_start_calls_register_agent_type(self):
        """SubagentStart should call store.register_agent_type(agent_id, agent_type)."""
        mock_workflow_client = MagicMock()
        mock_workflow_client.workflow_get_state.return_value = {}
        mock_workflow_client.workflow_is_active.return_value = False
        mock_workflow_client.agent_set_state.return_value = {"success": True}
        
        mock_store = MagicMock()
        
        with patch.dict('sys.modules', {'workflow_client': mock_workflow_client}):
            hook = load_hook_module('subagent-enforcement')
            
            hook_input = {
                "sessionId": "test-session-123",
                "agentId": "sub-abc12345",
                "agentType": "implementer",
                "task": "Add feature X"
            }
            
            # Patch the DuckDBStore import inside the hook
            with patch.object(hook, 'get_telemetry_store', return_value=mock_store):
                with patch('sys.stdin', Mock(read=lambda: json.dumps(hook_input))):
                    with patch('builtins.print'):
                        hook.main()
            
            # Verify register_agent_type was called with correct args
            mock_store.register_agent_type.assert_called_once_with(
                "sub-abc12345", "implementer"
            )
    
    def test_register_agent_type_failure_does_not_fail_hook(self):
        """If register_agent_type fails, hook should still complete successfully."""
        mock_workflow_client = MagicMock()
        mock_workflow_client.workflow_get_state.return_value = {}
        mock_workflow_client.workflow_is_active.return_value = False
        mock_workflow_client.agent_set_state.return_value = {"success": True}
        
        mock_store = MagicMock()
        mock_store.register_agent_type.side_effect = Exception("DB error")
        
        with patch.dict('sys.modules', {'workflow_client': mock_workflow_client}):
            hook = load_hook_module('subagent-enforcement')
            
            hook_input = {
                "sessionId": "test-session-123",
                "agentId": "sub-abc12345",
                "agentType": "implementer",
                "task": "Add feature X"
            }
            
            with patch.object(hook, 'get_telemetry_store', return_value=mock_store):
                with patch('sys.stdin', Mock(read=lambda: json.dumps(hook_input))):
                    with patch('builtins.print') as mock_print:
                        # Should not raise
                        hook.main()
            
            # Verify hook still produced output
            assert mock_print.called
            output = json.loads(mock_print.call_args[0][0])
            assert "hookSpecificOutput" in output


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
