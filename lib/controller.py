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
from lib.protocol_assembly import assemble_agent_briefing, assemble_subagent_briefing, get_workflow_state
from lib.errors import (
    BackendNotFoundError,
    PermissionDeniedError,
    RouterError,
    WorkflowError,
)
from lib.llm import LLMService
from lib.paths import agent_swarm_data_dir
from lib.permissions import AgentInfo, PermissionChecker

log = logging.getLogger(__name__)

# Keys that agents cannot write directly via set_value.
# Use workflow_advance_phase or workflow_pass_checkpoint instead.
PROTECTED_KEYS = frozenset({
    "phase", "active_agents", "started_at", "completed_at",
    "agent_id", "agent_type", "session_id", "workflow_id",
})


# Router control ops return structured data callers must parse;
# summarizing them destroys the contract.
_ROUTER_NO_SUMMARIZE = frozenset({
    "get_full", "register_agent", "update_agent_phase",
    "prepare_dispatch", "complete_dispatch",
    "get_allowed_tools", "ping", "list_tools",
})

_HEALTH_CHECK_INTERVAL = 60  # seconds between backend reconnect attempts


def _is_protected_key(key: str) -> bool:
    """Check whether a workflow state key is daemon-managed."""
    return (
        key in PROTECTED_KEYS
        or (len(key) > len("_checkpoint_passed") and key.endswith("_checkpoint_passed"))
    )


# Tools whose calls change durable state; their events record a target so the
# telemetry says not just "an edit happened" but "an edit to <path>".
_MUTATING_TOOLS = frozenset({
    "edit_file", "write_file",  # native
    "create_text_file", "replace_symbol_body", "insert_after_symbol",
    "insert_before_symbol", "replace_content", "replace_in_files",
    "replace_regex",  # serena
})
# Argument keys that name a mutation's target, in priority order.
_TARGET_ARG_KEYS = ("file_path", "relative_path", "path")


def _mutation_target(tool: str, args: dict) -> str:
    """Return what a mutating tool acted on (e.g. the edited file), else "".

    Only mutating tools yield a target; reads and queries return "" so the
    telemetry column marks genuine mutations. The target is pulled from
    whichever common path-like argument the tool carries.
    """
    basename = tool.split("__")[-1]
    if basename not in _MUTATING_TOOLS:
        return ""
    for key in _TARGET_ARG_KEYS:
        val = args.get(key)
        if val:
            return str(val)
    return ""


# --- Bash file-I/O lockdown ---------------------------------------------------



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
        # Summarize only genuinely large outputs. At the old 2000-char trigger,
        # 47% of summarizations were 2-4KB outputs the model re-fetched 62% of
        # the time — paying a round-trip to save <1KB. Trigger on real whales
        # only; keep the generated summary compact so per-whale savings hold.
        self._summarization_threshold = 8000  # trigger: summarize when output exceeds this
        self._summary_max_length = 2000  # target size of the generated summary

        # Import previous session data into dashboard DB periodically
        self._import_interval = 300  # seconds between import runs
        self._health_check_interval = _HEALTH_CHECK_INTERVAL
        threading.Thread(
            target=self._dashboard_import_loop, daemon=True, name="dashboard-import"
        ).start()

        threading.Thread(
            target=self._health_check_loop, daemon=True, name="backend-health-check"
        ).start()

    def _dashboard_import_loop(self) -> None:
        """Run dashboard import periodically."""
        while True:
            try:
                self.run_dashboard_import()
            except Exception:
                pass
            time.sleep(self._import_interval)

    def _health_check_loop(self) -> None:
        """Periodically reconnect any disconnected external backend.

        Sleeps first so startup is not delayed. Runs every _health_check_interval
        seconds. Swallows all exceptions so the thread never dies. Logs a warning
        when a backend is down.
        """
        while True:
            time.sleep(self._health_check_interval)
            try:
                backend_names = self.backends.list()
            except Exception as e:
                log.warning("Health check: failed to list backends: %s", e)
                continue
            for name in backend_names:
                try:
                    healthy = self.backends.reconnect_if_needed(name)
                    if not healthy:
                        log.warning(
                            "Health check: backend %s is down, reconnect failed", name
                        )
                except Exception as e:
                    log.warning("Health check error for %s: %s", name, e)

    def run_dashboard_import(self) -> dict:
        """Import Claude JSONL transcripts into the dashboard database.

        Safe to call repeatedly — uses dedup and import_log to skip
        already-imported files.
        """
        try:
            base_dir = Path(__file__).parent.parent
            db_path = agent_swarm_data_dir() / "dashboard.db"
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
                target=_mutation_target(tool, clean_args),
            )
            raise PermissionDeniedError(blocked)

        # Route by prefix
        try:
            if prefix == "native":
                raw_result = self._handle_native(tool_name, clean_args)
            elif prefix == "router":
                raw_result = self._handle_router(tool_name, clean_args)
            elif prefix == "workflow":
                raw_result = self._handle_workflow(tool_name, clean_args, agent_info)
            else:
                raw_result = self._handle_backend(prefix, tool_name, clean_args)
        except PermissionDeniedError:
            raise  # Already recorded above
        except Exception as e:
            self._record_error_event(
                tool, prefix, agent_info, start_time,
                type(e).__name__, str(e),
                target=_mutation_target(tool, clean_args),
            )
            raise

        skip_summarization = (
            (prefix == "router" and tool_name in _ROUTER_NO_SUMMARIZE)
            or (prefix == "native" and tool_name == "bash"
                and any(clean_args.get("command", "").lstrip().startswith(t)
                        for t in ("pytest", "python -m pytest", "ruff", "mypy")))
        )

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
            "workflow_id": (agent_info.workflow or "") if agent_info else "",
            "phase": (agent_info.phase or "") if agent_info else "",
            "target": _mutation_target(tool, clean_args),
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
        target: str = "",
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
                "target": target,
                "session_id": agent_info.session_id if agent_info else "",
                "agent_id": agent_info.agent_id if agent_info else "",
                "agent_type": agent_info.agent_type if agent_info else "",
                "workflow_id": (agent_info.workflow or "") if agent_info else "",
                "phase": (agent_info.phase or "") if agent_info else "",
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
            "web_fetch": self._native_web_fetch,
            "web_search": self._native_web_search,
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
            cmd.extend(["-n", "--no-heading", "--with-filename"])
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

    def _native_web_fetch(self, args: dict) -> dict:
        """Fetch content from a URL."""
        import urllib.request
        import urllib.error

        url = args.get("url", "")
        if not url:
            return {"error": "url is required", "isError": True}

        timeout = min(args.get("timeout", 30), 120)
        headers = args.get("headers", {})

        try:
            req = urllib.request.Request(url, headers=headers)
            req.add_header("User-Agent", "Mozilla/5.0 (compatible; agent-swarm)")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                content = resp.read().decode("utf-8", errors="replace")
                return {
                    "url": url,
                    "status": resp.status,
                    "content": content,
                    "content_type": resp.headers.get("Content-Type", ""),
                    "content_length": len(content),
                }
        except urllib.error.HTTPError as e:
            return {
                "url": url,
                "status": e.code,
                "error": str(e.reason),
                "isError": True,
            }
        except Exception as e:
            return {"url": url, "error": str(e), "isError": True}

    def _native_web_search(self, args: dict) -> dict:
        """Search the web and return results."""
        from duckduckgo_search import DDGS

        query = args.get("query", "")
        if not query:
            return {"error": "query is required", "isError": True}

        max_results = min(args.get("max_results", 10), 20)

        try:
            with DDGS() as ddgs:
                raw = list(ddgs.text(query, max_results=max_results))
            results = [
                {
                    "title": r.get("title", ""),
                    "url": r.get("href", ""),
                    "snippet": r.get("body", ""),
                }
                for r in raw
            ]
            return {
                "query": query,
                "results": results,
                "result_count": len(results),
            }
        except Exception as e:
            return {"query": query, "error": str(e), "isError": True}

    # --- Dispatch enforcement ---

    def _prepare_dispatch(self, args: dict) -> dict:
        """Prepare an agent for dispatch. Called by hook before Task() proceeds.

        Handles: validation, ID generation, permission registration,
        briefing assembly, state recording.
        Does NOT handle execution — the caller does Task().
        """
        agent_type = args.get("agent_type") or args.get("subagent_type")
        if not agent_type:
            raise RouterError("prepare_dispatch requires agent_type")

        description = args.get("description", "")

        # Generate agent ID. Use the full uuid4 hex (128-bit), not a truncated
        # prefix: agent_id keys the permission registry and the per-worker
        # iterate:{agent_id} instance, so a collision entangles two concurrent
        # workers in one AgentInfo / workflow instance -- silent governance
        # bypass and mid-flight teardown (#130).
        agent_id = f"sub-{uuid.uuid4().hex}"

        # Extract role from agent_type (e.g., "agent-swarm:implementer" -> "implementer")
        role = agent_type.split(":")[-1] if ":" in agent_type else agent_type

        # Register in permissions system
        info = self.permissions.register_agent(agent_id, role)

        # Bind the agent to the live workflow phase so per-phase permissions
        # (not just its role) govern it. Registered once here in the shared
        # daemon registry; propagate_phase keeps it current as phases advance,
        # and later mcp-call traffic resolves this entry via _caller.
        # Bind the new subagent. Dispatched within an active workflow (e.g.
        # develop) -> inherit it. A *standalone* implementer is an iterate worker
        # -> auto-start its own engine-backed iterate instance and bind it here,
        # so the start is a property of dispatch (nothing to remember) and
        # parallel workers get isolated instances.
        active_wf, active_phase = get_workflow_state()
        if active_wf:
            self.permissions.update_agent_phase(agent_id, active_wf, active_phase)
            wf_override = None
        elif role == "implementer":
            # Standalone implementer = iterate worker. Start a per-worker iterate
            # instance keyed by this sub-id and bind the worker to it (via
            # _wf_start), so iterate's phase gates govern the worker from its first
            # mcp-call (#116). The briefing tells the worker to use this sub-id as
            # its --caller-id, so binding here is correct -- the old "throwaway
            # sub-id the worker never uses" rationale was wrong. _complete_dispatch
            # tears the instance down so it does not orphan (#124).
            if self._wf_config("iterate") is not None:
                wf_id = f"iterate:{agent_id}"
                try:
                    self._wf_start({"workflow_id": wf_id}, agent_info=info)
                except WorkflowError:
                    # Instance already exists -- a re-dispatch of this sub-id, or
                    # (now astronomically unlikely, post-#130 full-entropy ids) an
                    # agent_id collision with a different live worker. _wf_start's
                    # bind only runs on a fresh start, so it did NOT bind THIS
                    # agent. Bind it here to the instance's current phase;
                    # otherwise the new worker proceeds unbound and
                    # permissions.check silently skips all L1 phase gates for it.
                    # Binding (fail-safe: governed) beats leaving it ungoverned
                    # (#116; collision space narrowed by #130).
                    with self._state_lock:
                        existing = self._workflow_state.get(wf_id)
                        phase = existing.get("phase") if existing else None
                    if phase:
                        self.permissions.update_agent_phase(agent_id, wf_id, phase)
            # Pass the FULL per-instance id so the briefing's __WF_ID__ resolves to
            # the workflow the worker is actually bound to (iterate:<agent_id>);
            # assemble_subagent_briefing strips the suffix for the protocol lookup.
            # Bare "iterate" would tell the worker to address a workflow that does
            # not exist, so it could not advance/stop its own instance (#116).
            wf_override = f"iterate:{agent_id}"
        else:
            wf_override = None

        briefing = assemble_subagent_briefing(role, workflow_override=wf_override)
        caller_header = (
            f"## Your Agent Identity\n"
            f"Agent ID: `{agent_id}`\n"
            f"Use `--caller-id={agent_id}` with ALL mcp-call invocations.\n\n"
        )
        full_briefing = caller_header + briefing

        # Record agent state
        with self._state_lock:
            # Record agent state
            self._agent_state[agent_id] = {
                "type": agent_type,
                "status": "pending",
                "started_at": datetime.now(timezone.utc).isoformat(),
                "description": description,
            }

        return {"success": True, "agent_id": agent_id, "briefing": full_briefing, "agent_type": role}

    def _get_agent_briefing(self, args: dict) -> dict:
        """Return main agent briefing. Subagents get briefing via dispatch hook additionalContext."""
        return {"briefing": assemble_agent_briefing()}

    def _complete_dispatch(self, args: dict) -> dict:
        """Mark an agent as completed/failed. Called after Task() finishes."""
        agent_id = args.get("agent_id")
        status = args.get("status", "completed")
        if not agent_id:
            raise RouterError("complete_dispatch requires agent_id")
        with self._state_lock:
            if agent_id in self._agent_state:
                self._agent_state[agent_id]["status"] = status
                self._agent_state[agent_id]["completed_at"] = datetime.now(timezone.utc).isoformat()
        self.permissions.remove_agent(agent_id)
        # Tear down the per-worker iterate instance that prepare_dispatch may have
        # started for a standalone implementer, so a finished worker does not
        # orphan it in _workflow_state (#116/#124). Only implementers get an
        # instance; guard on membership so non-implementer dispatches do not pay
        # for a raised+caught WorkflowError. _state_lock is an RLock, so holding
        # it across the check and _wf_stop is reentrant and closes the race.
        wf_id = f"iterate:{agent_id}"
        with self._state_lock:
            if wf_id in self._workflow_state:
                self._wf_stop({"workflow_id": wf_id})
        return {"success": True, "agent_id": agent_id}

    # --- Router operations ---

    def _handle_router(self, tool_name: str, args: dict) -> Any:
        if tool_name == "ping":
            return {"status": "ok"}

        if tool_name == "list_tools":
            return [t["name"] for t in self.list_backend_tools()]

        if tool_name == "get_full":
            return self.get_full_content(args.get("content_id", ""))

        if tool_name == "register_agent":
            agent_id = args.get("agent_id", "")
            agent_type = args.get("agent_type", "")
            workflow_id = args.get("workflow_id")

            # Idempotent: prepare_dispatch already registered this agent with its
            # real role + live phase. A later registration (e.g. mcp-call's
            # per-connection handshake, which carries AGENT_TYPE/WORKFLOW_ID env
            # defaults) must ATTACH to that identity, not overwrite it.
            existing = self.permissions.get_agent(agent_id)
            if existing is not None:
                info = existing
                agent_type = existing.agent_type
                workflow_id = existing.workflow
                phase = existing.phase
                # Apply an explicit session_id from the handshake (mcp-call's
                # AGENT_SESSION_ID, typically the parent session). prepare_dispatch
                # pre-registered dispatched subagents with a session_id derived
                # from their sub-id; the explicit parent value wins so their events
                # group under the parent session, not the derived sub-id.
                explicit_sid = args.get("session_id")
                if explicit_sid:
                    existing.session_id = explicit_sid
            else:
                # 1. Register in permissions system
                info = self.permissions.register_agent(
                    agent_id=agent_id,
                    agent_type=agent_type,
                    roles=args.get("roles"),
                    session_id=args.get("session_id", ""),
                )

                # 2. Determine phase from workflow config (if applicable)
                phase = None
                if workflow_id:
                    config = self._wf_config(workflow_id)
                    if config:
                        phase = config.initial_phase
                        info.workflow = workflow_id
                        info.phase = phase

            # 3. Record agent state
            agent_state = {
                "agent_id": agent_id,
                "agent_type": agent_type,
                "workflow_id": workflow_id,
                "phase": phase,
                "status": "registered",
                "registered_at": datetime.now(timezone.utc).isoformat(),
            }
            self._agent_set_state({"agent_id": agent_id, "state": agent_state})

            # 4. Assemble briefing (identity header + role/workflow protocol)
            caller_header = (
                f"## Your Agent Identity\n"
                f"Agent ID: `{agent_id}`\n"
                f"Use `--caller-id={agent_id}` with ALL mcp-call invocations.\n\n"
            )
            briefing = caller_header + assemble_subagent_briefing(
                agent_type, workflow_override=workflow_id
            )

            return {
                "agent_id": info.agent_id,
                "agent_type": info.agent_type,
                "roles": info.roles,
                "workflow_id": workflow_id,
                "phase": phase,
                "briefing": briefing,
            }

        if tool_name == "update_agent_phase":
            agent_id = args.get("agent_id", "")
            # Accept `workflow_id` (the key every other workflow tool uses) as
            # well as the legacy `workflow`. Reading only `workflow` silently set
            # the binding to "" for any caller using the conventional key, which
            # left dispatched workers unbound (no phase gating).
            workflow = args.get("workflow_id") or args.get("workflow", "")
            phase = args.get("phase", "")
            self.permissions.update_agent_phase(
                agent_id=agent_id, workflow=workflow, phase=phase,
            )
            # Keep the display/agent_state snapshot in sync with the live
            # permission binding so agent_get_state is not misleading.
            with self._state_lock:
                if agent_id in self._agent_state:
                    self._agent_state[agent_id]["workflow_id"] = workflow
                    self._agent_state[agent_id]["phase"] = phase
            return {"result": "ok"}

        if tool_name == "get_allowed_tools":
            return self.permissions.get_allowed_tools(
                agent_type=args.get("agent_type")
            )

        if tool_name == "import_dashboard":
            return self.run_dashboard_import()

        if tool_name == "prepare_dispatch":
            return self._prepare_dispatch(args)

        if tool_name == "complete_dispatch":
            return self._complete_dispatch(args)

        if tool_name == "get_agent_briefing":
            return self._get_agent_briefing(args)

        raise RouterError(f"Unknown router tool: {tool_name}")

    # --- Workflow state operations ---

    def _handle_workflow(self, tool_name: str, args: dict, agent_info=None) -> Any:
        # workflow_start binds the calling agent to the workflow it starts, so
        # the caller is actually governed by it (not its stale prior binding).
        if tool_name == "workflow_start":
            return self._wf_start(args, agent_info)
        dispatch = {
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

    def _wf_config(self, wf_id: str):
        """Resolve a workflow config by id, falling back to the base type for
        per-instance ids (e.g. 'iterate:<agent_id>' resolves to 'iterate')."""
        cfg = self._workflow_configs.get(wf_id)
        if cfg is None and ":" in wf_id:
            cfg = self._workflow_configs.get(wf_id.split(":", 1)[0])
        return cfg

    def _wf_start(self, args: dict, agent_info=None) -> dict:
        wf_id = args.get("workflow_id", "")
        with self._state_lock:
            if wf_id in self._workflow_state:
                raise WorkflowError(f"Workflow already exists: {wf_id}")
            # Validate against workflow config if available
            config = self._wf_config(wf_id)
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
            # Bind the caller to the workflow it just started so the permission
            # layer + propagate_phase govern it; without this the caller keeps
            # its stale session-start binding and never follows this workflow.
            if agent_info is not None and clean["phase"]:
                self.permissions.update_agent_phase(
                    agent_info.agent_id, wf_id, clean["phase"]
                )
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
            config = self._wf_config(wf_id)
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
            config = self._wf_config(wf_id)
            if config:
                valid_targets = config.transitions.get(current, set())
                if target not in valid_targets:
                    raise WorkflowError(
                        f"Invalid transition: {current} -> {target}. "
                        f"Valid targets: {sorted(valid_targets)}"
                    )
                # Check checkpoint if current phase requires it. The checkpoint
                # gates FORWARD progress only -- a kickback to an earlier phase
                # (test -> implement on a red suite, test -> test_writing,
                # review -> implement) is the failure loop and must stay open
                # even when the checkpoint has not been (and cannot honestly be)
                # passed. Phase order is the config's declared phase order.
                phase_config = config.phases.get(current)
                if phase_config and phase_config.checkpoint:
                    order = list(config.phases.keys())
                    forward = current in order and (
                        target not in order  # terminal phase -> forward
                        or order.index(target) > order.index(current)
                    )
                    ck_key = f"{current}_checkpoint_passed"
                    if forward and not state.get(ck_key):
                        raise WorkflowError(
                            f"Checkpoint not passed for phase '{current}'. "
                            "Call workflow_pass_checkpoint first."
                        )
            state["phase"] = target
            # Propagate to any agents bound to this workflow so their phase
            # snapshot does not go stale on mid-session transitions.
            self.permissions.propagate_phase(wf_id, target)
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
            config = self._wf_config(wf_id)
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
        # "" is the main-agent id; an empty/missing arg must NOT silently
        # de-register it (remove_agent("") would unbind the main session).
        # Mirror _complete_dispatch's guard.
        if not agent_id:
            raise RouterError("agent_delete requires agent_id")
        with self._state_lock:
            self._agent_state.pop(agent_id, None)
        # Mirror _complete_dispatch: also drop the permission-store entry. Leaving
        # it pins the old identity -- register_agent ATTACHES to a surviving perm
        # entry, so a deleted-then-re-registered id keeps its old agent_type/role
        # until a daemon restart (issue #114).
        self.permissions.remove_agent(agent_id)
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

        summary = self.llm.summarize(str(result), self._summary_max_length)
        return {
            "summary": summary,
            "content_id": content_id,
            "instruction": f"To retrieve full content, call router__get_full with content_id='{content_id}'",
            "full_available": True,
        }, True

    # --- Agent resolution ---

    def _resolve_agent(self, caller: str | None) -> AgentInfo | None:
        """Resolve caller identifier to AgentInfo.

        `caller=None` means no caller identity — used by internal daemon-method
        traffic (workflow/*, agent/*) routed through `Router._handle_daemon_method`,
        which carries no `_caller` field. Returning None lets the permission
        check fall back to the global allowlist for that infrastructure path.

        `caller=""` is the main agent. `Router._handle_tools_call` defaults a
        missing `_caller` to "" before reaching here, so model-side traffic
        from the main session resolves against the main-agent registry entry.
        """
        if caller is None:
            return None
        return self.permissions.get_agent(caller)
