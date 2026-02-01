#!/usr/bin/env python3
"""SubagentStart enforcement hook.

Runs when a subagent is spawned. Injects workflow context and constraints.
Note: This runs in the PARENT context, not inside the subagent.

Subagents receive:
- Their task description
- Phase constraints (what tools are blocked)
- TDD workflow instructions

Subagents do NOT:
- Call start() (would overwrite orchestrator state)
- Write to iterate.json (orchestrator's state file)
- Load state from state_manager (they get it injected)
"""

import json
import sys
import uuid
from datetime import datetime
from pathlib import Path

# Add lib to path for workflow_client and permission_store
lib_dir = Path(__file__).parent.parent / "lib"
sys.path.insert(0, str(lib_dir))

try:
    from workflow_client import workflow_get_state, agent_set_state, workflow_is_active, workflow_get_value, workflow_update
except ImportError:
    def workflow_get_state(workflow_id: str) -> dict | None:
        return None
    def agent_set_state(agent_id: str, state: dict) -> dict | None:
        return None
    def workflow_is_active(workflow_id: str) -> bool:
        return False
    def workflow_get_value(workflow_id: str, key: str):
        return None
    def workflow_update(workflow_id: str, updates: dict) -> dict | None:
        return None

try:
    from permission_store import PermissionStore, TOOL_CATEGORIES, get_tool_category
except ImportError:
    # Fallback if permission_store not available
    PermissionStore = None
    TOOL_CATEGORIES = {}
    def get_tool_category(name):
        return None

# Telemetry store for agent type registration
_telemetry_store = None
STATE_DIR = Path.home() / ".claude/plugins/agent-swarm/.state"


def get_telemetry_store():
    """Get or create DuckDBStore for telemetry."""
    global _telemetry_store
    if _telemetry_store is None:
        try:
            from stores.duckdb_store import DuckDBStore
            STATE_DIR.mkdir(parents=True, exist_ok=True)
            _telemetry_store = DuckDBStore(data_dir=str(STATE_DIR))
        except Exception:
            pass  # Telemetry unavailable
    return _telemetry_store


def load_session_state() -> dict:
    """Load session state from state server."""
    state = workflow_get_state("session")
    return state if state else {}


def load_iterate_state() -> dict:
    """Load iterate workflow state from state server."""
    state = workflow_get_state("iterate")
    return state if state else {}


def get_blocked_tools_for_phase(phase: str, perms_dict: dict | None) -> list[str]:
    """Get blocked tools for a phase using PermissionStore if available.

    Args:
        phase: Current workflow phase
        perms_dict: Permissions dict from workflow state (may contain phase_permissions)

    Returns:
        List of blocked tool names
    """
    blocked = []

    # Try to use PermissionStore
    if PermissionStore and perms_dict:
        store = PermissionStore.from_dict(perms_dict)
        if store.phase_permissions:
            blocked.extend(store.phase_permissions.blocked_tools)
            # Add tools from blocked categories
            if store.phase_permissions.allowed_categories:
                for tool_name, category in TOOL_CATEGORIES.items():
                    if category and category not in store.phase_permissions.allowed_categories:
                        if tool_name not in blocked:
                            blocked.append(tool_name)
        return blocked

    # Fallback to phase_model if PermissionStore not available
    try:
        from phase_model import get_phase_info, TOOL_CATEGORIES as PM_CATEGORIES
        phase_info = get_phase_info(phase)
        if phase_info:
            blocked = list(phase_info.blocked_tools)
            for tool, cat in PM_CATEGORIES.items():
                if cat and cat not in phase_info.allowed_categories:
                    if tool not in blocked:
                        blocked.append(tool)
    except Exception:
        pass

    return blocked


def build_tdd_context(agent_id: str, task_desc: str, group: str = "default", repo_path: str = "") -> str:
    """Build TDD workflow context for implementer subagents."""
    repo_info = f"\n**Repo:** {repo_path}" if repo_path else ""
    return f"""
## SUBAGENT WORKFLOW CONTEXT

**Agent ID:** {agent_id}
**Task:** {task_desc}
**Group/PR:** {group}{repo_info}
**Spawned by:** Orchestrator

### Tools Available

You have ONE tool: **Bash**

Use Bash to run `mcp-call` commands:
- Shell: `mcp-call pytest`, `mcp-call git status`, `mcp-call ruff check .`
- Read files: `mcp-call serena__read_file '{{"relative_path": "path/to/file"}}'`
- Search: `mcp-call serena__search_for_pattern '{{"pattern": "..."}}'`
- List dir: `mcp-call serena__list_dir '{{"relative_path": "."}}'`
- Edit: `mcp-call serena__replace_content '{{"relative_path": "...", "old": "...", "new": "..."}}'`
- Symbols: `mcp-call serena__get_symbols_overview '{{"relative_path": "..."}}'`

**DO NOT** use Read, Write, Edit, Glob, Grep directly. Use mcp-call via Bash.

### TDD Workflow (Follow This Order)

**YOU CANNOT SKIP PHASES.** You MUST follow this exact sequence:

1. **TEST_WRITING** - Write failing tests first
2. **IMPLEMENT** - Write code to make tests pass
3. **TEST** - Run tests, lint, coverage and record results
4. **REVIEW** - Git workflow (branch/PR/commit/push)

Phase-specific instructions are injected when you enter each phase.

### Important Notes

- **DO NOT** call iterate_workflow.start() - orchestrator manages workflow state
- **DO NOT** write to iterate.json - that's orchestrator's state file
- **REPORT** your completion status when done (pass/fail/blocked)
- Focus only on your assigned task

### Completion

When done, return a summary:
```json
{{
  "agent_id": "{agent_id}",
  "status": "complete|failed|blocked",
  "summary": "What was accomplished",
  "files_modified": ["list of files"],
  "tests_passed": true|false
}}
```
"""


def build_test_writing_context(agent_id: str, task_desc: str, group: str, repo_path: str = "") -> str:
    """Context injected when entering TEST_WRITING phase."""
    cd_cmd = f"cd {repo_path} && " if repo_path else ""
    return f"""
## TEST_WRITING PHASE

**Goal:** Write failing tests that define expected behavior.

**Steps:**
1. Read task requirements and existing code patterns
2. Write test file(s) that will fail (red phase of TDD)
3. Verify tests fail: `{cd_cmd}pytest <test_file> -x`
4. When done, advance: `python3 ~/.claude/plugins/agent-swarm/lib/iterate_workflow.py advance`

**DO NOT skip to implementation. Tests MUST exist and FAIL before proceeding.**
"""


def build_implement_context(agent_id: str, task_desc: str, group: str, repo_path: str = "") -> str:
    """Context injected when entering IMPLEMENT phase."""
    cd_cmd = f"cd {repo_path} && " if repo_path else ""
    return f"""
## IMPLEMENT PHASE

**Goal:** Write minimal code to make tests pass.

**Steps:**
1. Check side-effects before changes with `mcp-call serena__find_referencing_symbols '{"name_path_pattern": "..."}'`
2. Follow existing code patterns
3. Run tests frequently: `{cd_cmd}pytest <test_file> -x`
4. When tests pass, advance: `python3 ~/.claude/plugins/agent-swarm/lib/iterate_workflow.py advance`

**Write only what's needed to make tests pass. No extra features.**
"""


def build_test_context(agent_id: str, task_desc: str, group: str, repo_path: str = "") -> str:
    """Context injected when entering TEST phase."""
    cd_cmd = f"cd {repo_path} && " if repo_path else ""
    return f"""
## TEST PHASE

**Goal:** Full verification - tests, lint, coverage. NO EDITING in this phase.

**Steps:**
1. Run full test suite: `{cd_cmd}pytest`
2. Run linter: `{cd_cmd}ruff check .`
3. Check coverage: `{cd_cmd}pytest --cov`
4. Record results: `python3 ~/.claude/plugins/agent-swarm/lib/iterate_workflow.py test 1 1 1` (args: tests lint coverage, 1=pass 0=fail)
5. Advance: `python3 ~/.claude/plugins/agent-swarm/lib/iterate_workflow.py advance`

**Kickbacks:** Tests/lint fail → IMPLEMENT | Coverage low → TEST_WRITING
"""


def build_review_context(agent_id: str, task_desc: str, group: str, repo_path: str = "") -> str:
    """Context injected when entering REVIEW phase."""
    # Build cd command if repo_path provided (multi-repo support)
    cd_cmd = f"cd {repo_path} && " if repo_path else ""
    repo_info = f"\n**Repo:** {repo_path}" if repo_path else ""
    push_repo_arg = f" --repo-path={repo_path}" if repo_path else ""

    return f"""
## REVIEW PHASE

**Goal:** Git workflow - branch, commit, PR, gated push.
**Group:** {group} | **Branch:** feature/{group}{repo_info}

**Steps:**
1. Check/create branch: `{cd_cmd}git checkout -b "feature/{group}"` or `{cd_cmd}git checkout "feature/{group}"`
2. Create PR if first task: `{cd_cmd}gh pr create --title "{group}" --body "Implementation tasks" --draft`
3. Commit: `{cd_cmd}git add -A && git commit -m "{task_desc}"`
4. Gated push: `python3 scripts/iterate_state.py push --pr={group}{push_repo_arg}`
5. Record and advance: `python3 ~/.claude/plugins/agent-swarm/lib/iterate_workflow.py review 1 && python3 ~/.claude/plugins/agent-swarm/lib/iterate_workflow.py advance`
"""


# Map phases to their context builders
PHASE_CONTEXT_BUILDERS = {
    "test_writing": build_test_writing_context,
    "implement": build_implement_context,
    "test": build_test_context,
    "review": build_review_context,
}


def build_phase_restriction_context(agent_id: str, phase: str, mode: str, blocked_tools: list[str]) -> str:
    """Build phase restriction context for subagents."""
    if not blocked_tools:
        return ""

    mode_suffix = f" ({mode} mode)" if mode else ""
    return f"""
## PHASE RESTRICTIONS (ENFORCED)

**Agent ID:** {agent_id}
**Current phase:** {phase}{mode_suffix}

**BLOCKED TOOLS - DO NOT USE:**
{chr(10).join(f'- {t}' for t in sorted(set(blocked_tools))[:15])}

If you need a blocked tool, STOP and report to orchestrator.
"""


def main():
    # Read hook input
    input_data = json.loads(sys.stdin.read())
    # Extract info - Claude Code uses snake_case for field names
    session_id = input_data.get("session_id", "unknown")[:8]
    agent_type = input_data.get("agent_type", "unknown")
    task_desc = input_data.get("task", "implementation task")

    # Use Claude Code's agentId if provided, otherwise generate one
    # Claude Code uses camelCase 'agentId'
    agent_id = input_data.get("agentId") or input_data.get("agent_id") or f"sub-{uuid.uuid4().hex[:8]}"

    # Register agent type for telemetry (non-blocking)
    try:
        store = get_telemetry_store()
        if store:
            store.register_agent_type(agent_id, agent_type)
    except Exception:
        pass  # Don't fail the hook if telemetry registration fails

    # Load all state from state server
    session_state = load_session_state()
    iterate_state = load_iterate_state()

    # Determine context
    phase = iterate_state.get("phase") or session_state.get("phase") or "none"
    mode = iterate_state.get("mode", "")
    perms_dict = iterate_state.get("permissions") or session_state.get("permissions")

    # CRITICAL: When iterate workflow is active and spawning from orchestrate phase,
    # force ALL subagent types to start in test_writing phase (TDD enforcement)
    if workflow_is_active("iterate") and phase == "orchestrate":
        phase = "test_writing"

    # Store subagent state with its phase
    agent_state = {
        "phase": phase,
        "mode": mode,
        "task": task_desc,
        "parent_session": session_id,
    }
    agent_set_state(agent_id, agent_state)

    # Track in iterate workflow's active_agents (for subagent-complete.py to pop)
    try:
        if workflow_is_active("iterate"):
            agents = workflow_get_value("iterate", "active_agents") or {}
            agents[agent_id] = {
                "description": task_desc[:100] if task_desc else "No description",
                "type": agent_type,
                "spawned_at": datetime.now().isoformat(),
            }
            workflow_update("iterate", {"active_agents": agents})
    except Exception:
        pass  # Non-critical tracking

    # Build context to inject based on mode and phase
    additional_context = []
    message_suffix = ""

    # Early exit if no phase
    if not phase or phase == "none":
        pass  # No context to inject

    elif mode == "iterate-tdd":
        # In iterate-tdd mode
        # Extract group and repo info from iterate state or default
        group = iterate_state.get("current_group") or iterate_state.get("pr_id") or "default"
        repo_path = iterate_state.get("current_repo_path") or ""

        if agent_type == "implementer" and phase in ("orchestrate", "test_writing", "implement", "test", "review"):
            # Subagent spawned by orchestrator for implementation work
            message_suffix = f" (iterate-tdd/{phase})"
            additional_context.append(build_tdd_context(agent_id, task_desc, group, repo_path))

            # Add phase-specific context if we have a builder for this phase
            if phase in PHASE_CONTEXT_BUILDERS:
                phase_builder = PHASE_CONTEXT_BUILDERS[phase]
                additional_context.append(phase_builder(agent_id, task_desc, group, repo_path))
        else:
            # iterate-tdd but not implementer or different phase - apply phase restrictions
            blocked_tools = get_blocked_tools_for_phase(phase, perms_dict)
            if blocked_tools:
                additional_context.append(
                    build_phase_restriction_context(agent_id, phase, "iterate-tdd", blocked_tools)
                )

    else:
        # Has phase but not iterate-tdd mode - apply generic restrictions
        blocked_tools = get_blocked_tools_for_phase(phase, perms_dict)
        if blocked_tools:
            additional_context.append(
                build_phase_restriction_context(agent_id, phase, mode, blocked_tools)
            )

    result = {
        "hookSpecificOutput": {
            "hookEventName": "SubagentStart",
            "additionalContext": "\n".join(additional_context) if additional_context else None,
            "message": f"Subagent {agent_type} ({agent_id}) started in phase {phase}{message_suffix}"
        }
    }

    print(json.dumps(result))


if __name__ == "__main__":
    main()
