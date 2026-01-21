# Anti-Pattern Detection: Implementation Guide

This guide shows where and how to add new anti-pattern detection logic to the enforcement framework.

---

## Current Detection Architecture

```
┌─ PreToolUse Hooks (block/allow execution)
│  ├─ base-enforcement.py          (no workflow = no edit)
│  ├─ iterate-enforcement.py       (phase-based restrictions)
│  ├─ parallel-enforcement.py      (sequential task spawning)
│  ├─ background-enforcement.py    (run_in_background flag)
│  ├─ monitor_agent.py             (contextual validation)
│  └─ [NEW HOOKS HERE]
│
├─ PostToolUse Hooks (telemetry only)
│  ├─ post-task-tracking.py        (log subagent completion)
│  └─ [NEW HOOKS HERE]
│
└─ Session Hooks (lifecycle)
   ├─ session-start.py             (init telemetry)
   └─ session-end.py               (cleanup)
```

---

## Implementation Pattern: New Anti-Pattern Detection

### Step 1: Identify the Pattern

**Example:** Detect subagent making >100 tool calls (likely infinite loop)

**Signal:** Task tool output shows agent_id with call_count > 100
**When:** PostToolUse phase (after Task tool returns)
**Action:** Log warning + suggest investigation

### Step 2: Create Hook File

**File:** `/hooks/token-overflow-detection.py`

```python
#!/usr/bin/env python3
"""PostToolUse hook to detect infinite loops via excessive tool calls.

Signals when subagent makes excessive tool calls (>100) which typically
indicates infinite loops, runaway recursion, or stuck retry logic.
"""

import json
import sys
import re
from pathlib import Path
from datetime import datetime

# Try to import telemetry logging
try:
    from hook_logging import log_warning, log_info, log_debug
except ImportError:
    def log_warning(msg, **kw): pass
    def log_info(msg, **kw): pass
    def log_debug(msg, **kw): pass


def extract_call_count(tool_output: str | dict) -> int:
    """Extract tool call count from Task tool output.
    
    Looks for patterns like:
    - "call_count: 156"
    - "Tool calls made: 156"
    - "[156 calls]"
    """
    if isinstance(tool_output, dict):
        # Modern format: check for call_count key
        if "call_count" in tool_output:
            try:
                return int(tool_output["call_count"])
            except (ValueError, TypeError):
                pass
        
        # Check in text representation
        tool_output = json.dumps(tool_output)
    
    # Pattern matching for legacy formats
    patterns = [
        r'call_count["\s:]*(\d+)',
        r'Tool calls made["\s:]*(\d+)',
        r'\[(\d+)\s*calls?\]',
        r'tool calls:\s*(\d+)',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, str(tool_output), re.IGNORECASE)
        if match:
            try:
                return int(match.group(1))
            except (ValueError, IndexError):
                pass
    
    return 0


def is_excessive_calls(call_count: int, threshold: int = 100) -> bool:
    """Check if call count exceeds threshold."""
    return call_count > threshold


def main():
    """PostToolUse hook main."""
    try:
        input_data = json.loads(sys.stdin.read())
    except json.JSONDecodeError:
        # No valid input - allow through
        print(json.dumps({"hookSpecificOutput": {}}))
        return
    
    tool_name = input_data.get("tool_name", "")
    tool_output = input_data.get("tool_response", "")
    tool_input = input_data.get("tool_input", {})
    
    # Only check Task tool
    if tool_name != "Task":
        print(json.dumps({"hookSpecificOutput": {}}))
        return
    
    # Extract call count from output
    call_count = extract_call_count(tool_output)
    
    if not call_count:
        print(json.dumps({"hookSpecificOutput": {}}))
        return
    
    # Check for excessive calls
    if is_excessive_calls(call_count, threshold=100):
        agent_id = tool_input.get("subagent_type", "unknown")
        
        log_warning(
            f"Excessive tool calls detected",
            agent_id=agent_id,
            call_count=call_count,
            threshold=100
        )
        
        # Return informational message (don't block - already completed)
        output = {
            "hookSpecificOutput": {
                "message": (
                    f"⚠️ [TOKEN_OVERFLOW] Subagent made {call_count} tool calls (threshold: 100).\\n"
                    f"This may indicate an infinite loop or stuck retry logic.\\n"
                    f"Consider investigating the subagent output for errors."
                )
            }
        }
    else:
        output = {"hookSpecificOutput": {}}
    
    print(json.dumps(output))


if __name__ == "__main__":
    main()
```

### Step 3: Add Test File

**File:** `/tests/test_token_overflow_detection.py`

```python
#!/usr/bin/env python3
"""Tests for token-overflow-detection.py hook."""

import json
import sys
from pathlib import Path
from unittest.mock import patch
import pytest
import importlib.util

# Load hook module
hook_path = Path(__file__).parent.parent / "hooks" / "token-overflow-detection.py"
spec = importlib.util.spec_from_file_location("token_overflow", hook_path)
token_overflow = importlib.util.module_from_spec(spec)
sys.modules["token_overflow"] = token_overflow
spec.loader.exec_module(token_overflow)


def run_hook(tool_name="Task", tool_output="", tool_input=None):
    """Helper to run hook with test input."""
    if tool_input is None:
        tool_input = {"subagent_type": "implementer"}
    
    input_data = {
        "tool_name": tool_name,
        "tool_response": tool_output,
        "tool_input": tool_input
    }
    
    output = []
    with patch("sys.stdin.read", return_value=json.dumps(input_data)):
        with patch("builtins.print", side_effect=lambda x: output.append(x)):
            token_overflow.main()
    
    return json.loads(output[0]) if output else {}


def test_normal_call_count_allowed():
    """Normal tool call count should not trigger warning."""
    result = run_hook(
        tool_output={"call_count": 50, "status": "complete"}
    )
    
    # Should be empty output (no warning)
    assert result.get("hookSpecificOutput", {}).get("message") is None


def test_excessive_calls_warning():
    """Excessive tool calls should trigger warning."""
    result = run_hook(
        tool_output={"call_count": 156, "status": "complete"}
    )
    
    message = result.get("hookSpecificOutput", {}).get("message", "")
    assert "TOKEN_OVERFLOW" in message
    assert "156" in message
    assert "infinite loop" in message.lower()


def test_call_count_extraction_dict():
    """Should extract call_count from dict format."""
    count = token_overflow.extract_call_count({"call_count": 123})
    assert count == 123


def test_call_count_extraction_pattern():
    """Should extract call_count from string patterns."""
    cases = [
        ("call_count: 150", 150),
        ("Tool calls made: 200", 200),
        ("[75 calls]", 75),
        ("tool calls: 89", 89),
    ]
    
    for text, expected in cases:
        count = token_overflow.extract_call_count(text)
        assert count == expected, f"Failed for: {text}"


def test_non_task_tool_ignored():
    """Non-Task tools should be ignored."""
    result = run_hook(tool_name="Read", tool_output={"call_count": 500})
    
    # No warning message
    assert result.get("hookSpecificOutput", {}).get("message") is None


def test_threshold_customization():
    """Should respect custom threshold."""
    # At threshold: no warning
    assert not token_overflow.is_excessive_calls(100, threshold=100)
    
    # Above threshold: warning
    assert token_overflow.is_excessive_calls(101, threshold=100)
```

### Step 4: Register Hook in Plugin Config

**File:** `plugin.json` (Hook registration)

```json
{
  "hooks": [
    {
      "name": "token-overflow-detection",
      "event": "PostToolUse",
      "script": "hooks/token-overflow-detection.py",
      "description": "Detect excessive tool calls indicating infinite loops"
    }
  ]
}
```

---

## Pattern 2: Phase Transition Violation Detection

**Example:** Detect backwards phase transitions (implement → test_writing)

### Hook File

**File:** `/hooks/phase-transition-validation.py`

```python
#!/usr/bin/env python3
"""PreToolUse hook to detect invalid phase transitions.

Prevents agents from:
- Going backwards (implement → test_writing)
- Skipping phases (test_writing → review)
- Using tools from wrong phases
"""

import json
import sys
from pathlib import Path
from enum import Enum

sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

try:
    from workflow_client import workflow_get_state, agent_get_state
    from phase_model import ITERATE_PHASES
except ImportError:
    workflow_get_state = lambda wf: {}
    agent_get_state = lambda aid: {}
    ITERATE_PHASES = {}


# Phase ordering (earlier phases come first)
PHASE_ORDER = ["test_writing", "implement", "test", "review"]


def get_current_agent_phase() -> str:
    """Get current agent's phase from workflow state."""
    # For subagents, get from agent state
    # For orchestrator, get from iterate state
    try:
        # Try to determine agent_id from context
        # This would be injected by subagent-enforcement.py
        agent_state = agent_get_state("current_agent")
        if agent_state:
            return agent_state.get("phase")
    except Exception:
        pass
    
    # Fallback to iterate workflow state
    try:
        iterate_state = workflow_get_state("iterate")
        if iterate_state:
            return iterate_state.get("phase")
    except Exception:
        pass
    
    return None


def can_transition(from_phase: str, to_phase: str) -> bool:
    """Check if phase transition is valid.
    
    Valid transitions:
    - test_writing → implement
    - implement → test
    - test → review
    - test → implement (retry if tests failed)
    - review → test_writing (new iteration)
    """
    valid_transitions = {
        "test_writing": {"implement"},
        "implement": {"test"},
        "test": {"review", "implement"},  # Can retry implement if tests fail
        "review": {"test_writing"},  # Start new iteration
    }
    
    return to_phase in valid_transitions.get(from_phase, set())


def main():
    """PreToolUse hook main."""
    try:
        input_data = json.loads(sys.stdin.read())
    except json.JSONDecodeError:
        print(json.dumps({"hookSpecificOutput": {"permissionDecision": "allow"}}))
        return
    
    # For now, this is informational - log detected transitions
    # Could be enhanced to block invalid transitions
    
    current_phase = get_current_agent_phase()
    
    if not current_phase:
        print(json.dumps({"hookSpecificOutput": {"permissionDecision": "allow"}}))
        return
    
    # Log the phase for telemetry
    output = {
        "hookSpecificOutput": {
            "permissionDecision": "allow",
            "telemetry": {
                "current_phase": current_phase,
                "phase_order": PHASE_ORDER.index(current_phase) if current_phase in PHASE_ORDER else -1
            }
        }
    }
    
    print(json.dumps(output))


if __name__ == "__main__":
    main()
```

---

## Pattern 3: Workspace Conflict Detection

**Example:** Detect multiple agents editing the same file simultaneously

### Hook Concept

**File:** `/hooks/workspace-validation.py`

```python
#!/usr/bin/env python3
"""PostToolUse hook to detect workspace conflicts.

Tracks file modifications and warns when:
- Multiple agents edit same file in same phase
- File conflicts detected by git
- Orphaned test/code pairs (tests but no implementation)
"""

import json
import sys
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

try:
    from workflow_client import workflow_get_state, workflow_update
except ImportError:
    def workflow_get_state(wf): return {}
    def workflow_update(wf, updates): pass


MODIFIED_FILES_STATE_KEY = "workspace_modifications"
TIMEOUT_SECONDS = 300  # 5 minutes


def track_file_modification(agent_id: str, file_path: str, operation: str):
    """Track which agent modified which file."""
    try:
        state = workflow_get_state("iterate") or {}
        mods = state.get(MODIFIED_FILES_STATE_KEY, {})
        
        now = datetime.now().isoformat()
        
        if file_path not in mods:
            mods[file_path] = []
        
        # Add modification record
        mods[file_path].append({
            "agent_id": agent_id,
            "operation": operation,
            "timestamp": now
        })
        
        # Update state
        workflow_update("iterate", {MODIFIED_FILES_STATE_KEY: mods})
    except Exception:
        pass  # Fail silently


def detect_conflicts(file_path: str) -> list:
    """Detect if multiple agents modified this file recently."""
    try:
        state = workflow_get_state("iterate") or {}
        mods = state.get(MODIFIED_FILES_STATE_KEY, {})
        
        if file_path not in mods:
            return []
        
        # Get modifications from last 5 minutes
        cutoff = datetime.now() - timedelta(seconds=TIMEOUT_SECONDS)
        recent_mods = [
            m for m in mods[file_path]
            if datetime.fromisoformat(m["timestamp"]) > cutoff
        ]
        
        # If multiple agents, return conflicts
        agent_ids = set(m["agent_id"] for m in recent_mods)
        if len(agent_ids) > 1:
            return recent_mods
        
        return []
    except Exception:
        return []


def main():
    """PostToolUse hook main."""
    try:
        input_data = json.loads(sys.stdin.read())
    except json.JSONDecodeError:
        print(json.dumps({"hookSpecificOutput": {}}))
        return
    
    tool_name = input_data.get("tool_name", "")
    tool_input = input_data.get("tool_input", {})
    
    # Track file modifications
    if tool_name in {"Edit", "Write", "create_text_file", "replace_content"}:
        file_path = tool_input.get("file_path") or tool_input.get("relative_path")
        agent_id = "unknown"  # Would be injected by agent context
        
        if file_path:
            track_file_modification(agent_id, file_path, tool_name)
            
            # Check for conflicts
            conflicts = detect_conflicts(file_path)
            if conflicts:
                print(json.dumps({
                    "hookSpecificOutput": {
                        "warning": (
                            f"File conflict detected: {file_path} "
                            f"modified by {len(conflicts)} agents in last 5 minutes"
                        ),
                        "conflicts": conflicts
                    }
                }))
                return
    
    print(json.dumps({"hookSpecificOutput": {}}))


if __name__ == "__main__":
    main()
```

---

## Integration Checklist

When adding a new anti-pattern detection:

- [ ] **Identify** the anti-pattern and write description
- [ ] **Create** hook file in `/hooks/{name}.py`
- [ ] **Test** with unit tests in `/tests/test_{name}.py`
- [ ] **Register** in `plugin.json` (if plugin-based)
- [ ] **Document** in `ANTI_PATTERNS_DETECTION.md`
- [ ] **Validate** hook against current test suite
- [ ] **Deploy** with at least one test case passing
- [ ] **Monitor** telemetry for false positives/negatives

---

## Debugging Anti-Pattern Detection

### Test Locally

```bash
# Run specific test
python3 -m pytest tests/test_token_overflow_detection.py -v

# Test hook in isolation
python3 << 'EOF'
import json
import sys
from unittest.mock import patch

# Mock input
input_data = {"tool_name": "Task", "tool_response": {"call_count": 150}}

# Run hook
with patch("sys.stdin.read", return_value=json.dumps(input_data)):
    exec(open("hooks/token-overflow-detection.py").read())
EOF
```

### Inspect State

```bash
# View workflow state
python3 -c "from lib.workflow_client import workflow_get_state; import json; print(json.dumps(workflow_get_state('iterate'), indent=2))"

# View agent state
python3 -c "from lib.workflow_client import agent_get_state; import json; print(json.dumps(agent_get_state('sub-abc123'), indent=2))"
```

### Check Hook Logs

```bash
# View hook execution logs
tail -f ~/.claude/plugins/agent-swarm/.state/iterate.log

# Filter by hook name
grep "parallel-enforcement\|token-overflow" ~/.claude/plugins/agent-swarm/.state/iterate.log
```

---

## Common Patterns

### Pattern: Token Usage Tracking

```python
# Extract tokens from output
def extract_tokens(tool_output):
    import re
    match = re.search(r'tokens?["\s:]*(\d+)', str(tool_output), re.I)
    return int(match.group(1)) if match else 0

# Track cumulative usage
def add_token_usage(agent_id, tokens):
    state = workflow_get_state("session") or {}
    tokens_used = state.get("tokens_used", {})
    tokens_used[agent_id] = tokens_used.get(agent_id, 0) + tokens
    workflow_update("session", {"tokens_used": tokens_used})
```

### Pattern: File Pair Validation

```python
# Verify test file exists for implementation
def validate_test_pairs(impl_file):
    # impl_file: src/feature.py
    # test_file: tests/test_feature.py (or similar)
    import pathlib
    
    impl_path = pathlib.Path(impl_file)
    possible_tests = [
        impl_path.parent.parent / "tests" / f"test_{impl_path.name}",
        impl_path.parent / f"test_{impl_path.name}",
    ]
    
    return any(p.exists() for p in possible_tests)
```

### Pattern: Sequence Detection

```python
# Track tool call sequence
def get_tool_sequence(agent_id):
    state = agent_get_state(agent_id)
    return state.get("tool_calls_sequence", [])

def add_to_sequence(agent_id, tool_name):
    state = agent_get_state(agent_id) or {}
    seq = state.get("tool_calls_sequence", [])
    seq.append(tool_name)
    agent_set_state(agent_id, {**state, "tool_calls_sequence": seq[-20:]})  # Keep last 20
```

---

## Summary: Where to Add Detection

| Anti-Pattern | Hook Type | Location | Trigger |
|---|---|---|---|
| Orchestrator editing | PreToolUse | `iterate-enforcement.py` | Tool=Edit + Phase=orchestrate |
| Infinite loops | PostToolUse | `token-overflow-detection.py` (NEW) | call_count > 100 |
| Phase violations | PreToolUse | `phase-transition-validation.py` (NEW) | Invalid transition |
| File conflicts | PostToolUse | `workspace-validation.py` (NEW) | Multiple agents same file |
| Missing tests | PostToolUse | Enhancement to phase validation | implement phase without tests |
| Classification errors | PreToolUse | `monitor_agent.py` (Existing) | Classification != actual scope |
