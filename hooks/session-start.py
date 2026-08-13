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
from contextlib import contextmanager
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


# Brief retry to absorb the cold-daemon race at session start: the daemon
# is launched alongside the hook, and the socket may not be ready on the
# first attempt. Five 200 ms tries (~1 s) is enough in practice without
# slowing happy-path session starts (first attempt succeeds).
_DAEMON_CONNECT_ATTEMPTS = 5
_DAEMON_CONNECT_DELAY = 0.2


@contextmanager
def _open_daemon_client_with_retry(label: str):
    """Yield a connected DaemonClient, or None when retries are exhausted.

    Retries `connect()` briefly on cold-daemon `ConnectionRefusedError` /
    `OSError`. Always logs at WARNING (not DEBUG) on exhaustion so the
    failure is visible. Closes the client on exit, including when the body
    raised — surfaces close errors at WARNING (don't mask the original).

    Imports `DaemonClient` lazily so tests can inject mocks via
    `sys.modules["daemon_client"]`.
    """
    try:
        from daemon_client import DaemonClient as _DC
    except ImportError:
        yield None
        return

    last_exc: Exception | None = None
    for attempt in range(_DAEMON_CONNECT_ATTEMPTS):
        try:
            dc = _DC()
            dc.connect()
        except (ConnectionRefusedError, ConnectionError, OSError) as e:
            last_exc = e
            if attempt < _DAEMON_CONNECT_ATTEMPTS - 1:
                time.sleep(_DAEMON_CONNECT_DELAY)
            continue
        try:
            yield dc
        finally:
            try:
                dc.close()
            except Exception as close_exc:
                log_warning(f"{label}: error closing daemon client: {close_exc}")
        return

    log_warning(
        f"{label}: daemon unreachable after "
        f"{_DAEMON_CONNECT_ATTEMPTS} attempts: {last_exc}"
    )
    yield None


def auto_start_workflow():
    """Auto-start simple workflow if no workflow is currently active."""
    try:
        from permission_query import get_active_workflow_id
        try:
            if get_active_workflow_id() is not None:
                return
        except Exception as e:
            # Likely a cold-daemon race on the query path; the retry below
            # will surface a clear warning if the daemon is genuinely down.
            log_debug(f"auto_start_workflow: get_active_workflow_id check failed: {e}")
        with _open_daemon_client_with_retry("auto_start_workflow") as dc:
            if dc is None:
                return
            dc.workflow_start("simple", initial_state={"task": "Auto-started simple workflow"})
    except Exception as e:
        log_warning(f"auto_start_workflow failed: {e}")


def register_main_agent():
    """Register the main agent and bind it to the active workflow.

    The main agent caller id is derived from CLAUDE_CODE_SESSION_ID so that
    concurrent Claude Code sessions each register under a distinct key and
    cannot clobber each other phase bindings (issue #122). The id is
    "main:<session_id>" when CLAUDE_CODE_SESSION_ID is set, or "" as a
    fallback for environments where the env var is absent.

    Uses the router__* tool dispatch path (call_tool) rather than calling
    DaemonClient methods directly, because DaemonClient does not expose
    register_agent / update_agent_phase as bound methods.
    """
    if DaemonClient is None:
        log_debug("register_main_agent: DaemonClient unavailable; skipping")
        return

    # Derive a session-unique id so concurrent sessions do not clobber each
    # other registry entry in the daemon. CLAUDE_CODE_SESSION_ID is injected
    # by Claude Code into every process it spawns (hooks and mcp-router alike),
    # so both sides of registration always agree on the same key (issue #122).
    _session_id = os.environ.get("CLAUDE_CODE_SESSION_ID")
    main_agent_id = f"main:{_session_id}" if _session_id else ""

    with _open_daemon_client_with_retry("register_main_agent") as dc:
        if dc is None:
            return

        try:
            dc.call_tool("router__register_agent", {
                "agent_id": main_agent_id,
                # Labeled "main" (not "implementer") so telemetry separates the
                # top-level session's traffic from implementer subagents. The
                # agents.main permission block mirrors implementer, so governance
                # is unchanged.
                "agent_type": "main",
                "roles": ["editor", "shell_full"],
            })
        except Exception as e:
            log_warning(f"register_main_agent: register step failed: {e}")
            return

        try:
            active_wf = get_active_workflow_id()
            if not active_wf:
                log_debug("register_main_agent: no active workflow; agent registered but not phase-bound")
                return
            state = dc.workflow_get_state(active_wf)
            phase = state.get("phase") if isinstance(state, dict) else None
            if not phase:
                log_debug(f"register_main_agent: workflow {active_wf} has no phase; registered without phase binding")
                return
            dc.call_tool("router__update_agent_phase", {
                "agent_id": main_agent_id,
                "workflow_id": active_wf,
                "phase": phase,
            })
        except Exception as e:
            log_warning(
                f"register_main_agent: agent registered but phase binding failed "
                f"(agent will fall back to global-only until next session): {e}"
            )


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


def discover_resume_brief() -> str:
    """Call continuity's resume-brief CLI when available and cwd matches a project.

    Looks for `~/.claude/plugins/continuity/bin/continuity` on disk. If not
    present, returns empty string (graceful degradation — continuity is an
    optional peer plugin).

    Determines current project name from cwd basename. If the current vault
    has no `10-projects/<basename>/` directory, continuity returns a 'not
    found' message which we surface as-is (it's still useful — tells the user
    why no brief is appearing).

    Vault path is read from CONTINUITY_VAULT_DIR / VAULT_DIR env vars by
    continuity itself; this hook does not need to know the vault location.
    """
    try:
        continuity_bin = Path.home() / ".claude" / "plugins" / "continuity" / "bin" / "continuity"
        if not continuity_bin.is_file():
            return ""

        cwd = Path.cwd()
        # Project name = cwd basename (matches the CLAUDE.md continuity convention)
        project = cwd.name
        if not project:
            return ""

        import subprocess
        result = subprocess.run(
            [str(continuity_bin), "resume-brief", project],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return ""
        brief = result.stdout.strip()
        # Truncate if very long (mirrors handoff truncation pattern)
        if len(brief) > 4000:
            brief = brief[:4000] + "\n... (truncated)"
        return brief
    except Exception as e:
        log_warning(f"Continuity resume-brief discovery failed: {e}")
        return ""


def list_serena_memories() -> list[str]:
    """List available Serena memories."""
    memories_dir = plugin_dir / ".serena" / "memories"
    if not memories_dir.exists():
        return []
    return [f.stem for f in memories_dir.glob("*.md")]


def get_agent_briefing() -> str:
    """Get agent protocol briefing from router.

    For the main agent only — subagents receive their briefing via
    additionalContext from the dispatch hook.
    """
    result = call_router("get_agent_briefing", {})
    if result and "briefing" in result:
        return result["briefing"]

    # Fallback: direct import if router unavailable
    try:
        from protocol_assembly import UNIVERSAL_PROTOCOL, AGENT_PROTOCOL
        return f"{UNIVERSAL_PROTOCOL}\n{AGENT_PROTOCOL}"
    except ImportError:
        return ""


def ensure_otel_stack(otel_dir: Path | None = None) -> str | None:
    """Start OTEL stack if not running."""
    import subprocess
    if otel_dir is None:
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
        # Not running — best-effort background start (the hook budget is ~10s,
        # too short to wait for `compose up -d`). Capture output to a log so a
        # failed start leaves a trace instead of being silently discarded, and
        # report honestly that startup is unconfirmed rather than claiming it
        # started (a failed compose up would otherwise still print "starting").
        start_log = otel_dir / ".last-start.log"
        with open(start_log, "w") as log:
            subprocess.Popen(
                ["docker", "compose", "-f", str(compose_file), "up", "-d"],
                stdout=log, stderr=subprocess.STDOUT,
            )
        return (
            "OTEL stack was not running — attempted a background start "
            f"(unconfirmed; see {start_log} or Grafana at http://localhost:3000)"
        )
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

        # 2b. Register main agent with active workflow's phase
        register_main_agent()

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

        # 8. Continuity resume brief (vault-driven, when continuity is installed
        #    and cwd resolves to a known vault project)
        resume_brief = discover_resume_brief()

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
        if resume_brief:
            messages.append(resume_brief)
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
