#!/usr/bin/env python3
"""Session Start Hook - reset counters, inject context, auto-start workflow.

Responsibilities:
1. Reset enforcement counters (preserve compaction state)
2. Auto-start implementer workflow if none active
3. Clean up stale output files
4. Inject workflow permission context
5. Discover and inject recent handoff context
6. List available Serena memories
7. Inject agent protocol briefing (via router)
"""

import json
import socket
import sys
import time
from datetime import datetime
from pathlib import Path
import os

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
    from daemon_client import DaemonClient
except ImportError:
    DaemonClient = None

try:
    from project_root import find_project_root, find_recent_handoffs
except ImportError:
    find_project_root = None
    find_recent_handoffs = None


from paths import STATE_DIR

DAEMON_PORT = int(os.environ.get("DAEMON_PORT", "7523"))

# Flags that persist across compaction
PERSISTENT_FLAGS = [
    "user_approved_commit",
    "tests_executed",
    "verify_signal_given",
    "phase",
    "workflow_invoked",
]


def call_router(tool_name: str, args: dict = None, timeout: float = 10.0, retries: int = 3) -> dict | None:
    """Call router tool, with retries for startup delay."""
    args = args or {}
    
    for attempt in range(retries):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(timeout)
                s.connect(("127.0.0.1", DAEMON_PORT))
                
                request = {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {
                        "name": f"router__{tool_name}",
                        "arguments": args,
                    },
                }
                s.sendall(json.dumps(request).encode() + b"\n")
                
                data = b""
                while b"\n" not in data:
                    chunk = s.recv(4096)
                    if not chunk:
                        break
                    data += chunk
                
                if not data:
                    if attempt < retries - 1:
                        time.sleep(1)
                        continue
                    return None
                
                response = json.loads(data.decode().strip())
                if "error" in response:
                    return None
                
                result = response.get("result", {})
                if isinstance(result, dict) and "content" in result:
                    content = result["content"]
                    if content and isinstance(content[0], dict):
                        text = content[0].get("text", "")
                        try:
                            return json.loads(text)
                        except json.JSONDecodeError:
                            return {"text": text}
                return result
                
        except (socket.timeout, socket.error, ConnectionRefusedError):
            if attempt < retries - 1:
                time.sleep(1)
                continue
            return None
        except Exception:
            return None
    
    return None


def reset_enforcement_counters(agent_id: str | None = None):
    """Reset enforcement counters, preserving compaction state."""
    compaction_state_file = STATE_DIR / "compaction_state.json"

    try:
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
            "searches_done": [],
            "tool_call_count": 0,
            "started_at": datetime.now().isoformat(),
        }

        for flag in PERSISTENT_FLAGS:
            if flag in compaction_flags:
                state[flag] = compaction_flags[flag]

        state_file = STATE_DIR / "enforcement_state.json"
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        state_file.write_text(json.dumps(state, indent=2))

        if agent_id and DaemonClient:
            try:
                phase = compaction_flags.get("phase")
                if phase:
                    with DaemonClient() as dc:
                        dc.agent_set_state(agent_id, {"phase": phase})
            except Exception:
                pass

    except Exception as e:
        log_warning(f"Failed to reset enforcement counters: {e}")


def auto_start_workflow():
    """Auto-start implementer workflow if none active."""
    try:
        from implementer_workflow import ImplementerWorkflow
        wf = ImplementerWorkflow()
        if not wf.is_active():
            wf.start("Auto-started implementer workflow")
    except Exception as e:
        log_debug(f"Auto-start workflow failed: {e}")


def cleanup_stale_outputs() -> str | None:
    """Clean up output files older than 48 hours."""
    try:
        output_dir = STATE_DIR / "outputs"
        if not output_dir.exists():
            return None

        cutoff = time.time() - (48 * 3600)
        deleted = 0
        bytes_freed = 0

        for f in output_dir.glob("*"):
            if f.is_file() and f.stat().st_mtime < cutoff:
                bytes_freed += f.stat().st_size
                f.unlink()
                deleted += 1

        if deleted:
            mb = bytes_freed / (1024 * 1024)
            return f"Cleaned up {deleted} stale files ({mb:.1f}MB)"
        return None
    except Exception:
        return None


def format_permissions(perms):
    """Format permission info for display."""
    if not perms:
        return None

    lines = []
    if "phase_permissions" in perms:
        pp = perms["phase_permissions"]
        if pp.get("blocked_tools"):
            lines.append(f"Blocked: {', '.join(pp['blocked_tools'])}")
        if pp.get("allowed_categories"):
            lines.append(f"Allowed categories: {', '.join(pp['allowed_categories'])}")

    if perms.get("is_subagent"):
        lines.append("Running as subagent")

    return "\n".join(lines) if lines else None


def discover_handoffs() -> str:
    """Find and format recent handoff files."""
    try:
        if not find_project_root or not find_recent_handoffs:
            return ""

        project_root = find_project_root()
        if not project_root:
            return ""

        handoffs = find_recent_handoffs(project_root, max_count=3)
        if not handoffs:
            return ""

        # Read the most recent handoff
        recent = handoffs[0]
        content = recent.read_text()
        if len(content) > 1500:
            content = content[:1500] + "\n... (truncated)"

        return f"Recent Handoff ({recent.name}):\n{content}"
    except Exception as e:
        log_warning(f"Handoff discovery failed: {e}")
        return ""


def list_serena_memories() -> list[str]:
    """List available Serena memories."""
    memories_dir = plugin_dir / ".serena" / "memories"
    if not memories_dir.exists():
        return []
    return [f.stem for f in memories_dir.glob("*.md")]


def get_agent_briefing() -> str:
    """Get agent protocol briefing from router."""
    result = call_router("get_agent_briefing")
    if result and "briefing" in result:
        return result["briefing"]
    
    # Fallback: try direct import if router unavailable
    try:
        from protocol_assembly import UNIVERSAL_PROTOCOL, AGENT_PROTOCOL
        return f"{UNIVERSAL_PROTOCOL}\n{AGENT_PROTOCOL}"
    except ImportError:
        return ""


def ensure_otel_stack() -> str | None:
    """Start OTEL stack if not running."""
    import subprocess
    otel_dir = Path.home() / ".claude" / "infra" / "otel"
    compose_file = next(
        (otel_dir / name for name in ("docker-compose.yml", "docker-compose.yaml", "compose.yaml", "compose.yml")
         if (otel_dir / name).exists()),
        None,
    )
    if compose_file is None:
        return None
    try:
        result = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Running}}", "otel-collector"],
            capture_output=True, text=True, timeout=5,
        )
        if result.stdout.strip() == "true":
            return None
        # Not running — start it
        result = subprocess.run(
            ["docker", "compose", "-f", str(compose_file), "up", "-d"],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            return None
        return "OTEL stack started from ~/.claude/infra/otel/"
    except Exception:
        return None


def main():
    try:
        input_data = json.loads(sys.stdin.read())
    except json.JSONDecodeError:
        input_data = {}

    agent_id = input_data.get("agent_id")

    # 1. Reset counters
    reset_enforcement_counters(agent_id)

    if not agent_id:
        # Main agent flow
        
        # 2. Auto-start workflow
        auto_start_workflow()

        # 3. Cleanup stale files
        cleanup_msg = cleanup_stale_outputs()

        # 3b. Ensure OTEL stack is running
        otel_msg = ensure_otel_stack()

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

        # 7. Agent briefing (from router)
        briefing = get_agent_briefing()

        # Build output
        messages = []
        
        if briefing:
            messages.append(f"# AGENT PROTOCOL\n\n{briefing}")
        if cleanup_msg:
            messages.append(cleanup_msg)
        if otel_msg:
            messages.append(otel_msg)
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
