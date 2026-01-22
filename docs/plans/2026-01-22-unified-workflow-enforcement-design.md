# Unified Workflow Enforcement Design

**Date**: 2026-01-22
**Status**: Draft
**Author**: Claude (brainstorming session)

## Problem Statement

The current workflow enforcement system has grown organically through reactive patching of agent escapes. This has resulted in:

1. **Hook proliferation**: 25+ hooks, with 3 core enforcement hooks running as separate Python processes
2. **Scattered logic**: Enforcement decisions spread across `base-enforcement.py`, `workflow-state-enforcement.py`, `iterate-enforcement.py`, plus `iterate_workflow.py` and `phase_model.py`
3. **Socket overhead**: Each hook makes 1-4 socket calls to query workflow state
4. **No configurability**: Changing rules requires code changes; no way to disable, override, or adjust without editing Python
5. **Single workflow**: System designed for `/iterate`; adding `/debugger` or `/pr-review` would mean more hooks

### Goals

1. **Increase agent fidelity** to workflows (prevent escapes like `ruff --fix`)
2. **Decrease complexity** by consolidating enforcement into fewer, clearer components
3. **Add configurability**: disable workflow, change allowed tools, sudo mode for debugging
4. **Support multiple workflows**: iterate (TDD), debugger, PR reviews - all phase-driven

## Current Architecture

```
Tool Call → Claude Code → PreToolUse Hooks (separate processes)
                              ├── base-enforcement.py     ──┐
                              ├── iterate-enforcement.py  ──┼── socket → router → workflow_server
                              └── workflow-state-enforcement.py
                                         ↓
                              [allow/deny decision]
                                         ↓
                              MCP Router → Backend Server
```

### Key Insight

The **router is already the choke point**. Every MCP tool call flows through `mcp_router.py`. The hooks exist because Claude Code's hook system runs external processes—but the router could make enforcement decisions inline, with direct access to workflow state (via its shadow cache).

## Proposed Architecture

### Overview

Move enforcement from hooks into the router. Rules become data (JSON), not code (Python).

```
Tool Call → Claude Code → MCP Router
                              │
                              ├── Check workflow state (in-memory, no socket)
                              ├── Load enforcement rules (from JSON config)
                              ├── Make allow/deny decision
                              │
                              └── If allowed → route to backend
                                  If denied  → return block response
```

### Component Changes

#### 1. Router Enhancement (`lib/mcp_router.py`)

Add enforcement check before routing:

```python
def route(self, destination: str, tool_name: str, args: dict,
          agent_id: str = None) -> RouterResponse:
    """Route tool call with enforcement check."""

    # 1. Load enforcement rules (cached, hot-reloadable)
    rules = self._load_enforcement_rules()

    # 2. Check each active workflow's rules
    for workflow_id, workflow_rules in rules.items():
        if workflow_id == "global":
            continue

        # Skip disabled workflows
        if not workflow_rules.get("enabled", True):
            continue

        # Check if this workflow is active
        state_key = workflow_rules.get("state_key", workflow_id)
        workflow_state = self._workflow_cache.get(state_key)

        if not workflow_state or not workflow_state.get("active"):
            continue

        # Apply this workflow's enforcement
        decision = self._check_workflow_rules(
            tool_name=tool_name,
            args=args,
            agent_id=agent_id,
            workflow_state=workflow_state,
            rules=workflow_rules
        )

        if not decision.allowed:
            return RouterResponse(
                blocked=True,
                reason=decision.reason,
                workflow=workflow_id
            )

    # 3. Check global rules (no-workflow-blocks)
    if not self._any_workflow_active():
        global_rules = rules.get("global", {})
        no_workflow_blocks = global_rules.get("no_workflow_blocks", [])
        if self._tool_matches(tool_name, no_workflow_blocks):
            return RouterResponse(
                blocked=True,
                reason=f"No active workflow. Start a workflow to use {tool_name}."
            )

    # 4. Enforcement passed - route to backend
    return self._forward_to_backend(destination, tool_name, args)
```

#### 2. Enforcement Rules File (`config/enforcement.json`)

```json
{
  "$schema": "./enforcement.schema.json",
  "version": "1.0",

  "global": {
    "sudo_override": false,
    "no_workflow_blocks": ["Edit", "Write", "NotebookEdit"],
    "tool_aliases": {
      "native__edit_file": "Edit",
      "native__write_file": "Write",
      "serena__create_text_file": "Write",
      "serena__replace_content": "Edit"
    }
  },

  "iterate": {
    "enabled": true,
    "sudo_mode": false,
    "state_key": "iterate",

    "phases": {
      "orchestrate": {
        "allowed": ["Read", "Task", "TodoWrite", "TaskOutput", "Glob", "Grep", "native__bash"],
        "blocked": ["Edit", "Write", "NotebookEdit", "Bash"],
        "bash_whitelist": ["iterate_workflow.py", "gh"]
      },
      "intake": {
        "allowed": ["Read", "Glob", "Grep", "WebSearch", "WebFetch", "Task"],
        "blocked": ["Edit", "Write", "Bash"]
      },
      "design": {
        "allowed": ["Read", "Glob", "Grep", "Write", "native__bash", "Task"],
        "blocked": ["Bash"],
        "bash_whitelist": ["iterate_workflow.py"]
      },
      "test_writing": {
        "allowed": ["Read", "Glob", "Grep", "Edit", "Write", "native__bash"],
        "blocked": ["Bash"],
        "bash_whitelist": ["iterate_workflow.py", "pytest"]
      },
      "implement": {
        "allowed": ["Read", "Glob", "Grep", "Edit", "Write", "native__bash"],
        "blocked": ["Bash"],
        "bash_whitelist": ["iterate_workflow.py", "pytest", "ruff", "mypy"],
        "bash_blocklist": ["--fix", "--unsafe-fixes"]
      },
      "test": {
        "allowed": ["Read", "Glob", "Grep", "native__bash"],
        "blocked": ["Edit", "Write", "Bash"],
        "bash_whitelist": ["iterate_workflow.py", "pytest", "ruff", "mypy", "coverage"]
      },
      "review": {
        "allowed": ["Read", "Glob", "Grep", "Edit", "Write", "native__bash"],
        "blocked": ["Bash"],
        "bash_whitelist": ["iterate_workflow.py", "pytest", "ruff", "mypy", "coverage", "git", "gh"],
        "conditional_blocks": {
          "git commit": { "requires": "coverage_ok", "reason": "Run tests before committing" },
          "git push": { "requires": "coverage_ok", "reason": "Run tests before pushing" }
        }
      },
      "done": {
        "allowed": ["*"],
        "blocked": ["Bash"]
      }
    },

    "subagent_restrictions": {
      "blocked_tools": [
        "workflow_start", "workflow_stop", "workflow_update",
        "workflow_set_state", "workflow_set_value"
      ],
      "agent_state_self_only": true
    }
  },

  "debugger": {
    "enabled": true,
    "sudo_mode": false,
    "state_key": "debugger",

    "phases": {
      "investigate": {
        "allowed": ["Read", "Grep", "Glob", "native__bash"],
        "blocked": ["Edit", "Write"],
        "bash_whitelist": ["git", "pytest", "python"]
      },
      "hypothesis": {
        "allowed": ["Read", "WebSearch", "WebFetch", "Grep", "Glob"],
        "blocked": ["Edit", "Write", "Bash", "native__bash"]
      },
      "experiment": {
        "allowed": ["Read", "Grep", "Glob", "Edit", "Write", "native__bash"],
        "blocked": ["Bash"],
        "bash_whitelist": ["pytest", "python"]
      },
      "verify": {
        "allowed": ["Read", "native__bash"],
        "blocked": ["Edit", "Write", "Bash"],
        "bash_whitelist": ["pytest", "git"]
      }
    }
  },

  "pr-review": {
    "enabled": true,
    "sudo_mode": false,
    "state_key": "pr-review",

    "phases": {
      "fetch": {
        "allowed": ["native__bash", "Read"],
        "blocked": ["Edit", "Write", "Bash"],
        "bash_whitelist": ["gh", "git"]
      },
      "analyze": {
        "allowed": ["Read", "Grep", "Glob", "WebFetch"],
        "blocked": ["Edit", "Write", "Bash", "native__bash"]
      },
      "comment": {
        "allowed": ["native__bash", "Read"],
        "blocked": ["Edit", "Write", "Bash"],
        "bash_whitelist": ["gh"]
      }
    }
  }
}
```

#### 3. Enforcement Logic (`lib/enforcement.py`)

New module containing the decision logic:

```python
"""Unified workflow enforcement logic.

This module implements tool access control based on:
- Active workflow and current phase
- Subagent restrictions
- Bash command filtering
- Conditional blocks (e.g., coverage_ok required for git push)
"""

from dataclasses import dataclass
from typing import Optional
import re


@dataclass
class EnforcementDecision:
    allowed: bool
    reason: str = ""
    workflow: str = ""
    phase: str = ""


def check_enforcement(
    tool_name: str,
    args: dict,
    agent_id: Optional[str],
    workflow_state: dict,
    rules: dict,
) -> EnforcementDecision:
    """Check if tool use is allowed under workflow rules.

    Args:
        tool_name: Normalized tool name (e.g., "Edit", "native__bash")
        args: Tool arguments
        agent_id: Subagent ID if applicable, None for main agent
        workflow_state: Current workflow state dict
        rules: Workflow rules from enforcement.json

    Returns:
        EnforcementDecision with allowed status and reason
    """
    workflow_id = rules.get("state_key", "unknown")

    # Check sudo mode - log but don't block
    if rules.get("sudo_mode", False):
        return EnforcementDecision(
            allowed=True,
            reason=f"[SUDO] Would block: {tool_name}",
            workflow=workflow_id
        )

    # Get current phase
    phase_name = workflow_state.get("phase", "unknown")
    phase_rules = rules.get("phases", {}).get(phase_name)

    if not phase_rules:
        # Unknown phase - allow by default (fail-open)
        return EnforcementDecision(allowed=True, workflow=workflow_id, phase=phase_name)

    # Check subagent restrictions
    if agent_id:
        decision = check_subagent_restrictions(tool_name, args, agent_id, rules)
        if not decision.allowed:
            decision.workflow = workflow_id
            decision.phase = phase_name
            return decision

    # Normalize tool name via aliases
    normalized = normalize_tool_name(tool_name, rules)

    # Check blocked tools
    blocked = phase_rules.get("blocked", [])
    if tool_matches(normalized, blocked):
        return EnforcementDecision(
            allowed=False,
            reason=f"[{workflow_id.upper()}:{phase_name}] {tool_name} is blocked in this phase",
            workflow=workflow_id,
            phase=phase_name
        )

    # Check allowed tools (if not "*")
    allowed = phase_rules.get("allowed", ["*"])
    if "*" not in allowed and not tool_matches(normalized, allowed):
        return EnforcementDecision(
            allowed=False,
            reason=f"[{workflow_id.upper()}:{phase_name}] {tool_name} not in allowed list",
            workflow=workflow_id,
            phase=phase_name
        )

    # Check bash command restrictions
    if normalized in ("native__bash", "Bash"):
        decision = check_bash_command(args.get("command", ""), phase_rules, workflow_state)
        if not decision.allowed:
            decision.workflow = workflow_id
            decision.phase = phase_name
            return decision

    return EnforcementDecision(allowed=True, workflow=workflow_id, phase=phase_name)


def check_subagent_restrictions(
    tool_name: str,
    args: dict,
    agent_id: str,
    rules: dict
) -> EnforcementDecision:
    """Check subagent-specific restrictions."""
    restrictions = rules.get("subagent_restrictions", {})

    # Check blocked tools for subagents
    blocked = restrictions.get("blocked_tools", [])
    normalized = normalize_tool_name(tool_name, rules)

    if tool_matches(normalized, blocked):
        return EnforcementDecision(
            allowed=False,
            reason=f"[SUBAGENT] {tool_name} blocked for subagents"
        )

    # Check agent_state_self_only
    if restrictions.get("agent_state_self_only", False):
        if "agent_set_state" in tool_name.lower():
            target_agent = args.get("agent_id", "")
            if target_agent != agent_id:
                return EnforcementDecision(
                    allowed=False,
                    reason=f"[SUBAGENT] Cannot modify other agent's state"
                )

    return EnforcementDecision(allowed=True)


def check_bash_command(
    command: str,
    phase_rules: dict,
    workflow_state: dict
) -> EnforcementDecision:
    """Check bash command against whitelist/blocklist."""
    if not command:
        return EnforcementDecision(allowed=True)

    cmd_lower = command.strip().lower()

    # Check blocklist patterns (e.g., "--fix", "--unsafe-fixes")
    blocklist = phase_rules.get("bash_blocklist", [])
    for pattern in blocklist:
        if pattern.lower() in cmd_lower:
            return EnforcementDecision(
                allowed=False,
                reason=f"[BASH] Pattern '{pattern}' is blocked in this phase"
            )

    # Check whitelist
    whitelist = phase_rules.get("bash_whitelist")
    if whitelist is None:
        # No whitelist = all commands allowed
        return EnforcementDecision(allowed=True)

    # Parse command to get base commands (handle pipes, &&, ||, etc.)
    base_commands = extract_base_commands(cmd_lower)

    for base_cmd in base_commands:
        if not command_matches_whitelist(base_cmd, whitelist):
            return EnforcementDecision(
                allowed=False,
                reason=f"[BASH] Command '{base_cmd}' not in whitelist: {', '.join(whitelist)}"
            )

    # Check conditional blocks
    conditional = phase_rules.get("conditional_blocks", {})
    for pattern, condition in conditional.items():
        if pattern.lower() in cmd_lower:
            required_field = condition.get("requires")
            if required_field and not workflow_state.get(required_field):
                return EnforcementDecision(
                    allowed=False,
                    reason=f"[BASH] {condition.get('reason', f'{required_field} required')}"
                )

    return EnforcementDecision(allowed=True)


def extract_base_commands(command: str) -> list[str]:
    """Extract base command names from a shell command string."""
    # Split on shell operators
    parts = re.split(r'\s*(?:;|&&|\|\||\||&)\s*', command)

    base_commands = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        # Get first word (the command)
        words = part.split()
        if words:
            base_commands.append(words[0])

    return base_commands


def command_matches_whitelist(base_cmd: str, whitelist: list[str]) -> bool:
    """Check if base command matches any whitelist entry."""
    for pattern in whitelist:
        pattern_lower = pattern.lower()
        # Exact match or pattern appears in command
        if base_cmd == pattern_lower or pattern_lower in base_cmd:
            return True
    return False


def tool_matches(tool_name: str, patterns: list[str]) -> bool:
    """Check if tool name matches any pattern in list."""
    tool_lower = tool_name.lower()
    for pattern in patterns:
        pattern_lower = pattern.lower()
        if pattern == "*":
            return True
        if tool_lower == pattern_lower:
            return True
        # Handle MCP prefixes
        if tool_lower.endswith(f"__{pattern_lower}"):
            return True
        if pattern_lower.endswith(f"__{tool_lower}"):
            return True
    return False


def normalize_tool_name(tool_name: str, rules: dict) -> str:
    """Normalize tool name using global aliases."""
    # Remove common prefixes
    if tool_name.startswith("mcp__router__"):
        tool_name = tool_name[len("mcp__router__"):]

    # Check aliases
    aliases = rules.get("tool_aliases", {})
    return aliases.get(tool_name, tool_name)
```

#### 4. Hook Reduction

**Before**: 3 enforcement hooks + others
**After**: 0-1 enforcement hooks

If we can pass `agentId` through the MCP request context, we need zero hooks. If not, one thin passthrough hook:

```python
#!/usr/bin/env python3
"""Minimal hook to pass agentId context to router."""

import json
import sys

def main():
    input_data = json.loads(sys.stdin.read())
    agent_id = input_data.get("agentId")

    # Store agent_id somewhere the router can access
    # Option 1: Environment variable (if router respawns per request)
    # Option 2: Shared file in .state/
    # Option 3: Pass through modified tool args (if supported)

    # Allow - let router do actual enforcement
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow"
        }
    }))

if __name__ == "__main__":
    main()
```

### Configuration Features

#### Disabling a Workflow

```json
{
  "iterate": {
    "enabled": false,
    ...
  }
}
```

Router skips all enforcement for disabled workflows.

#### Sudo Mode

```json
{
  "iterate": {
    "sudo_mode": true,
    ...
  }
}
```

Router logs what would be blocked but allows everything. Useful for debugging enforcement issues.

#### Global Sudo Override

```json
{
  "global": {
    "sudo_override": true
  }
}
```

Disables ALL enforcement. Emergency escape hatch.

#### Hot Reloading

Router watches `config/enforcement.json` for changes (or reloads on each request during development). No restart needed.

## Migration Path

### Phase 1: Add Router Enforcement (Parallel)

1. Implement `lib/enforcement.py` with new logic
2. Add enforcement check to router's `route()` method
3. Keep existing hooks active
4. Add logging to compare decisions

### Phase 2: Validate Equivalence

1. Run both systems in parallel
2. Log any decision mismatches
3. Fix rule definitions until 100% match

### Phase 3: Remove Hooks

1. Disable hooks one by one
2. Remove hook files
3. Update manifest.json

### Phase 4: Add New Workflows

1. Add `debugger` rules to enforcement.json
2. Add `pr-review` rules
3. Create corresponding workflow state management

## Testing Strategy

### Unit Tests

```python
def test_implement_phase_allows_edit():
    rules = load_test_rules()
    state = {"active": True, "phase": "implement"}

    decision = check_enforcement("Edit", {}, None, state, rules["iterate"])

    assert decision.allowed

def test_implement_phase_blocks_ruff_fix():
    rules = load_test_rules()
    state = {"active": True, "phase": "implement"}

    decision = check_enforcement(
        "native__bash",
        {"command": "ruff check --fix ."},
        None, state, rules["iterate"]
    )

    assert not decision.allowed
    assert "--fix" in decision.reason

def test_subagent_cannot_modify_workflow():
    rules = load_test_rules()
    state = {"active": True, "phase": "implement"}

    decision = check_enforcement(
        "workflow_set_state",
        {"workflow_id": "iterate", "state": {}},
        "subagent-123",
        state, rules["iterate"]
    )

    assert not decision.allowed
```

### Integration Tests

1. Start router with test enforcement.json
2. Make tool calls through router
3. Verify correct allow/deny responses
4. Test phase transitions
5. Test sudo mode logging

## Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| Router becomes single point of failure | Sudo override as emergency escape |
| Rules JSON becomes complex | JSON schema validation, editor support |
| Hot reload causes inconsistent state | Atomic file replacement, version field |
| Missing hook context (agentId) | Fallback to thin passthrough hook |
| Performance regression | Rules cached in memory, no socket calls |

## Success Criteria

1. **Reduced complexity**: 3 enforcement hooks → 0-1
2. **Configurable**: Change rules without code changes
3. **Multi-workflow**: Add new workflow in <30 min
4. **No escapes**: All current protections preserved
5. **Better debugging**: Sudo mode, clear logging

## Open Questions

1. ~~**agentId access**: Can we get this without a hook?~~ **RESOLVED**: Claude Code assigns agentId when spawning subagents and returns it in the Task result. The agentId is passed to hooks via stdin. We keep ONE minimal hook that writes agentId to `.state/request_context.json` for the router to read. No enforcement logic in the hook.

2. **Schema validation**: Should we validate enforcement.json on load? JSON Schema or Pydantic?

3. **Rule inheritance**: Should phases inherit from a base? Or keep them explicit?

4. **Audit logging**: Should enforcement decisions be logged to a file for debugging?

## Agent State Field Restrictions

### Problem

Subagents can call `agent_set_state(their_id, {...})` with arbitrary fields. If they can set their own `phase` field, they could bypass enforcement by claiming to be in a permissive phase.

### Solution: Read-Only Fields for Subagents

The orchestrator controls certain fields; subagents can only update result/status fields.

**Orchestrator-controlled (read-only for agents)**:
- `phase` - The workflow phase this agent operates in
- `assigned_task` - The task description assigned by orchestrator
- `workflow_id` - Which workflow this agent belongs to
- `spawned_at` - Timestamp when agent was created

**Agent-writable**:
- `result` - Output/result of agent's work
- `status` - Current status (running, complete, failed, blocked)
- `error` - Error message if failed
- `progress` - Progress indicator (percentage, step count, etc.)

### Enforcement Rules Update

```json
{
  "subagent_restrictions": {
    "blocked_tools": ["workflow_start", "workflow_stop", "workflow_update",
                      "workflow_set_state", "workflow_set_value"],
    "agent_state_self_only": true,
    "agent_state_readonly_fields": ["phase", "assigned_task", "workflow_id", "spawned_at"],
    "agent_state_allowed_fields": ["result", "status", "error", "progress"]
  }
}
```

### Router Enforcement Logic

```python
def check_agent_set_state(args: dict, agent_id: str, rules: dict) -> EnforcementDecision:
    """Validate agent_set_state calls from subagents."""
    restrictions = rules.get("subagent_restrictions", {})

    # Check self-only restriction
    target_agent = args.get("agent_id")
    if restrictions.get("agent_state_self_only") and target_agent != agent_id:
        return EnforcementDecision(
            allowed=False,
            reason="[SUBAGENT] Can only modify own agent state"
        )

    # Check for writes to readonly fields
    new_state = args.get("state", {})
    readonly_fields = restrictions.get("agent_state_readonly_fields", [])

    for field in readonly_fields:
        if field in new_state:
            return EnforcementDecision(
                allowed=False,
                reason=f"[SUBAGENT] Cannot modify readonly field: {field}"
            )

    return EnforcementDecision(allowed=True)
```

### Orchestrator-Agent Workflow

1. Orchestrator spawns subagent via Task tool
2. Claude Code returns assigned `agentId` in result
3. Orchestrator initializes agent state with protected fields:
   ```python
   agent_set_state(agent_id, {
       "phase": "implement",
       "assigned_task": "Implement feature X",
       "workflow_id": "iterate",
       "spawned_at": "2026-01-22T10:30:00Z",
       "status": "running"
   })
   ```
4. Subagent works, can only update allowed fields:
   ```python
   agent_set_state(my_id, {"status": "running", "progress": 50})
   ```
5. Subagent completes, reports result:
   ```python
   agent_set_state(my_id, {"status": "complete", "result": {...}})
   ```
6. Orchestrator reads result and decides next steps

## Appendix: Current vs Proposed Comparison

| Aspect | Current | Proposed |
|--------|---------|----------|
| Enforcement points | 3+ hooks (separate processes) | 1 (router inline) |
| Socket calls per check | 2-4 | 0 |
| Configuration | Python code changes | JSON file edits |
| Multi-workflow | Each workflow adds hooks | Each workflow adds rules section |
| Disable workflow | Comment out hook registration | Set `enabled: false` |
| Sudo mode | Not available | JSON flag |
| Add new phase | Edit Python, restart | Edit JSON, auto-reload |
| Debug enforcement | Add print statements | Enable sudo_mode, check logs |
