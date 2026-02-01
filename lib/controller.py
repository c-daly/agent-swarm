#!/usr/bin/env python3
"""Core orchestrator for the daemon.

All tool calls flow through Controller.handle_call(). Owns all services
as properties: PermissionChecker, BackendManager, LLMService, DataStore, Cache.
"""

from __future__ import annotations

import copy
import glob as glob_module
import logging
import os
import re
import subprocess
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from lib.backends import BackendManager
from lib.cache import Cache
from lib.datastore import DataStore
from lib.errors import (
    BackendNotFoundError,
    PermissionDeniedError,
    RouterError,
    WorkflowError,
)
from lib.llm import LLMService
from lib.permissions import AgentInfo, PermissionChecker

log = logging.getLogger(__name__)

# Keys that agents cannot write directly via set_value.
# Use workflow_advance_phase or workflow_pass_checkpoint instead.
PROTECTED_KEYS = frozenset({
    "phase", "active_agents", "started_at", "completed_at",
    "agent_id", "agent_type", "session_id", "workflow_id",
})


def _is_protected_key(key: str) -> bool:
    """Check whether a workflow state key is daemon-managed."""
    return (
        key in PROTECTED_KEYS
        or (len(key) > len("_checkpoint_passed") and key.endswith("_checkpoint_passed"))
    )


# --- Bash file-I/O lockdown ---------------------------------------------------
# These commands read file *contents* — agents must use native__read_file so
# the output flows through the summarization pipeline.
_BASH_READ_CMDS = frozenset({
    "cat", "head", "tail", "less", "more", "bat", "tac", "nl",
    "strings", "xxd", "hexdump", "od",
})
# File-content search — agents must use native__grep / native__glob.
_BASH_SEARCH_CMDS = frozenset({
    "grep", "egrep", "fgrep", "rg", "ag", "ack",
})
# Read-and-transform — agents must use native__read_file + native__edit_file.
_BASH_PROCESS_CMDS = frozenset({"sed", "awk"})
# Write via pipe — agents must use native__write_file.
_BASH_WRITE_CMDS = frozenset({"tee"})
_BASH_BLOCKED_CMDS = (
    _BASH_READ_CMDS | _BASH_SEARCH_CMDS | _BASH_PROCESS_CMDS | _BASH_WRITE_CMDS
)


def _check_bash_file_io(command: str) -> str | None:
    """Return an error message if *command* attempts file I/O, else ``None``.

    Splits on shell operators to inspect the first word of each segment,
    then checks for output/input redirections and inline-script patterns.
    """
    cmd = command.strip()

    # 1. Blocked commands in any segment
    for segment in re.split(r"[;|&]+|\$\(|`|\(", cmd):
        words = segment.strip().split()
        if not words:
            continue
        # Skip sudo / env prefixes
        idx = 0
        while idx < len(words) and words[idx] in ("sudo", "env"):
            idx += 1
        if idx >= len(words):
            continue
        first_cmd = words[idx].rsplit("/", 1)[-1]  # /usr/bin/cat -> cat

        if first_cmd in _BASH_READ_CMDS:
            return f"'{first_cmd}' blocked — use native__read_file to read files"
        if first_cmd in _BASH_SEARCH_CMDS:
            return f"'{first_cmd}' blocked — use native__grep or native__glob to search"
        if first_cmd in _BASH_PROCESS_CMDS:
            return (
                f"'{first_cmd}' blocked — use native__read_file + native__edit_file"
            )
        if first_cmd in _BASH_WRITE_CMDS:
            return f"'{first_cmd}' blocked — use native__write_file to write files"

    # Strip quoted strings before checking redirections so that '>' inside
    # e.g. git commit -m "feat: x > y" does not false-positive.
    unquoted = re.sub(r"""('[^']*'|"[^"]*")""", "", cmd)

    # 2. Output redirection to a real file  (allow /dev/* and fd dup >&N)
    if re.search(r"(?<![&])>{1,2}\s*(?!/dev/)(?!&)\S", unquoted):
        return "Output redirection blocked — use native__write_file to write files"

    # 3. Input redirection from a real file  (allow heredocs << and /dev/*)
    if re.search(r"(?<!<)<(?!<)\s*(?!/dev/)\S", unquoted):
        return "Input redirection blocked — use native__read_file to read files"

    # 4. Inline-script file I/O  (python/ruby/perl/node -c '…open(…')
    if re.search(
        r"(?:python|python3|ruby|perl|node)\s+-[ce]\s+.*\bopen\s*\(",
        cmd,
        re.DOTALL,
    ):
        return "Inline script file I/O blocked — use native__read_file / native__write_file"

    # 5. dd with file operands
    if re.search(r"\bdd\b.*\b(?:if|of)=(?!/dev/)", cmd):
        return "dd file I/O blocked — use native__read_file / native__write_file"

    return None


class Controller:
    """Orchestrates all request handling. Owns all services as properties."""

    def __init__(
        self,
        config_dir: Path,
        data_dir: Path,
        workflow_configs: dict | None = None,
    ) -> None:
        self._workflow_configs = workflow_configs or {}
        self.permissions = PermissionChecker(config_dir / "permissions.yaml")
        self.backends = BackendManager(config_dir / "backends.json")
        self.llm = LLMService()
        self.data = DataStore(data_dir / "datastore.db")
        self.cache = Cache()

        self._tool_to_backend: dict[str, str] = {}
        self._workflow_state: dict[str, dict] = {}
        self._agent_state: dict[str, dict] = {}
        self._state_lock = threading.RLock()
        self._summarization_threshold = 2000

        # Import previous session data into dashboard DB on startup
        threading.Thread(
            target=self.run_dashboard_import, daemon=True, name="dashboard-import"
        ).start()

    def run_dashboard_import(self) -> dict:
        """Import Claude JSONL transcripts into the dashboard database.

        Safe to call repeatedly — uses dedup and import_log to skip
        already-imported files.
        """
        try:
            base_dir = Path(__file__).parent.parent
            db_path = base_dir / "dashboard" / "data" / "dashboard.db"
            projects_dir = Path("~/.claude/projects").expanduser()

            if not projects_dir.exists():
                return {"status": "skipped", "reason": "projects dir not found"}

            # Load dashboard/import.py via importlib ("import" is a keyword)
            import importlib.util
            spec = importlib.util.spec_from_file_location(
                "dashboard_import", base_dir / "dashboard" / "import.py"
            )
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)

            db_path.parent.mkdir(parents=True, exist_ok=True)
            conn = mod.init_db(str(db_path))
            result = mod.import_claude_transcripts(conn, str(projects_dir))
            conn.close()

            log.info(
                "Dashboard import: %d files, %d inserted, %d skipped",
                result["files"], result["inserted"], result["skipped"],
            )
            return {"status": "ok", **result}
        except Exception as e:
            log.warning("Dashboard import failed: %s", e)
            return {"status": "error", "error": str(e)}

    # --- Main entry point ---

    def handle_call(self, tool: str, args: dict) -> Any:
        """Main entry point. All tool calls go through here."""
        start_time = time.monotonic()

        # Parse prefix and tool_name
        if "__" in tool:
            prefix, _, tool_name = tool.partition("__")
        else:
            prefix, tool_name = tool, ""

        # Extract caller info without mutating original args dict
        caller_info = args.get("_caller")
        clean_args = {k: v for k, v in args.items() if k != "_caller"}
        agent_info = self._resolve_agent(caller_info)

        # Check permissions
        allowed, blocked = self.permissions.check(tool, clean_args, agent_info)
        if not allowed:
            self._record_error_event(
                tool, prefix, agent_info, start_time,
                "PermissionDeniedError", blocked.reason if blocked else "blocked",
            )
            raise PermissionDeniedError(blocked)

        # Route by prefix
        try:
            if prefix == "native":
                raw_result = self._handle_native(tool_name, clean_args)
            elif prefix == "router":
                raw_result = self._handle_router(tool_name, clean_args)
            elif prefix == "workflow":
                raw_result = self._handle_workflow(tool_name, clean_args)
            else:
                raw_result = self._handle_backend(prefix, tool_name, clean_args)
        except PermissionDeniedError:
            raise  # Already recorded above
        except Exception as e:
            self._record_error_event(
                tool, prefix, agent_info, start_time,
                type(e).__name__, str(e),
            )
            raise

        # Skip caching/summarization for get_full (agent explicitly wants full content)
        skip_summarization = (prefix == "router" and tool_name == "get_full")

        if skip_summarization:
            result = raw_result
            was_summarized = False
            original_size = len(str(raw_result))
            content_id = None
        else:
            # Cache full response
            content_id = f"c{uuid.uuid4().hex[:12]}"
            original_size = len(str(raw_result))
            self.cache.store(content_id, raw_result)

            # Summarize if needed
            result, was_summarized = self._maybe_summarize(
                raw_result, content_id, original_size
            )

        # Record success telemetry
        duration_ms = int((time.monotonic() - start_time) * 1000)
        self.data.record_event({
            "tool": tool,
            "backend": prefix,
            "status": "success",
            "duration_ms": duration_ms,
            "original_size": original_size,
            "summary_size": len(str(result)) if was_summarized else None,
            "was_summarized": was_summarized,
            "session_id": agent_info.session_id if agent_info else "",
            "agent_id": agent_info.agent_id if agent_info else "",
            "agent_type": agent_info.agent_type if agent_info else "",
        })

        return result

    def _record_error_event(
        self,
        tool: str,
        prefix: str,
        agent_info: AgentInfo | None,
        start_time: float,
        error_type: str,
        error_msg: str,
    ) -> None:
        """Record a failed tool call in the event store."""
        duration_ms = int((time.monotonic() - start_time) * 1000)
        try:
            self.data.record_event({
                "tool": tool,
                "backend": prefix,
                "status": "error",
                "duration_ms": duration_ms,
                "error_type": error_type,
                "session_id": agent_info.session_id if agent_info else "",
                "agent_id": agent_info.agent_id if agent_info else "",
                "agent_type": agent_info.agent_type if agent_info else "",
            })
        except Exception:
            log.warning("Failed to record error event for %s", tool)

    def get_full_content(self, content_id: str) -> Any:
        """Retrieve cached full content by content_id."""
        content = self.cache.get(content_id)
        if content is None:
            return {"error": "Content not found or expired", "isError": True}

        self.data.record_event({
            "tool": "router__get_full",
            "backend": "router",
            "status": "success",
        })
        return content

    def list_backend_tools(self) -> list[dict]:
        """Query all backends for their tool lists, prefixed by backend name."""
        all_tools: list[dict] = []
        for backend_name in self.backends.list():
            try:
                tools = self.backends.list_tools(backend_name)
                for tool in tools:
                    prefixed_name = f"{backend_name}__{tool['name']}"
                    tool_copy = dict(tool)
                    tool_copy["name"] = prefixed_name
                    self._tool_to_backend[prefixed_name] = backend_name
                    all_tools.append(tool_copy)
            except Exception as e:
                log.warning("Failed to list tools for %s: %s", backend_name, e)
        return all_tools

    def shutdown(self) -> None:
        """Graceful shutdown."""
        self.backends.shutdown_all()
        self.data.close()

    # --- Native operations ---

    def _handle_native(self, tool_name: str, args: dict) -> Any:
        dispatch = {
            "read_file": self._native_read_file,
            "write_file": self._native_write_file,
            "edit_file": self._native_edit_file,
            "glob": self._native_glob,
            "grep": self._native_grep,
            "bash": self._native_bash,
        }
        handler = dispatch.get(tool_name)
        if handler is None:
            raise RouterError(f"Unknown native tool: {tool_name}")
        return handler(args)

    def _native_read_file(self, args: dict) -> dict:
        """Read a file from disk."""
        file_path = args.get("file_path", "")
        offset = args.get("offset", 0)
        limit = args.get("limit")

        try:
            p = Path(file_path)
            if not p.exists():
                return {"error": f"File not found: {file_path}", "isError": True}
            if p.is_dir():
                return {"error": f"Is a directory: {file_path}", "isError": True}

            lines = p.read_text(encoding="utf-8", errors="replace").splitlines(True)
            total = len(lines)

            if limit is not None:
                selected = lines[offset : offset + limit]
                truncated = (offset + limit) < total
            else:
                selected = lines[offset:]
                truncated = offset > 0

            # cat -n format
            numbered = []
            for i, line in enumerate(selected, start=offset + 1):
                numbered.append(f"  {i}\t{line.rstrip()}")
            content = "\n".join(numbered)

            return {
                "content": content,
                "line_count": len(selected),
                "char_count": sum(len(l) for l in selected),
                "truncated": truncated,
            }
        except PermissionError:
            return {"error": f"Permission denied: {file_path}", "isError": True}

    def _native_write_file(self, args: dict) -> dict:
        """Write content to a file."""
        file_path = args.get("file_path", "")
        content = args.get("content", "")
        p = Path(file_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return {"result": f"File written: {file_path}"}

    def _native_edit_file(self, args: dict) -> dict:
        """Find and replace text in a file."""
        file_path = args.get("file_path", "")
        old_string = args.get("old_string", "")
        new_string = args.get("new_string", "")
        replace_all = args.get("replace_all", False)

        p = Path(file_path)
        if not p.exists():
            return {"error": f"File not found: {file_path}", "isError": True}

        text = p.read_text(encoding="utf-8")
        count = text.count(old_string)

        if count == 0:
            return {"error": "String not found in file", "isError": True}
        if count > 1 and not replace_all:
            return {
                "error": "Multiple matches found. Use replace_all=True or provide more context.",
                "isError": True,
            }

        if replace_all:
            new_text = text.replace(old_string, new_string)
        else:
            new_text = text.replace(old_string, new_string, 1)

        p.write_text(new_text, encoding="utf-8")
        replacements = count if replace_all else 1
        return {"result": f"Edited: {file_path}", "replacements": replacements}

    def _native_glob(self, args: dict) -> dict:
        """Find files matching a glob pattern."""
        pattern = args.get("pattern", "")
        path = args.get("path", ".")

        base = Path(path)
        matches = sorted(
            base.glob(pattern),
            key=lambda p: p.stat().st_mtime if p.exists() else 0,
            reverse=True,
        )
        return {"files": [str(m) for m in matches if m.is_file()]}

    def _native_grep(self, args: dict) -> dict:
        """Search file contents with regex."""
        pattern = args.get("pattern", "")
        path = args.get("path", ".")
        output_mode = args.get("output_mode", "files")
        case_insensitive = args.get("case_insensitive", False)
        file_glob = args.get("file_glob")

        # Try ripgrep first, fall back to grep
        cmd = ["rg"]
        if case_insensitive:
            cmd.append("-i")
        if output_mode == "files":
            cmd.append("-l")
        else:
            cmd.extend(["-n", "--no-heading"])
        if file_glob:
            cmd.extend(["--glob", file_glob])
        cmd.extend([pattern, path])

        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=30
            )
        except FileNotFoundError:
            # rg not available, try grep
            cmd = ["grep", "-r"]
            if case_insensitive:
                cmd.append("-i")
            if output_mode == "files":
                cmd.append("-l")
            else:
                cmd.append("-n")
            cmd.extend([pattern, path])
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=30
            )

        lines = result.stdout.strip().splitlines() if result.stdout else []

        if output_mode == "files":
            return {"files": lines}

        matches = []
        for line in lines:
            parts = line.split(":", 2)
            if len(parts) >= 3:
                matches.append({
                    "file": parts[0],
                    "line": int(parts[1]) if parts[1].isdigit() else 0,
                    "text": parts[2],
                })
        return {"matches": matches}

    def _native_bash(self, args: dict) -> dict:
        """Execute a shell command.

        Security: shell=True is intentional — this is a local-only daemon
        (127.0.0.1) and access is gated by PermissionChecker. The permissions
        config superblocks dangerous patterns (rm -rf, sudo, curl|sh, etc.)
        and restricts bash access per agent type and workflow phase.
        """
        command = args.get("command", "")

        # Block file I/O — force agents through native tools / summarization
        violation = _check_bash_file_io(command)
        if violation:
            return {"error": violation, "isError": True}

        timeout = min(args.get("timeout", 120), 600)
        cwd = args.get("cwd")

        timed_out = False
        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=cwd,
            )
            return {
                "exit_code": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "timed_out": False,
            }
        except subprocess.TimeoutExpired:
            return {
                "exit_code": -1,
                "stdout": "",
                "stderr": f"Command timed out after {timeout}s",
                "timed_out": True,
            }

    # --- Router operations ---

    def _handle_router(self, tool_name: str, args: dict) -> Any:
        if tool_name == "ping":
            return {"status": "ok"}

        if tool_name == "list_tools":
            return [t["name"] for t in self.list_backend_tools()]

        if tool_name == "get_full":
            return self.get_full_content(args.get("content_id", ""))

        if tool_name == "register_agent":
            info = self.permissions.register_agent(
                agent_id=args.get("agent_id", ""),
                agent_type=args.get("agent_type", ""),
                roles=args.get("roles"),
            )
            return {
                "agent_id": info.agent_id,
                "agent_type": info.agent_type,
                "roles": info.roles,
            }

        if tool_name == "update_agent_phase":
            self.permissions.update_agent_phase(
                agent_id=args.get("agent_id", ""),
                workflow=args.get("workflow", ""),
                phase=args.get("phase", ""),
            )
            return {"result": "ok"}

        if tool_name == "get_allowed_tools":
            return self.permissions.get_allowed_tools(
                agent_type=args.get("agent_type")
            )

        if tool_name == "import_dashboard":
            return self.run_dashboard_import()

        raise RouterError(f"Unknown router tool: {tool_name}")

    # --- Workflow state operations ---

    def _handle_workflow(self, tool_name: str, args: dict) -> Any:
        dispatch = {
            "workflow_start": self._wf_start,
            "workflow_stop": self._wf_stop,
            "workflow_is_active": self._wf_is_active,
            "workflow_get_state": self._wf_get_state,
            "workflow_get_value": self._wf_get_value,
            "workflow_set_value": self._wf_set_value,
            "workflow_advance_phase": self._wf_advance_phase,
            "workflow_pass_checkpoint": self._wf_pass_checkpoint,
            "agent_get_state": self._agent_get_state,
            "agent_set_state": self._agent_set_state,
            "agent_delete": self._agent_delete,
            "list_agents": self._agent_list,
        }
        handler = dispatch.get(tool_name)
        if handler is None:
            raise RouterError(f"Unknown workflow tool: {tool_name}")
        return handler(args)

    def _wf_start(self, args: dict) -> dict:
        wf_id = args.get("workflow_id", "")
        with self._state_lock:
            if wf_id in self._workflow_state:
                raise WorkflowError(f"Workflow already exists: {wf_id}")
            # Validate against workflow config if available
            config = self._workflow_configs.get(wf_id)
            if self._workflow_configs and config is None:
                raise WorkflowError(f"Unknown workflow: {wf_id}")
            # Strip protected keys from user-provided initial state
            initial = args.get("initial_state", {})
            clean = {k: v for k, v in initial.items()
                     if not _is_protected_key(k)}
            # Add daemon-managed keys
            clean["started_at"] = datetime.now(timezone.utc).isoformat()
            clean["active_agents"] = {}
            clean["phase"] = config.initial_phase if config else ""
            self._workflow_state[wf_id] = clean
            self.data.record_event({
                "tool": "workflow__workflow_start",
                "backend": "workflow",
                "status": "success",
                "workflow_id": wf_id,
            })
            return copy.deepcopy(self._workflow_state[wf_id])

    def _wf_stop(self, args: dict) -> bool:
        wf_id = args.get("workflow_id", "")
        with self._state_lock:
            if wf_id not in self._workflow_state:
                raise WorkflowError(f"Workflow not found: {wf_id}")
            del self._workflow_state[wf_id]
            self.data.record_event({
                "tool": "workflow__workflow_stop",
                "backend": "workflow",
                "status": "success",
                "workflow_id": wf_id,
            })
            return True

    def _wf_is_active(self, args: dict) -> bool:
        wf_id = args.get("workflow_id", "")
        with self._state_lock:
            if wf_id not in self._workflow_state:
                return False
            # Terminal phase means workflow completed
            config = self._workflow_configs.get(wf_id)
            if config and self._workflow_state[wf_id].get("phase") == config.terminal_phase:
                return False
            return True

    def _wf_get_state(self, args: dict) -> dict | None:
        wf_id = args.get("workflow_id", "")
        with self._state_lock:
            state = self._workflow_state.get(wf_id)
            return copy.deepcopy(state) if state is not None else None

    def __wf_set_state(self, args: dict) -> dict:
        """Internal only -- not exposed via client dispatch."""
        wf_id = args.get("workflow_id", "")
        state = args.get("state", {})
        with self._state_lock:
            if wf_id not in self._workflow_state:
                raise WorkflowError(f"Workflow not found: {wf_id}")
            self._workflow_state[wf_id] = dict(state)
            return copy.deepcopy(self._workflow_state[wf_id])

    def __wf_update(self, args: dict) -> dict:
        """Internal only -- not exposed via client dispatch."""
        wf_id = args.get("workflow_id", "")
        updates = args.get("updates", {})
        with self._state_lock:
            if wf_id not in self._workflow_state:
                raise WorkflowError(f"Workflow not found: {wf_id}")
            self._workflow_state[wf_id].update(updates)
            return copy.deepcopy(self._workflow_state[wf_id])

    def _wf_get_value(self, args: dict) -> Any:
        wf_id = args.get("workflow_id", "")
        key = args.get("key", "")
        with self._state_lock:
            state = self._workflow_state.get(wf_id)
            if state is None:
                return None
            return copy.deepcopy(state.get(key))

    def _wf_set_value(self, args: dict) -> bool:
        wf_id = args.get("workflow_id", "")
        key = args.get("key", "")
        value = args.get("value")
        with self._state_lock:
            if wf_id not in self._workflow_state:
                raise WorkflowError(f"Workflow not found: {wf_id}")
            if _is_protected_key(key):
                raise WorkflowError(
                    f"Protected key '{key}' cannot be set directly. "
                    "Use workflow_advance_phase or workflow_pass_checkpoint."
                )
            self._workflow_state[wf_id][key] = value
            return True

    def _wf_advance_phase(self, args: dict) -> dict:
        """Advance workflow to a new phase, validating the transition."""
        wf_id = args.get("workflow_id", "")
        target = args.get("target_phase", "")
        with self._state_lock:
            if wf_id not in self._workflow_state:
                raise WorkflowError(f"Workflow not found: {wf_id}")
            state = self._workflow_state[wf_id]
            current = state.get("phase", "")
            # Validate transition if config available
            config = self._workflow_configs.get(wf_id)
            if config:
                valid_targets = config.transitions.get(current, set())
                if target not in valid_targets:
                    raise WorkflowError(
                        f"Invalid transition: {current} -> {target}. "
                        f"Valid targets: {sorted(valid_targets)}"
                    )
                # Check checkpoint if current phase requires it
                phase_config = config.phases.get(current)
                if phase_config and phase_config.checkpoint:
                    ck_key = f"{current}_checkpoint_passed"
                    if not state.get(ck_key):
                        raise WorkflowError(
                            f"Checkpoint not passed for phase '{current}'. "
                            "Call workflow_pass_checkpoint first."
                        )
            state["phase"] = target
            # Handle terminal phase
            if config and target == config.terminal_phase:
                state["completed_at"] = datetime.now(timezone.utc).isoformat()
            return {"status": "advanced", "phase": target}

    def _wf_pass_checkpoint(self, args: dict) -> dict:
        """Mark the current phase's checkpoint as passed."""
        wf_id = args.get("workflow_id", "")
        with self._state_lock:
            if wf_id not in self._workflow_state:
                raise WorkflowError(f"Workflow not found: {wf_id}")
            state = self._workflow_state[wf_id]
            current = state.get("phase", "")
            if not current:
                raise WorkflowError("No active phase to checkpoint")
            # Validate that current phase has a checkpoint (if config available)
            config = self._workflow_configs.get(wf_id)
            if config:
                phase_config = config.phases.get(current)
                if phase_config and not phase_config.checkpoint:
                    raise WorkflowError(
                        f"Phase '{current}' does not have a checkpoint"
                    )
            state[f"{current}_checkpoint_passed"] = datetime.now(timezone.utc).isoformat()
            return {"status": "checkpoint_passed", "phase": current}

    def _agent_get_state(self, args: dict) -> dict | None:
        agent_id = args.get("agent_id", "")
        with self._state_lock:
            state = self._agent_state.get(agent_id)
            return copy.deepcopy(state) if state is not None else None

    def _agent_set_state(self, args: dict) -> dict:
        agent_id = args.get("agent_id", "")
        state = args.get("state", {})
        with self._state_lock:
            self._agent_state[agent_id] = dict(state)
            return copy.deepcopy(self._agent_state[agent_id])

    def _agent_delete(self, args: dict) -> bool:
        agent_id = args.get("agent_id", "")
        with self._state_lock:
            self._agent_state.pop(agent_id, None)
            return True

    def _agent_list(self, args: dict) -> list[str]:
        with self._state_lock:
            return list(self._agent_state.keys())

    # --- Backend dispatch ---

    def _handle_backend(self, backend: str, tool_name: str, args: dict) -> Any:
        return self.backends.dispatch(backend, tool_name, args)

    # --- Summarization ---

    def _maybe_summarize(
        self, result: Any, content_id: str, original_size: int
    ) -> tuple[Any, bool]:
        """Summarize if above threshold. Returns (result, was_summarized)."""
        if original_size <= self._summarization_threshold:
            return result, False

        summary = self.llm.summarize(str(result), self._summarization_threshold)
        return {
            "summary": summary,
            "content_id": content_id,
            "instruction": f"To retrieve full content, call router__get_full with content_id='{content_id}'",
            "full_available": True,
        }, True

    # --- Agent resolution ---

    def _resolve_agent(self, caller: str | None) -> AgentInfo | None:
        """Resolve caller identifier to AgentInfo."""
        if caller is None:
            return None
        return self.permissions.get_agent(caller)
