#!/usr/bin/env python3
"""Session Start Hook - reset counters, inject context, auto-start workflow.

Responsibilities:
1. Reset enforcement counters (preserve compaction state)
2. Auto-start implementer workflow if none active
3. Clean up stale output files
4. Inject workflow permission context
5. Discover and inject recent handoff context
6. List available Serena memories
"""

import json
import sys
import time
from datetime import datetime
from pathlib import Path

# Add lib to path
plugin_dir = Path(__file__).parent.parent
lib_dir = plugin_dir / "lib"
sys.path.insert(0, str(lib_dir))

try:
    from hook_logging import log_warning, log_debug
except ImportError:
    def log_warning(msg, **kw): pass
    def log_debug(msg, **kw): pass

try:
    from permission_query import get_permissions, get_active_workflow_id
except ImportError:
    def get_active_workflow_id(): return None
    def get_permissions(workflow_id=None): return None

try:
    from workflow_client import workflow_get_state, workflow_set_state, agent_set_state
except ImportError:
    def workflow_get_state(workflow_id): return None
    def workflow_set_state(workflow_id, state): return None
    def agent_set_state(agent_id, state): return None

try:
    from project_root import find_project_root, find_recent_handoffs
except ImportError:
    find_project_root = None
    find_recent_handoffs = None


STATE_DIR = Path.home() / ".claude/plugins/agent-swarm/.state"

# Flags that persist across compaction (same conversation)
PERSISTENT_FLAGS = [
    "user_approved_commit",
    "tests_executed",
    "verify_signal_given",
    "phase",
    "workflow_invoked",
]


def reset_enforcement_counters(agent_id: str | None = None):
    """Reset enforcement counters, preserving compaction state."""
    compaction_state_file = STATE_DIR / "compaction_state.json"

    try:
        # Restore flags preserved from compaction
        compaction_flags = {}
        if compaction_state_file.exists():
            try:
                compaction_data = json.loads(compaction_state_file.read_text())
                compaction_flags = compaction_data.get("flags", {})
                compaction_state_file.unlink()
            except (json.JSONDecodeError, IOError):
                pass

        state = {
            "last_phase": None,
            "last_tool_time": None,
            "files_read": [],
            "read_count": 0,
            "files_edited_this_session": [],
            "phase": None,
            "search_count": 0,
            "edits_this_response": 0,
            "mcp_counts": {},
            "classification_given": False,
            "classification_type": None,
            "workflow_invoked": False,
        }

        # Restore compaction flags
        state.update(compaction_flags)

        # Set project_root for router auto-activation
        if find_project_root is not None:
            try:
                state["project_root"] = str(find_project_root(Path.cwd()))
            except Exception:
                pass

        # Subagent: inherit phase from orchestrator
        if agent_id:
            iterate_state = workflow_get_state("iterate")
            if iterate_state and iterate_state.get("phase"):
                state["phase"] = iterate_state["phase"]
            agent_set_state(agent_id, state)

        workflow_set_state("session", state)
        return True
    except Exception as e:
        log_warning(f"Counter reset failed: {e}")
        return False


def auto_start_workflow():
    """Start implementer workflow if none active."""
    for attempt in range(2):
        try:
            active_wf = get_active_workflow_id()
            if active_wf is None:
                from implementer_workflow import ImplementerWorkflow
                wf = ImplementerWorkflow()
                wf.start("Default session workflow")
            break
        except Exception:
            if attempt == 0:
                time.sleep(0.5)


def cleanup_stale_outputs() -> str | None:
    """Clean up stale output files, return message if any cleaned."""
    try:
        from output_cleanup import cleanup_stale_outputs as _cleanup
        result = _cleanup(max_age_hours=48, dry_run=False)
        if result["files_deleted"] > 0:
            space_mb = result["space_reclaimed"] / (1024 * 1024)
            return f"Cleaned {result['files_deleted']} stale output files ({space_mb:.1f} MB)"
    except Exception:
        pass
    return None


def format_permissions(perms) -> str:
    """Format PermissionStore as human-readable prompt context."""
    if not perms:
        return "No active workflow - standard permissions apply."

    lines = [
        f"Active workflow: {perms.workflow_type} ({perms.workflow_id})",
        f"Current phase: {perms.phase}",
    ]

    if perms.phase_permissions:
        pp = perms.phase_permissions
        if pp.blocked_tools:
            tools = list(pp.blocked_tools)[:10]
            if len(pp.blocked_tools) > 10:
                tools.append(f"...and {len(pp.blocked_tools) - 10} more")
            lines.append(f"Blocked tools: {', '.join(tools)}")
        if pp.allowed_categories:
            lines.append(f"Allowed categories: {', '.join(pp.allowed_categories)}")

    if perms.is_subagent:
        lines.append("Running as subagent - restricted permissions apply")

    return "\n".join(lines)


def discover_handoffs() -> str:
    """Find and format recent handoff files."""
    if find_project_root is None or find_recent_handoffs is None:
        return ""

    try:
        project_root = find_project_root(Path.cwd())
        handoffs = find_recent_handoffs(project_root, max_count=3, max_age_hours=48)
        if not handoffs:
            return ""

        content = handoffs[0].read_text()
        if len(content) > 1500:
            content = content[:1500] + "\n\n[truncated...]"

        result = f"**Previous Session Handoff** ({handoffs[0].name}):\n\n{content}"
        if len(handoffs) > 1:
            other = [h.name for h in handoffs[1:3]]
            result += f"\n\n_Other recent handoffs: {', '.join(other)}_"
        return result
    except Exception as e:
        log_debug(f"Handoff discovery failed: {e}")
        return ""


def list_serena_memories() -> list[str]:
    """List available Serena memories."""
    try:
        memories_dir = plugin_dir / ".serena" / "memories"
        if not memories_dir.exists():
            return []
        return [f.stem for f in memories_dir.glob("*.md")]
    except Exception:
        return []


def main():
    try:
        input_data = json.loads(sys.stdin.read())
    except json.JSONDecodeError:
        input_data = {}

    agent_id = input_data.get("agentId")

    # 1. Reset enforcement counters
    reset_enforcement_counters(agent_id)

    # Main agent only: workflow, cleanup, context
    if not agent_id:
        # 2. Auto-start workflow
        auto_start_workflow()

        # 3. Cleanup stale files
        cleanup_msg = cleanup_stale_outputs()

        # 4. Permission context
        permission_context = None
        try:
            active_wf_id = get_active_workflow_id()
            perms = get_permissions(active_wf_id) if active_wf_id else None
            permission_context = format_permissions(perms)
        except Exception:
            pass

        # 5. Handoff context
        handoff_context = discover_handoffs()

        # 6. List memories
        memories = list_serena_memories()

        # Build output
        messages = []
        if cleanup_msg:
            messages.append(cleanup_msg)
        if permission_context:
            messages.append(f"Workflow Permissions:\n{permission_context}")
        if handoff_context:
            messages.append(handoff_context)
        if memories:
            messages.append(f"Serena Memories: {', '.join(memories)}")

        output = {"systemMessage": "\n\n".join(messages) if messages else ""}
    else:
        output = {"systemMessage": ""}

    print(json.dumps(output))


if __name__ == "__main__":
    main()
