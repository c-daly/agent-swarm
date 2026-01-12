#!/usr/bin/env python3
"""
Combined enforcement hook for agent-swarm plugin.

Enforces:
1. Phase restrictions - tools allowed per phase
2. Subagent requirements - implement phase requires subagents
3. Token efficiency - blocks excessive direct tool use
4. Scope discipline - prevents off-task exploration
5. Autopilot mode - auto-approves when enabled
"""

import sys
import json
import re
import time
from datetime import datetime, timedelta
from pathlib import Path

try:
    from hook_logging import log_error, log_warning, log_info, log_debug, ConfigError, StateError
except ImportError:
    # Fallback: define minimal logging functions
    def log_error(msg, **kw): pass
    def log_warning(msg, **kw): pass
    def log_info(msg, **kw): pass
    def log_debug(msg, **kw): pass
    class ConfigError(Exception): pass
    class StateError(Exception): pass


# Try to import monitor agent (optional dependency)
try:
    from monitor_agent import needs_monitoring, call_monitor_agent, format_monitor_result
    MONITOR_AVAILABLE = True
except ImportError:
    MONITOR_AVAILABLE = False

# Import Workflow class for state management
try:
    sys.path.insert(0, str(Path.home() / ".claude/plugins/agent-swarm/lib"))
    from workflow import Workflow
    WORKFLOW_AVAILABLE = True
except ImportError:
    WORKFLOW_AVAILABLE = False

# Import new enforcement modules (P1-P5)
try:
    from shell_virtualizer import check_command as shell_check_command
    from phase_model import check_tool_allowed as phase_check_tool_allowed
    from classification_validator import validate_classification
    from review_gate import check_review_allowed, on_push, on_review_complete
    from agent_protocol import validate_agent_spawn, get_protocol
    NEW_MODULES_AVAILABLE = True
except ImportError as e:
    NEW_MODULES_AVAILABLE = False
    log_warning(f"New enforcement modules not available: {e}")

# Import verification gates for tracking lint/test/format runs
try:
    from verification_gates import (
        on_bash_complete,
        check_verify_signal,
        check_agent_spawning,
        check_tool_versions,
        check_greptile_comments,
        load_verification_state,
        check_pr_ready,
    )
    VERIFICATION_GATES_AVAILABLE = True
except ImportError:
    VERIFICATION_GATES_AVAILABLE = False

# Configuration
STATE_FILE = Path.home() / ".claude/plugins/agent-swarm/.state/session.json"
STATE_DIR = STATE_FILE.parent
CONFIG_FILE = Path.home() / ".claude/plugins/agent-swarm/config/workflow.json"
LOG_FILE = Path.home() / ".claude/plugins/agent-swarm/.state/activity.log"
STATS_FILE = Path.home() / ".claude/plugins/agent-swarm/.state/stats.json"

def log_event(event_type: str, details: str):
    """Append event to activity log."""
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%H:%M:%S")
    with open(LOG_FILE, "a") as f:
        f.write(f"[{timestamp}] {event_type}: {details}\n")

def update_stats(allowed: bool, reason: str = None, tool_name: str = None):
    """Update usage statistics."""
    stats = {}
    if STATS_FILE.exists():
        try:
            stats = json.loads(STATS_FILE.read_text())
        except json.JSONDecodeError as e:
            log_warning(f"Corrupted stats file, resetting: {e}", file=str(STATS_FILE))
        except IOError as e:
            log_warning(f"Cannot read stats file: {e}", file=str(STATS_FILE))

    if allowed:
        stats["tools_allowed"] = stats.get("tools_allowed", 0) + 1
    else:
        stats["tools_blocked"] = stats.get("tools_blocked", 0) + 1
        if reason:
            blocks = stats.get("blocks_by_reason", {})
            # Extract first word as category
            category = reason.split("]")[0].replace("[", "") if "]" in reason else "other"
            blocks[category] = blocks.get(category, 0) + 1
            stats["blocks_by_reason"] = blocks

    if tool_name == "Task":
        stats["subagents_spawned"] = stats.get("subagents_spawned", 0) + 1

    STATS_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATS_FILE.write_text(json.dumps(stats, indent=2))

# Tool categories for grouping semantically equivalent tools
TOOL_CATEGORIES = {
    "file_read": {
        "Read",
        "mcp__filesystem__read_text_file",
        "mcp__filesystem__read_media_file",
        "mcp__plugin_serena_serena__read_file",
    },
    "file_write": {
        "Edit",
        "Write",
        "NotebookEdit",
        "mcp__filesystem__write_file",
        "mcp__filesystem__edit_file",
        "mcp__plugin_serena_serena__create_text_file",
        "mcp__plugin_serena_serena__replace_content",
    },
    "file_search": {
        "Glob",
        "Grep",
        "mcp__filesystem__search_files",
        "mcp__filesystem__list_directory",
        "mcp__filesystem__directory_tree",
        "mcp__plugin_serena_serena__find_file",
        "mcp__plugin_serena_serena__search_for_pattern",
    },
    "code_query": {
        "mcp__plugin_serena_serena__find_symbol",
        "mcp__plugin_serena_serena__get_symbols_overview",
        "mcp__plugin_serena_serena__find_referencing_symbols",
    },
    "code_edit": {
        "mcp__plugin_serena_serena__replace_symbol_body",
        "mcp__plugin_serena_serena__insert_after_symbol",
        "mcp__plugin_serena_serena__insert_before_symbol",
        "mcp__plugin_serena_serena__rename_symbol",
    },
    "web_research": {
        "WebSearch",
        "WebFetch",
        "mcp__context7__resolve-library-id",
        "mcp__context7__query-docs",
    },
    "memory": {
        "mcp__memory__read_graph",
        "mcp__memory__search_nodes",
        "mcp__memory__open_nodes",
        "mcp__plugin_serena_serena__read_memory",
        "mcp__plugin_serena_serena__list_memories",
    },
    "episodic_memory": {
        "mcp__plugin_episodic-memory_episodic-memory__search",
        "mcp__plugin_episodic-memory_episodic-memory__read",
    },
    "subagent": {
        "Task",
    },
    "user_interaction": {
        "AskUserQuestion",
        "TodoWrite",
    },
    "shell": {
        "Bash",
    },
}

# Legacy tool groups (keep for backward compatibility)
WRITE_TOOLS = {"Edit", "Write", "NotebookEdit"}
SEARCH_TOOLS = {"Glob", "Grep"}  # Read has its own counter
RESEARCH_TOOLS = {"WebSearch", "WebFetch"}

# Model enforcement for subagent spawning
AGENT_MODEL_MAP = {
    # Built-in agent types
    "Explore": "haiku",
    "Plan": "sonnet",
    "general-purpose": "sonnet",
    # agent-swarm specific agents
    "agent-swarm:explorer": "haiku",
    "agent-swarm:researcher": "haiku",
    "agent-swarm:git-agent": "haiku",
    "agent-swarm:architect": "sonnet",
    "agent-swarm:implementer": "sonnet",
    "agent-swarm:reviewer": "sonnet",
    "agent-swarm:debugger": "sonnet",
}
SUBAGENT_TOOLS = {"Task"}
GIT_TOOLS = {"Bash"}  # git commands via bash

# Phase restrictions using category names
PHASE_ALLOWED_CATEGORIES = {
    "intake": {"file_read", "file_search", "code_query", "user_interaction", "episodic_memory"},
    "research": {"web_research", "file_read", "subagent", "user_interaction"},
    "explore": {"file_search", "file_read", "code_query", "subagent", "user_interaction"},
    "design": {"file_read", "file_search", "code_query", "subagent", "user_interaction"},
    "implement": {"subagent", "file_read", "user_interaction"},  # Write only via subagent
    "review": {"file_read", "file_search", "shell", "subagent", "user_interaction"},
    "debug": {"file_read", "file_search", "file_write", "code_edit", "shell", "subagent", "user_interaction"},
    "git": {"shell", "file_read", "user_interaction"},
    "": set(),  # No phase = no restrictions
}

# Legacy phase restrictions (keep for backward compatibility with specific tool checks)
PHASE_ALLOWED_TOOLS = {
    "intake": {"Read", "Glob", "Grep", "AskUserQuestion"},
    "research": {"WebSearch", "WebFetch", "Read", "Task"},
    "explore": {"Glob", "Grep", "Read", "Task"},
    "design": {"Read", "Glob", "Grep", "Task", "AskUserQuestion"},
    "implement": {"Task", "Read"},  # Write only via subagent
    "review": {"Read", "Glob", "Grep", "Bash", "Task"},
    "debug": {"Read", "Glob", "Grep", "Bash", "Edit", "Write", "Task"},
    "git": {"Bash", "Read"},
    "": set(),  # No phase = no restrictions
}

# Tools always allowed regardless of phase
ALWAYS_ALLOWED = {"TodoWrite", "AskUserQuestion"}

# Thresholds
MAX_DIRECT_SEARCHES = 5  # After this, must use scripts
MAX_FILE_READS = 5  # After this, must use subagent

# MCP tools allowed without script (low-cost single operations)
MCP_DIRECT_ALLOWED = {
    "mcp__plugin_serena_serena__find_symbol",
    "mcp__plugin_serena_serena__get_definition",
    "mcp__plugin_serena_serena__get_symbols_overview",
    "mcp__plugin_serena_serena__search_for_pattern",  # Smart tool for code understanding
    "mcp__context7__resolve-library-id",
    "mcp__context7__query-docs",
    "mcp__memory__read_memory",
    "mcp__memory__search_nodes",
    "mcp__filesystem__read_text_file",
}

# MCP tools that require script (high-cost/batch operations)
MCP_SCRIPT_REQUIRED = {
    "mcp__plugin_serena_serena__list_dir",  # recursive can be huge
    "mcp__plugin_serena_serena__search_for_pattern",
    "mcp__plugin_serena_serena__find_referencing_symbols",
    "mcp__filesystem__directory_tree",
    "mcp__filesystem__search_files",
}


def _normalize_shell_command(cmd: str) -> str:
    """Normalize shell command by removing common obfuscation patterns.

    Prevents bypasses like: .sta""te, .sta''te, $'.state', \\s escapes
    """
    # Remove empty string concatenations: "" and ''
    cmd = re.sub(r'""', '', cmd)
    cmd = re.sub(r"''", '', cmd)
    # Remove backslash escapes for non-special chars (keep \n \t \r \\)
    cmd = re.sub(r'\\([^nrt\\])', r'\1', cmd)
    # Remove $'' ANSI-C quoting wrapper (common obfuscation)
    cmd = re.sub(r"\$'([^']*)'", r'\1', cmd)
    # Remove backtick empty commands
    cmd = re.sub(r'`\s*`', '', cmd)
    # Collapse multiple spaces
    cmd = re.sub(r'\s+', ' ', cmd)
    return cmd


def _validate_inputs(tool_name: str = None, tool_input: dict = None, state: dict = None) -> tuple:
    """Validate and normalize inputs. Returns (tool_input, state) with defaults."""
    if tool_input is None:
        tool_input = {}
    if state is None:
        state = {}
    return tool_input, state

def load_json(path: Path) -> dict:
    """Load JSON file safely with logging."""
    if not path.exists():
        log_debug("Config file not found (using defaults)", file=str(path))
        return {}
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as e:
        log_error(f"Malformed JSON in config file: {e}", file=str(path))
        return {}
    except IOError as e:
        log_error(f"Cannot read config file: {e}", file=str(path))
        return {}

def save_state(state: dict) -> None:
    """Save session state."""
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))

def allow(reason: str = None) -> dict:
    """Return allow decision."""
    result = {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow"}}
    if reason:
        result["hookSpecificOutput"]["permissionDecisionReason"] = reason
    return result

def block(reason: str) -> dict:
    """Return block decision."""
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason
        }
    }


def allow_with_warning(tool_name: str, tool_input: dict, warning: str) -> dict:
    """Allow tool but inject warning message."""
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
            "permissionDecisionWarning": warning
        }
    }


def get_tool_category(tool_name: str) -> str | None:
    """Get the category of a tool, returns None if not categorized."""
    for category, tools in TOOL_CATEGORIES.items():
        if tool_name in tools:
            return category
    return None

def check_autopilot(state: dict) -> dict | None:
    """Autopilot mode bypasses all enforcement."""
    autopilot = state.get("autopilot", {})
    if autopilot.get("enabled", False):
        return allow("[AUTOPILOT] Auto-approved")
    return None

def check_phase_restrictions(tool_name: str, state: dict, tool_input: dict = None) -> dict | None:
    """Enforce phase-specific tool restrictions."""
    tool_input, state = _validate_inputs(tool_input=tool_input, state=state)
    
    # FIRST: State file protection (always enforced, regardless of phase)
    # Only block WRITES to state files, allow reads (ls, cat, grep, etc.)
    if tool_name == "Bash" and tool_input:
        command = tool_input.get("command", "").strip()
        # Normalize to prevent obfuscation bypasses like .sta""te or $'.state'
        normalized_cmd = _normalize_shell_command(command)
        if '.state' in normalized_cmd or 'session.json' in normalized_cmd:
            # Block write operations
            write_patterns = [
                r'\brm\s+',  # rm
                r'\bmv\s+.*\.state',  # mv to .state
                r'\bcp\s+.*\.state',  # cp to .state
                r'>\s*.*\.state',  # redirect to .state
                r'>\s*.*session\.json',  # redirect to session.json
                r'\bsed\s+-i',  # sed in-place
                r'\becho\s+.*>',  # echo redirect
                r'\bcat\s+>',  # cat redirect
            ]
            if any(re.search(pattern, normalized_cmd) for pattern in write_patterns):
                return block(
                    "[BLOCKED] Cannot write to .state/ directory.\n\n"
                    "REQUIRED ACTION: Read from .state/ only, never write\n"
                    "✓ DO: Use ls, cat, grep, Read tool on .state/ files\n"
                    "✗ DON'T: Try echo >, sed -i, mv, rm, or any write operation\n"
                    "✗ DON'T: Try workarounds like temp files then mv\n\n"
                    "Why: State files are managed by enforcement system only.\n"
                    "Corrupting these breaks all metrics and tracking."
                )
            # Allow read operations (ls, cat, grep, find, etc.)

    # Block .state/ writes for Write/Edit tools
    if tool_name in ["Write", "Edit"] and tool_input:
        from pathlib import Path
        file_path = tool_input.get("file_path", "")
        if ".state" in file_path or "session.json" in file_path:
            return block(
                "[BLOCKED] Cannot write to .state/ directory.\n\n"
                "REQUIRED ACTION: Read from .state/ only, never write\n"
                "✓ DO: Use Read tool or Bash (ls, cat, grep) on .state/ files\n"
                "✗ DON'T: Use Write or Edit tools on .state/ files\n\n"
                "Why: State files are managed by enforcement system only.\n"
                "Corrupting these breaks all metrics and tracking."
            )

    # SECOND: Allow critical documentation files (handoffs, notes) from any phase
    if tool_name == "Write" and tool_input:
        from pathlib import Path
        file_path = tool_input.get("file_path", "")
        filename = Path(file_path).name
        CRITICAL_FILES = {"HANDOFF.md", "SESSION_NOTES.md"}
        if filename in CRITICAL_FILES:
            return None  # Allow handoff writes from any phase

    phase = (state.get("phase") or "").lower()

    # No phase = no restrictions
    if not phase:
        return None

    # Always allowed tools
    if tool_name in ALWAYS_ALLOWED:
        return None

    # Special case: Bash in intake phase (Python execution only)
    if phase == "intake" and tool_name == "Bash" and tool_input:
        command = tool_input.get("command", "").strip()

        # Allow orchestrator phase-transition commands
        if 'AGENT_PHASE=' in command or '/tmp/phase_' in command:
            return None  # Allow

        # Allow Python execution patterns
        python_patterns = [
            command.startswith("python3 -c"),
            command.startswith("python3 <<"),
            "cat >" in command and ".py" in command,  # Creating temp Python script
            command.startswith("python3 /tmp/") and ".py" in command,  # Running temp script
            command.startswith("rm /tmp/") and ".py" in command,  # Cleanup
        ]

        if any(python_patterns):
            return None  # Allow Python-related Bash

        # Block all other Bash commands in intake
        return block(
            "[PHASE: intake] Bash restricted to Python execution only.\n"
            "Allowed patterns:\n"
            "  - python3 -c \"...\"\n"
            "  - cat > /tmp/script.py << 'EOF'\n"
            "  - python3 /tmp/script.py\n"
            "  - rm /tmp/*.py\n"
            "For other operations, use allowed tools: Read, Glob, Grep, AskUserQuestion"
        )

    # Check phase restrictions
    allowed_tools = PHASE_ALLOWED_TOOLS.get(phase, set())

    # During implement phase, write tools require subagent
    if phase == "implement" and tool_name in WRITE_TOOLS:
        return block(
            f"[PHASE: {phase}] {tool_name} blocked. "
            f"Use Task tool to spawn implementer subagent. "
            f"Direct edits bypass review and context management."
        )

    # Strict phase enforcement (default True, can disable in config)
    config = load_json(CONFIG_FILE)
    if config.get("strict_phase_enforcement", True):
        # Use phase_model if available (P2 module) - provides unified phase enforcement
        if NEW_MODULES_AVAILABLE:
            allowed, reason = phase_check_tool_allowed(tool_name, phase)
            if not allowed:
                return block(f"[PHASE: {phase}] {reason}")
        else:
            # Fallback to inline check
            tool_category = get_tool_category(tool_name)
            allowed_categories = PHASE_ALLOWED_CATEGORIES.get(phase, set())

            # Allow if tool name matches OR category matches
            if (tool_name not in allowed_tools and
                tool_name not in ALWAYS_ALLOWED and
                tool_category not in allowed_categories):
                return block(
                    f"[PHASE: {phase}] {tool_name} not allowed in this phase.\n"
                    f"Allowed tools: {', '.join(sorted(allowed_tools))}\n"
                    f"Allowed categories: {', '.join(sorted(allowed_categories))}"
                )

    return None

def check_token_efficiency(tool_name: str, tool_input: dict, state: dict) -> dict | None:
    """Enforce token-saving measures."""
    tool_input, state = _validate_inputs(tool_input=tool_input, state=state)
    from datetime import datetime

    # CHECK COMPLIANCE: If previously blocked, agent MUST use Task/Write
    # BUT: Allow git commands and script execution even when blocked
    if "blocked_at" in state:
        blocked_info = state["blocked_at"]
        required_tools = ["Task", "Write"]

        # Check if this is an allowed Bash command even when blocked
        allowed_bash_command = False
        if tool_name == "Bash":
            command = tool_input.get("command", "")
            # Allow git commands
            if command.strip().startswith("git "):
                allowed_bash_command = True
            # Allow Python script execution
            elif "python3" in command or "python " in command:
                allowed_bash_command = True

        if tool_name in required_tools or allowed_bash_command:
            # Complied! Clear block state
            del state["blocked_at"]
            save_state(state)
            log_event("COMPLIANCE", f"Agent used {tool_name} after block - compliant")
        else:
            # Violation - block harder
            return block(
                f"[COMPLIANCE VIOLATION] Previously blocked for: {blocked_info['reason']}\n\n"
                f"REQUIRED: You were told to use Task or Write.\n"
                f"You tried to use {tool_name} instead.\n\n"
                f"YOU MUST USE: Task (spawn subagent) or Write (create script)"
            )
    # Detect phase changes and reset counters
    current_phase = state.get("phase") or ""
    last_phase = state.get("last_phase", "")
    
    if current_phase != last_phase and last_phase:
        # Phase changed, reset counters
        state["search_count"] = 0
        state["read_count"] = 0
        state["files_read"] = []
        # DON'T reset edits_this_response - it tracks per-message, not per-phase
        state["last_phase"] = current_phase
        log_event("COUNTER_RESET", f"Phase changed from '{last_phase}' to '{current_phase}', counters reset")
        save_state(state)
    elif not last_phase:
        # Initialize last_phase tracking
        state["last_phase"] = current_phase
        save_state(state)

    # NOTE: 30-minute idle detection REMOVED
    # Session reset is now handled by SessionStart hook which fires when Claude Code starts
    # This is more accurate than a time-based heuristic
    current_time = datetime.now().isoformat()

    # Update last tool time
    state["last_tool_time"] = current_time
    save_state(state)

    # Track search tool usage
    if tool_name in SEARCH_TOOLS:
        count = state.get("search_count", 0) + 1
        state["search_count"] = count
        save_state(state)

        # Check thresholds before blocking
        if count == 3:  # 50% of limit
            log_event("THRESHOLD_WARNING", f"50% search limit reached (3/{MAX_DIRECT_SEARCHES})")
            return allow_with_warning(
                tool_name, tool_input,
                f"[WARNING] 50% limit reached ({count}/{MAX_DIRECT_SEARCHES} searches).\n\n"
                f"Approaching limit. Consider batching if you need more:\n"
                f"• Task(subagent_type='Explore', ...) for codebase exploration\n"
                f"• Write script to /tmp/ for multiple search patterns"
            )
        elif count == 4:  # 80% of limit
            log_event("THRESHOLD_WARNING", f"80% search limit reached (4/{MAX_DIRECT_SEARCHES})")
            return allow_with_warning(
                tool_name, tool_input,
                f"[CAUTION] 80% limit reached ({count}/{MAX_DIRECT_SEARCHES} searches).\n\n"
                f"⚠️ Next search will BLOCK. Use Task or Write script now!"
            )

        if count > MAX_DIRECT_SEARCHES:
            state["blocked_at"] = {
                "tool": tool_name,
                "count": count,
                "timestamp": current_time,
                "reason": f"Exceeded search limit ({count}/{MAX_DIRECT_SEARCHES})"
            }
            save_state(state)
            return block(
                f"[BLOCKED] {count} direct searches used (limit: {MAX_DIRECT_SEARCHES}).\n\n"
                f"REQUIRED ACTION: Choose based on task type\n\n"
                f"✓ USE EXPLORER SUBAGENT when:\n"
                f"  - 'Find all files that...'\n"
                f"  - 'Where is X implemented?'\n"
                f"  - Understanding codebase structure\n"
                f"  Example: Task(subagent_type='Explore', prompt='Find error handlers...')\n\n"
                f"✓ USE BATCH SCRIPT when:\n"
                f"  - Multiple specific search patterns\n"
                f"  - Data extraction from known patterns\n"
                f"  Pattern: Create /tmp/batch_search.py\n"
                f"```python\n"
                f"from mcp_bridge import native_glob, native_grep\n"
                f"# Batch all searches\n"
                f"```\n"
                f"Or spawn an Explorer subagent with Task tool."
            )

    # Track file reads and detect duplicates
    if tool_name == "Read":
        file_path = tool_input.get("file_path", "")

        # Track which files have been read
        files_read = state.get("files_read", [])

        # Check for duplicate - warn but allow
        if file_path in files_read:
            log_event("DUPLICATE_READ_WARNING", f"Re-reading: {file_path}")
            # Advisory only - allow the read but track it

        # Track this file
        files_read.append(file_path)
        state["files_read"] = files_read

        count = state.get("read_count", 0) + 1
        state["read_count"] = count
        save_state(state)

        # Check thresholds before blocking
        if count == 3:  # 50% of limit (3/5 = 60%)
            log_event("THRESHOLD_WARNING", f"50% read limit reached (3/{MAX_FILE_READS})")
            return allow_with_warning(
                tool_name, tool_input,
                f"[WARNING] 50% limit reached ({count}/{MAX_FILE_READS} file reads).\n\n"
                f"Approaching limit. Consider batching if you need more:\n"
                f"• Task(subagent_type='Explore', ...) for codebase exploration\n"
                f"• Write script to /tmp/ for batch file processing"
            )
        elif count == 4:  # 80% of limit (4/5 = 80%)
            log_event("THRESHOLD_WARNING", f"80% read limit reached (4/{MAX_FILE_READS})")
            return allow_with_warning(
                tool_name, tool_input,
                f"[CAUTION] 80% limit reached ({count}/{MAX_FILE_READS} file reads).\n\n"
                f"⚠️ Next read will BLOCK. Use Task or Write script now!"
            )

        if count > MAX_FILE_READS:
            state["blocked_at"] = {
                "tool": tool_name,
                "count": count,
                "timestamp": current_time,
                "reason": f"Exceeded read limit ({count}/{MAX_FILE_READS})"
            }
            save_state(state)
            return block(
                f"[BLOCKED] {count} direct file reads (limit: {MAX_FILE_READS}).\n\n"
                f"REQUIRED ACTION: Choose based on task type\n\n"
                f"✓ USE EXPLORER SUBAGENT when:\n"
                f"  - Exploring unfamiliar code ('how does X work?')\n"
                f"  - Finding patterns across files\n"
                f"  - Understanding architecture/flow\n"
                f"  Example: Task(subagent_type='Explore', prompt='Find all API endpoints...')\n\n"
                f"✓ USE BATCH SCRIPT when:\n"
                f"  - Processing known file list\n"
                f"  - Repetitive data operations\n"
                f"  - Known extraction task\n\n"
                f"✗ DON'T: Keep calling Read one at a time\n\n"
                f"Why: Direct reads flood context. Agents aggregate better."
            )


    # Track test execution for Layer 2 of git approval
    if tool_name == "Bash":
        cmd = tool_input.get("command", "")
        test_patterns = [
            r'\bpytest\b',
            r'poetry\s+run\s+pytest',
            r'python\s+-m\s+pytest',
            r'npm\s+(?:run\s+)?test',
            r'cargo\s+test',
            r'go\s+test',
            r'make\s+test',
        ]
        if any(re.search(pattern, cmd) for pattern in test_patterns):
            state["tests_executed"] = True
            save_state(state)

    return None

def check_scope_discipline(tool_name: str, tool_input: dict, state: dict) -> dict | None:
    """Prevent off-task exploration."""
    tool_input, state = _validate_inputs(tool_input=tool_input, state=state)
    phase = state.get("phase") or ""
    task_summary = state.get("task_summary", "")

    # Only enforce during active phases
    if not phase or phase in ("intake", "research", "explore"):
        return None

    # Check if spawning subagent without clear purpose
    if tool_name == "Task":
        prompt = tool_input.get("prompt", "")
        if len(prompt) < 20:
            return block(
                "[SCOPE] Subagent prompt too vague. "
                "Provide clear, specific instructions for the subagent."
            )

    return None

def check_mcp_script_requirement(tool_name: str, tool_input: dict, state: dict) -> dict | None:
    """Enforce script usage for high-cost MCP operations."""

    # Check if this is an MCP tool
    if not tool_name.startswith("mcp__"):
        return None

    # Allow low-cost operations directly
    if tool_name in MCP_DIRECT_ALLOWED:
        return None

    # Whitelist polling operations when poll skill is active
    POLLING_TOOLS = {
        "mcp__plugin_greptile_greptile__get_code_review",
        "mcp__plugin_greptile_greptile__list_code_reviews",
        "mcp__plugin_greptile_greptile__get_merge_request",
    }
    if tool_name in POLLING_TOOLS and state.get("poll_skill_active"):
        return None  # Allow controlled polling

    # Block high-cost operations - require script
    if tool_name in MCP_SCRIPT_REQUIRED:
        return block(
            f"[MCP SCRIPT] {tool_name} requires batch script.\n"
            f"This operation can return large results. Use:\n"
            f"```python\n"
            f"from mcp_bridge import call_mcp\n"
            f"result = call_mcp('{tool_name}', {tool_input})\n"
            f"# Process and summarize result\n"
            f"```"
        )

    # Track repeated MCP calls with timestamps for time-based rate limiting
    # Rate limit: max 6 calls per tool per 5 minutes (300 seconds)
    RATE_LIMIT_WINDOW = 300  # seconds
    RATE_LIMIT_MAX_CALLS = 6

    current_time = time.time()
    mcp_timestamps = state.get("mcp_timestamps", {})

    # Get timestamps for this tool, filter to within window
    tool_timestamps = mcp_timestamps.get(tool_name, [])
    tool_timestamps = [ts for ts in tool_timestamps if current_time - ts < RATE_LIMIT_WINDOW]

    # Add current call
    tool_timestamps.append(current_time)
    mcp_timestamps[tool_name] = tool_timestamps
    state["mcp_timestamps"] = mcp_timestamps
    save_state(state)

    # Count calls within window
    count = len(tool_timestamps)

    # Block if exceeds rate limit within window
    if count > RATE_LIMIT_MAX_CALLS:
        minutes_remaining = int((RATE_LIMIT_WINDOW - (current_time - tool_timestamps[0])) / 60) + 1
        return block(
            f"[BLOCKED] {tool_name} called {count} times in {RATE_LIMIT_WINDOW // 60} minutes.\n\n"
            f"REQUIRED ACTION: Write a Python script to batch operations\n"
            f"✓ DO: Create /tmp/batch_ops.py using mcp_bridge\n"
            f"✗ DON'T: Try calling the tool 'just one more time'\n"
            f"✗ DON'T: Switch to Edit, Read, or other workarounds\n\n"
            f"Why: Repeated tool calls waste tokens. Scripts are faster and tracked.\n"
            f"Rate limit resets in ~{minutes_remaining} minute(s)."
        )

    return None

def check_smart_tool_usage(tool_name: str, tool_input: dict, state: dict) -> dict | None:
    """Block dumb methods when smarter alternatives exist."""
    tool_input, state = _validate_inputs(tool_input=tool_input, state=state)

    # WebSearch for library docs → use Context7
    if tool_name == "WebSearch":
        query = tool_input.get("query", "").lower()
        doc_indicators = ["docs", "documentation", "api", "how to", "example",
                          "tutorial", "guide", "reference", "usage"]

        # Common libraries that are definitely in Context7
        known_libs = ["react", "next", "vue", "angular", "svelte", "express",
                      "fastapi", "django", "flask", "prisma", "drizzle",
                      "tailwind", "typescript", "node", "deno", "bun"]

        if any(ind in query for ind in doc_indicators):
            if any(lib in query for lib in known_libs):
                return block(
                    "[SMART TOOLS] Use Context7 instead of WebSearch for docs:\n"
                    "  1. mcp__context7__resolve-library-id\n"
                    "  2. mcp__context7__query-docs\n"
                    "Context7 has curated, up-to-date docs. WebSearch wastes tokens on noise."
                )

    # Read for code understanding → use Serena
    if tool_name == "Read":
        file_path = tool_input.get("file_path", "")
        # Code file extensions
        code_exts = [".py", ".ts", ".js", ".tsx", ".jsx", ".go", ".rs", ".java", ".rb"]

        if any(file_path.endswith(ext) for ext in code_exts):
            # Check if this looks like exploration vs targeted read
            phase = state.get("phase") or ""
            read_count = state.get("read_count", 0)

            # First read is usually OK, but suggest Serena after that
            if read_count >= 2:
                return block(
                    f"[BLOCKED] Use Serena tools instead of Read for code understanding.\n\n"
                    f"REQUIRED ACTION: Use symbolic code exploration\n"
                    f"✓ DO: mcp__plugin_serena_serena__find_symbol - locate definitions\n"
                    f"✓ DO: mcp__plugin_serena_serena__get_symbols_overview - see structure\n"
                    f"✓ DO: mcp__plugin_serena_serena__find_references - find usages\n\n"
                    f"✗ DON'T: Use Read tool to dump entire files into context\n"
                    f"✗ DON'T: Try reading multiple files to find something\n\n"
                    f"Why: Serena extracts structure efficiently. Read dumps everything.\n"
                    f"You've used Read {read_count} times - switch to symbolic tools now."
                )

    # Bash for git → suggest gh_wrapper for queries
    if tool_name == "Bash":
        cmd = tool_input.get("command", "")

        # Exempt orchestrator system commands
        if 'AGENT_PHASE=' in cmd or '/tmp/phase_' in cmd:
            return None  # Allow

        # Use shell_virtualizer if available (P1 module)
        if NEW_MODULES_AVAILABLE:
            allowed, message = shell_check_command(cmd)
            if not allowed:
                return block(f"[BLOCKED] {message}\nCurrent command: {cmd[:60]}")
            # Cat with heredocs (writing)
            if re.search(r'\bcat\s*[>]+.*<<|\bcat\s*<<', cmd):
                return block(
                    f"[BASH ABUSE] Don't use 'cat' for writing - use Write tool instead\n"
                    f"❌ Bash: {cmd[:60]}\n"
                    f"✅ Write: {{'file_path': '<path>', 'content': '...'}}\n"
                    f"Bash cat wastes tokens and bypasses tracking."
                )

        # grep/rg abuse → use Grep (powered by ripgrep)
        if re.search(r'\b(grep|rg|egrep|fgrep)\s+', cmd):
            return block(
                f"[BLOCKED] Don't use grep/rg via Bash.\n\n"
                f"REQUIRED ACTION: Use the Grep tool\n"
                f"✓ DO: Grep({{'pattern': '<regex>', 'path': '.', 'output_mode': 'content'}})\n"
                f"✗ DON'T: Try bash grep, egrep, rg, or shell pipes\n\n"
                f"Why: Grep tool has proper formatting and integrates with metrics.\n"
                f"Current command: {cmd[:60]}"
            )

        # find abuse → use Glob
        if re.search(r'\bfind\s+', cmd):
            return block(
                f"[BASH ABUSE] Don't use 'find' - use Glob tool instead\n"
                f"❌ Bash: {cmd[:60]}\n"
                f"✅ Glob: {{'pattern': '**/*.ext', 'path': '.'}}\n"
                f"Glob is faster and integrates with tracking."
            )

        # sed/awk for file editing → use Edit
        if re.search(r'\b(sed|awk)\s+', cmd) and not re.search(r'\|', cmd):
            return block(
                f"[BLOCKED] Don't use sed/awk for file editing.\n\n"
                f"REQUIRED ACTION: Use the Edit tool\n"
                f"✓ DO: Edit({{'file_path': '<path>', 'old_string': '...', 'new_string': '...'}})\n"
                f"✗ DON'T: Try bash sed, awk, perl, or in-place edit commands\n\n"
                f"Why: Edit tool is atomic, tracked, and doesn't corrupt files.\n"
                f"Current command: {cmd[:60]}"
            )

        if cmd.startswith("gh ") and not any(x in cmd for x in ["create", "merge", "close", "edit"]):
            # Query commands, not mutating commands
            if any(x in cmd for x in ["list", "view", "status", "search"]):
                return block(
                    f"[SMART TOOLS] Use gh_wrapper.py for summarized output:\n"
                    f"  python3 ~/.claude/plugins/agent-swarm/scripts/gh_wrapper.py {cmd[3:]}\n"
                    f"Raw gh output floods context. Wrapper extracts key info only."
                )

    return None

def check_checkpoint_approval(tool_name: str, tool_input: dict, state: dict) -> dict | None:
    """Enforce checkpoint approval requirement before critical operations."""
    tool_input, state = _validate_inputs(tool_input=tool_input, state=state)
    phase = state.get("phase") or ""
    if not phase:
        return None
    
    # Load config to check if checkpoint enabled for this phase
    config = load_json(CONFIG_FILE)
    checkpoints = config.get("checkpoints", {})
    
    if not checkpoints.get(phase, False):
        return None  # No checkpoint required for this phase
    
    # Check if approval has been granted for this phase
    checkpoint_approvals = state.get("checkpoint_approvals", {})
    if checkpoint_approvals.get(phase, False):
        return None  # Approval already granted
    
    # Block critical operations that require checkpoint approval
    if tool_name == "Bash":
        command = tool_input.get("command", "")
        
        # Block git push operations
        if re.search(r'\bgit\s+push\b', command):
            return block(
                f"[CHECKPOINT: {phase}] Git push requires approval\n"
                f"This phase has checkpoint enabled. Get user approval before pushing.\n"
                f"To approve: Add 'checkpoint_approvals': {{'{phase}': true}} to state"
            )
        
        # Block git commit operations
        if re.search(r'\bgit\s+commit\b', command):
            return block(
                f"[CHECKPOINT: {phase}] Git commit requires approval\n"
                f"This phase has checkpoint enabled. Get user approval before committing.\n"
                f"To approve: Add 'checkpoint_approvals': {{'{phase}': true}} to state"
            )
    
    # Block phase transitions
    if tool_name == "Bash" and ("AGENT_PHASE=" in tool_input.get("command", "") or 
                                 "/tmp/phase_" in tool_input.get("command", "")):
        return block(
            f"[CHECKPOINT: {phase}] Phase transition requires approval\n"
            f"Complete checkpoint for '{phase}' phase before transitioning.\n"
            f"To approve: Add 'checkpoint_approvals': {{'{phase}': true}} to state"
        )
    
    return None

def check_git_safety(tool_name: str, tool_input: dict, state: dict) -> dict | None:
    """Prevent dangerous git operations."""
    tool_input, state = _validate_inputs(tool_input=tool_input, state=state)
    if tool_name != "Bash":
        return None

    command = tool_input.get("command", "")

    # Dangerous patterns
    dangerous = [
        "git push --force",
        "git push -f",
        "git reset --hard",
        "git clean -fd",
        "git checkout .",  # Discards all changes
    ]

    for pattern in dangerous:
        if pattern in command:
            return block(
                f"[GIT SAFETY] Dangerous command blocked: {pattern}\n"
                f"This operation is destructive. Get explicit user approval first."
            )

    # Note: git commit --amend checks are in CLAUDE.md, not enforced here
    # Message-only amends (fixing typos, removing attribution) are safe

    # Block attribution in commit messages - hooks should NOT add Co-Authored-By
    if "git commit" in command and "Co-Authored-By" in command:
        return block(
            "[GIT SAFETY] Attribution not allowed in commit messages.\n\n"
            "REMOVE 'Co-Authored-By' from your commit message.\n"
            "Hooks handle attribution automatically via post-commit.\n\n"
            "Just use a clean commit message without attribution."
        )

    # Monitor agent for commit message validation
    if MONITOR_AVAILABLE and "git commit" in command:
        if needs_monitoring("Bash", tool_input, state):
            decision = call_monitor_agent("Bash", tool_input, state)
            if decision:
                result = format_monitor_result(decision)
                hook_output = result.get("hookSpecificOutput", {})
                if hook_output.get("permissionDecision") == "deny":
                    return result  # Already in proper hook format

    return None





def check_git_approval_layers(tool_name: str, tool_input: dict, state: dict, messages: list) -> dict | None:
    """
    3-layer git safety system to prevent agents from committing/pushing without proper validation.

    Layer 1: User approval detection - scan messages for approval keywords
    Layer 2: Test execution requirement - track test runs, block commits without tests
    Layer 3: [VERIFY] signal - require quality check signal before commits

    Orchestrator mode: Skips Layer 2 & 3 for workflow-initiated commits
    """
    # TEMPORARY: Disable approval check for iterate workflow debugging
    return None

    if tool_name != "Bash":
        return None

    command = tool_input.get("command", "")

    # Quick bypass: check for approval flag file FIRST before any other checks
    approval_flag = STATE_DIR / "git_approval.flag"
    if approval_flag.exists() and ("git commit" in command or "git push" in command):
        return None  # Approved via flag file
    
    # Detect git commit or push
    is_commit = re.search(r'\bgit\s+commit\b', command)
    is_push = re.search(r'\bgit\s+push\b', command)
    
    if not (is_commit or is_push):
        return None
    
    # Detect orchestrator mode (workflow-initiated commits)
    is_orchestrator = (
        state.get("workflow_phase") == "git" or 
        state.get("phase") == "git" or
        "orchestrator" in command.lower()
    )
    
    # Debug logging
    log_event("GIT_APPROVAL_DEBUG", f"Messages: {len(messages)}, Orchestrator: {is_orchestrator}, Command: {command[:50]}")
    
    # LAYER 1: User Approval Detection
    # Scan recent user messages for approval keywords
    approval_keywords = [
        "approve", "approved", "go ahead", "proceed", "yes",
        "commit it", "push it", "create commit", "make the commit",
        "create the commit", "do it", "please commit", "please push",
        "go ahead and commit", "go ahead with"
    ]
    
    user_approved = state.get("user_approved_commit", False)

    # Check state flag first (survives session summaries)
    if user_approved:
        return None  # Already approved

    # Check separate approval file (survives state resets by Claude Code)
    approval_file = STATE_DIR / "git_approval.flag"
    if approval_file.exists():
        return None  # Approval flag file exists

    if not user_approved:
        # Check Bash command description first (for orchestrators)
        cmd_desc = tool_input.get("description", "").lower()
        if any(keyword in cmd_desc for keyword in approval_keywords):
            state["user_approved_commit"] = True
            save_state(state)
            user_approved = True
            log_event("GIT_APPROVAL", f"Approved via command description: {cmd_desc[:50]}")
        
        # Scan last 20 messages for user approval
        if not user_approved:
            recent_messages = messages[-20:] if len(messages) > 20 else messages
            log_event("GIT_APPROVAL_DEBUG", f"Scanning {len(recent_messages)} recent messages")
            for msg in reversed(recent_messages):
                if msg.get("role") == "user":
                    # Handle both string content and list of content blocks
                    raw_content = msg.get("content", "")
                    if isinstance(raw_content, list):
                        msg_content = " ".join(
                            block.get("text", "") if isinstance(block, dict) else str(block)
                            for block in raw_content
                        ).lower()
                    else:
                        msg_content = str(raw_content).lower()
                    if any(keyword in msg_content for keyword in approval_keywords):
                        state["user_approved_commit"] = True
                        save_state(state)
                        user_approved = True
                        log_event("GIT_APPROVAL", f"Approved via user message: {msg_content[:50]}")
                        break
    
    if not user_approved:
        return block(
            "[GIT APPROVAL] User approval required before commit/push\n\n"
            "No approval detected in conversation. User must explicitly approve.\n\n"
            "Approval phrases:\n"
            "  - \"go ahead and commit\"\n"
            "  - \"approved\"\n"
            "  - \"yes, commit it\"\n"
            "  - \"proceed\"\n\n"
            "Once approved, you can proceed with git operations."
        )
    
    # LAYER 2 & 3: Only apply to commits, not pushes
    if not is_commit:
        return None
    
    # Orchestrator bypass: Skip Layer 2 & 3 for workflow-initiated commits
    if is_orchestrator:
        log_event("GIT_APPROVAL", "Orchestrator mode: Skipping Layer 2 & 3 checks")
        return None  # Allow commit with only Layer 1 approval
    
    # LAYER 2: Test Execution Requirement
    tests_executed = state.get("tests_executed", False)
    
    if not tests_executed:
        return block(
            "[GIT APPROVAL] Tests must be executed before commit\n\n"
            "No test execution detected this session.\n\n"
            "Run tests first:\n"
            "  - pytest\n"
            "  - npm test\n"
            "  - cargo test\n"
            "  - go test\n"
            "  - make test\n\n"
            "This prevents committing untested code."
        )
    
    # LAYER 3: [VERIFY] Signal Detection
    verify_signal = state.get("verify_signal_given", False)

    if not verify_signal:
        # Check command description first (for current response)
        cmd_desc = tool_input.get("description", "")
        if "verified" in cmd_desc.lower() or "[verify]" in cmd_desc.lower():
            state["verify_signal_given"] = True
            save_state(state)
            verify_signal = True
            log_event("VERIFY_SIGNAL", f"Verified via command description: {cmd_desc[:50]}")

        # Scan assistant messages for [VERIFY] pattern
        if not verify_signal:
            for msg in reversed(messages):
                if msg.get("role") == "assistant":
                    msg_content = msg.get("content", "")
                    # Look for [VERIFY] tests: ✓ | types: ✓ | lint: ✓
                    if re.search(r'\[VERIFY\].*tests:.*✓.*types:.*✓.*lint:.*✓', msg_content):
                        state["verify_signal_given"] = True
                        save_state(state)
                        verify_signal = True
                        break
    
    if not verify_signal:
        return block(
            "[GIT APPROVAL] [VERIFY] signal required before commit\n\n"
            "Quality checks not verified. Output [VERIFY] signal first:\n\n"
            "[VERIFY] tests: ✓ | types: ✓ | lint: ✓\n\n"
            "This confirms all quality checks passed before committing."
        )
    
    return None


def check_verify_required(tool_name: str, tool_input: dict, state: dict) -> dict | None:
    """Block git commit unless verify has passed."""
    tool_input, state = _validate_inputs(tool_input=tool_input, state=state)
    if tool_name != "Bash":
        return None

    command = tool_input.get("command", "")

    # Only check git commit commands
    if not re.search(r'\bgit\s+commit\b', command):
        return None

    # Check if verify enforcement is enabled
    config = load_json(CONFIG_FILE)
    if not config.get("verify_required", False):
        return None  # Verify enforcement disabled

    # Check if verify has passed
    if state.get("verify_passed", False):
        return None  # Verify passed, allow commit

    return block(
        "[VERIFY REQUIRED] Git commit blocked - verification not passed.\n"
        "Run /verify (or python3 ~/.claude/plugins/agent-swarm/scripts/verify.py)\n"
        "to check: ruff, black, mypy, pytest\n"
        "All checks must pass before committing."
    )


def reset_verify_on_edit(tool_name: str, tool_input: dict, state: dict) -> None:
    """Reset verify_passed flag when files are edited."""
    tool_input, state = _validate_inputs(tool_input=tool_input, state=state)
    if tool_name not in WRITE_TOOLS:
        return

    # Reset the flag since code has changed
    if state.get("verify_passed", False):
        state["verify_passed"] = False
        save_state(state)
        log_event("VERIFY_RESET", f"verify_passed reset due to {tool_name}")


def check_tool_version_mismatch(tool_name: str, tool_input: dict, state: dict) -> dict | None:
    """Warn if local tool versions don't match pyproject.toml.

    Uses verification_gates module to check tool versions.
    """
    if not VERIFICATION_GATES_AVAILABLE:
        return None

    # Only check once per session, on first lint/format command
    if state.get("tool_versions_checked"):
        return None

    # Check on lint/format commands
    if tool_name != "Bash":
        return None

    command = tool_input.get("command", "")
    if not any(x in command for x in ["ruff", "black", "pylint", "mypy"]):
        return None

    # Mark as checked
    state["tool_versions_checked"] = True
    save_state(state)

    # Get cwd from input or use default
    import os
    cwd = os.getcwd()

    warning_msg = check_tool_versions(cwd)
    if warning_msg:
        return allow_with_warning(tool_name, tool_input, warning_msg)

    return None


def check_verification_claims(tool_name: str, tool_input: dict, state: dict, messages: list) -> dict | None:
    """Block [VERIFY] or completion claims without actual verification runs.

    Uses verification_gates module to track lint/test runs and block premature
    completion claims.
    """
    if not VERIFICATION_GATES_AVAILABLE:
        return None

    # Only check on git commit attempts (most critical gate)
    if tool_name != "Bash":
        return None

    command = tool_input.get("command", "")
    if "git commit" not in command:
        return None

    # Get recent assistant messages to check for verification claims
    recent_content = ""
    for msg in reversed(messages[-10:]):
        if msg.get("role") == "assistant":
            content = msg.get("content", "")
            if isinstance(content, list):
                content = " ".join(
                    block.get("text", "") if isinstance(block, dict) else str(block)
                    for block in content
                )
            recent_content += str(content) + "\n"

    # Check if verification claims are made without actual runs
    error_msg = check_verify_signal(recent_content)
    if error_msg:
        return block(error_msg)

    return None




def check_greptile_gate(tool_name: str, tool_input: dict, state: dict, messages: list) -> dict | None:
    """Block git commit when unaddressed P0 Greptile comments exist.

    Uses cached Greptile state from verification_gates module. The state is
    populated when the agent calls the Greptile MCP tool - hooks cannot call
    MCP tools directly.

    Also uses review_gate (P4 module) for SHA tracking to ensure reviews
    are not stale.

    Triggers on:
    - git commit commands
    - Completion claims mentioning "ready for merge" or "PR ready"
    """
    if not VERIFICATION_GATES_AVAILABLE:
        return None

    # Only check on git commit attempts
    if tool_name != "Bash":
        return None

    command = tool_input.get("command", "")

    # Track pushes with review_gate (P4 module)
    if NEW_MODULES_AVAILABLE and "git push" in command:
        # Get current HEAD SHA
        import subprocess
        try:
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                sha = result.stdout.strip()
                on_push(sha)
        except Exception:
            pass

    if "git commit" not in command:
        return None

    # Check review_gate for stale reviews (P4 module)
    if NEW_MODULES_AVAILABLE:
        allowed, msg = check_review_allowed()
        if not allowed:
            return block(f"[REVIEW GATE] {msg}\nReviews must be current before committing.")

    # Try to detect PR number from git branch or state
    # Look for PR number in state or recent messages
    pr_number = state.get("current_pr_number")
    repo = state.get("current_repo", "c-daly/apollo")

    if not pr_number:
        # Try to extract from branch name (feature/xxx-123 or pr-123)
        try:
            import subprocess
            result = subprocess.run(
                ["git", "branch", "--show-current"],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                branch = result.stdout.strip()
                import re
                # Match patterns like feature/foo-123, pr-123, etc.
                match = re.search(r'[/-](\d+)$', branch)
                if match:
                    pr_number = int(match.group(1))
        except Exception:
            pass

    if not pr_number:
        # No PR number available, skip check gracefully
        return None

    # Check for unaddressed P0 comments using cached state
    error_msg = check_greptile_comments(pr_number, repo)
    if error_msg:
        return block(error_msg)

    return None

def check_commit_attribution(tool_name: str, tool_input: dict, state: dict) -> dict | None:
    """Block commit messages with AI attributions.

    Per project standards, commit messages should not contain:
    - Co-Authored-By: Claude/AI/etc
    - Generated by Claude
    - AI attribution markers
    """
    tool_input, state = _validate_inputs(tool_input=tool_input, state=state)
    if tool_name != "Bash":
        return None

    command = tool_input.get("command", "")

    # Only check git commit commands
    if not re.search(r'\bgit\s+commit\b', command):
        return None

    # Check for common attribution patterns (case-insensitive)
    attribution_patterns = [
        r'Co-Authored-By:',
        r'Generated\s+(by|with)\s+(Claude|AI|GPT|Anthropic)',
        r'🤖',  # Robot emoji often used for AI attribution
        r'\[AI\]',
        r'\[Claude\]',
    ]

    for pattern in attribution_patterns:
        if re.search(pattern, command, re.IGNORECASE):
            return block(
                "[ATTRIBUTION BLOCKED] Commit message contains AI attribution.\n"
                "Per project standards, commit messages should not include:\n"
                "- Co-Authored-By: Claude/AI markers\n"
                "- 'Generated by' attributions\n"
                "- AI/Claude markers or emojis\n"
                "Remove the attribution and try again."
            )

    return None


def check_coverage_required(tool_name: str, tool_input: dict, state: dict) -> dict | None:
    """Block git commit unless coverage meets threshold.

    Coverage enforcement:
    - Set state["coverage_percentage"] after running coverage
    - Set config["coverage_required"] = true to enable enforcement
    - Set config["coverage_threshold"] = 80 for threshold (default 80%)
    """
    tool_input, state = _validate_inputs(tool_input=tool_input, state=state)
    if tool_name != "Bash":
        return None

    command = tool_input.get("command", "")

    # Only check git commit commands
    if not re.search(r'\bgit\s+commit\b', command):
        return None

    # Check if coverage enforcement is enabled
    config = load_json(CONFIG_FILE)
    if not config.get("coverage_required", False):
        return None  # Coverage enforcement disabled

    # Get threshold (default 80%)
    threshold = config.get("coverage_threshold", 80)

    # Check if coverage has been recorded
    coverage = state.get("coverage_percentage")
    if coverage is None:
        return block(
            f"[COVERAGE REQUIRED] Git commit blocked - coverage not measured.\n"
            f"Run: poetry run pytest --cov=src --cov-report=term-missing\n"
            f"Then set state['coverage_percentage'] = <value>\n"
            f"Required threshold: {threshold}%"
        )

    # Check if coverage meets threshold
    if coverage >= threshold:
        return None  # Coverage meets threshold, allow commit

    return block(
        f"[COVERAGE REQUIRED] Git commit blocked - coverage below threshold.\n"
        f"Current: {coverage}% | Required: {threshold}%\n"
        f"Add tests to improve coverage before committing."
    )


def check_pr_completion_gate(tool_name: str, tool_input: dict, state: dict, messages: list) -> dict | None:
    """
    PR completion composite gate - blocks 'PR ready' claims unless ALL conditions met.

    Triggers on:
    - git push
    - gh pr create
    - Messages claiming 'ready for merge'

    Checks:
    1. Lint has been run (from verification state)
    2. Tests have been run and passed
    3. No unaddressed P0 Greptile comments (placeholder)
    """
    if not VERIFICATION_GATES_AVAILABLE:
        return None

    # Detect triggering conditions
    is_git_push = False
    is_pr_create = False
    is_merge_claim = False

    if tool_name == "Bash":
        command = tool_input.get("command", "")
        is_git_push = re.search(r'\bgit\s+push\b', command) is not None
        is_pr_create = re.search(r'\bgh\s+pr\s+create\b', command) is not None

    # Check recent messages for merge readiness claims
    merge_claim_patterns = [
        r'ready\s+for\s+merge',
        r'ready\s+to\s+merge',
        r'PR\s+is\s+ready',
        r'pull\s+request\s+is\s+ready',
        r'can\s+be\s+merged',
        r'good\s+to\s+merge',
        r'merge\s+ready',
    ]

    for msg in reversed(messages[-5:]):
        if msg.get("role") == "assistant":
            raw_content = msg.get("content", "")
            if isinstance(raw_content, list):
                content = " ".join(
                    block.get("text", "") if isinstance(block, dict) else str(block)
                    for block in raw_content
                )
            else:
                content = str(raw_content)

            if any(re.search(pattern, content, re.IGNORECASE) for pattern in merge_claim_patterns):
                is_merge_claim = True
                break

    # Only enforce gate on triggering conditions
    if not (is_git_push or is_pr_create or is_merge_claim):
        return None

    # Extract PR number if available (for Greptile check)
    pr_number = state.get("current_pr_number", 0)
    repo = state.get("current_repo", "")

    # Run composite gate check
    is_ready, issues = check_pr_ready(pr_number, repo)

    if not is_ready:
        trigger_type = "git push" if is_git_push else "gh pr create" if is_pr_create else "merge claim"
        return block(
            f"[PR COMPLETION GATE] Blocked {trigger_type} - PR not ready.\n\n"
            f"Issues:\n" +
            "\n".join(f"  - {issue}" for issue in issues) +
            "\n\nResolve all issues before claiming PR is ready or pushing."
        )

    return None


def check_subagent_model(tool_name: str, tool_input: dict, state: dict) -> dict | None:
    """Enforce correct model usage when spawning subagents."""
    tool_input, state = _validate_inputs(tool_input=tool_input, state=state)
    if tool_name != "Task":
        return None

    subagent_type = tool_input.get("subagent_type", "")
    specified_model = tool_input.get("model", "")

    # Use agent_protocol if available (P5 module) - provides unified validation
    if NEW_MODULES_AVAILABLE:
        phase = state.get("phase") or state.get("iterate_phase") or ""
        valid, msg = validate_agent_spawn(subagent_type, specified_model, phase)
        if not valid:
            protocol = get_protocol(subagent_type)
            correct_model = protocol.model if protocol else "sonnet"
            return block(
                f"[AGENT PROTOCOL] {msg}\n"
                f"Agent '{subagent_type}' requires model='{correct_model}'\n"
                f"Current phase: {phase}"
            )
        return None  # P5 module handled validation, skip legacy check

    # Fallback to legacy check if P5 module not available
    # Skip if not an agent type we track
    if subagent_type not in AGENT_MODEL_MAP:
        return None
    
    expected_model = AGENT_MODEL_MAP[subagent_type]
    
    # If no model specified, warn and suggest
    if not specified_model:
        return block(
            f"[MODEL] Task missing 'model' parameter.\n"
            f"  For {subagent_type}, use: model: \"{expected_model}\""
        )
    
    # If wrong model, block with correction
    if specified_model != expected_model:
        # Allow downgrade (sonnet agent using haiku for simple task)
        if expected_model == "sonnet" and specified_model == "haiku":
            return None  # Downgrade is OK
        
        # Block upgrade or wrong model
        return block(
            f"[MODEL] Wrong model for {subagent_type}.\n"
            f"  Expected: {expected_model}, got: {specified_model}\n"
            f"  Downgrades OK (sonnet->haiku), upgrades blocked."
        )
    
    return None

def check_episodic_memory_suggestion(tool_name: str, tool_input: dict, state: dict):
    """Stronger suggestion for episodic memory search at key moments"""
    tool_input, state = _validate_inputs(tool_input=tool_input, state=state)

    # Track suggestion count (allow multiple, but limit spam)
    suggestion_count = state.get("memory_search_suggested", 0)
    if suggestion_count >= 3:
        return None  # After 3 suggestions, stop

    # Scenario 1: Research/exploration tasks (most important)
    if tool_name == "Task":
        subagent_type = tool_input.get("subagent_type", "")
        prompt = tool_input.get("prompt", "").lower()

        research_keywords = ["explore", "investigate", "understand", "how does", "find out", "research", "explain", "analyze"]
        is_research = (subagent_type in ["Explore", "explorer", "research", "researcher"] or
                      any(keyword in prompt for keyword in research_keywords))

        if is_research:
            state["memory_search_suggested"] = suggestion_count + 1
            save_state(state)

            return {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "allow",
                    "permissionDecisionWarning": "\n============================================================\n"
                    "🧠 EPISODIC MEMORY SUGGESTION\n"
                    "============================================================\n"
                    "Before exploring, consider searching past conversations.\n"
                    "You might find:\n"
                    "  • Previous work in this codebase\n"
                    "  • Decisions and rationale for designs\n"
                    "  • Known issues or gotchas\n"
                    "  • Solutions to similar problems\n\n"
                    "Search with:\n"
                    "  Skill: episodic-memory:search-conversations\n"
                    "  Tool: mcp__plugin_episodic-memory_episodic-memory__search\n\n"
                    "Example queries:\n"
                    f"  - '{prompt[:50]}'\n"
                    "  - '<feature/component name>'\n"
                    "  - '<architectural decision>'\n"
                    "============================================================"
                }
            }

    # Scenario 2: Extensive code reading/searching (new codebase exploration)
    search_count = state.get("search_count", 0)
    read_count = state.get("read_count", 0)

    if (search_count + read_count >= 5) and suggestion_count == 0:
        # First time doing extensive exploration
        state["memory_search_suggested"] = 1
        save_state(state)

        return {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "allow",
                "permissionDecisionWarning": "\n============================================================\n"
                "🧠 EPISODIC MEMORY SUGGESTION\n"
                "============================================================\n"
                "You're exploring unfamiliar code.\n"
                "Past conversations might have context about:\n"
                "  • Architecture and design decisions\n"
                "  • Where key features are implemented\n"
                "  • Known issues or technical debt\n\n"
                "Consider: episodic-memory:search-conversations\n"
                "============================================================"
            }
        }

    return None

def check_workflow_compliance(tool_name: str, tool_input: dict, state: dict, messages: list) -> dict | None:
    """Enforce CLAUDE.md workflow compliance."""

    # EARLY EXIT: Always allow workflow initialization commands (before any other checks)
    if tool_name == "Bash":
        command = tool_input.get("command", "")
        workflow_patterns = ["lib/workflow.py", "workflow.py iterate", "workflow.py orchestrate",
                            "workflow.py status", "workflow.py advance", "workflow.py reset"]
        if any(pattern in command for pattern in workflow_patterns):
            return None  # Always allow workflow commands

    # Parse messages to detect classification and workflow invocation
    classification_pattern = r'\[(TRIVIAL|CONVERSATION|RESEARCH)\]'
    
    for msg in messages:
        if msg.get("role") == "assistant":
            raw_content = msg.get("content", "")
            # Handle both string and list content formats
            if isinstance(raw_content, list):
                content = " ".join(
                    block.get("text", "") if isinstance(block, dict) else str(block)
                    for block in raw_content
                )
            else:
                content = str(raw_content)

            # Check for classification
            match = re.search(classification_pattern, content)
            if match:
                new_classification = match.group(1)
                # Allow classification to update (user can change from RESEARCH to TRIVIAL, etc.)
                if state.get("classification_type") != new_classification:
                    # Classification changed - reset workflow tracking
                    state["classification_given"] = True
                    state["classification_type"] = new_classification
                    state["workflow_invoked"] = False  # May not need workflow for new task type
                    save_state(state)
                elif not state.get("classification_given"):
                    # First classification
                    state["classification_given"] = True
                    state["classification_type"] = new_classification
                    save_state(state)
#             
            # Check for workflow invocation (/orchestrate or /iterate)
            workflow_patterns = [
                '"skill": "agent-swarm:orchestrate"',
                'Skill(skill="agent-swarm:orchestrate")',
                '"skill": "iterate"',
                'Skill(skill="iterate")',
                '/orchestrate',
                '/iterate',
            ]
            if any(pattern in content for pattern in workflow_patterns):
                state["workflow_invoked"] = True
                save_state(state)
            
            # Check for episodic memory search
            if 'episodic-memory' in content and 'search' in content:
                state["episodic_search_done"] = True
                save_state(state)

    # Use classification_validator if available (P3 module)
    # Validates that classification matches actual task complexity
    if NEW_MODULES_AVAILABLE:
        classification = state.get("classification_type")
        task_desc = state.get("current_task", "")
        if classification and tool_name in {"Write", "Edit", "mcp__plugin_serena_serena__replace_symbol_body"}:
            valid, reason = validate_classification(
                claimed=classification,
                task=task_desc,
                state=state
            )
            if not valid:
                return block(f"[CLASSIFICATION MISMATCH] {reason}")

    # Block editing tools in CONVERSATION/RESEARCH mode unless workflow invoked
    edit_tools = {"Write", "Edit", "NotebookEdit",
                  "mcp__plugin_serena_serena__replace_symbol_body",
                  "mcp__plugin_serena_serena__create_text_file",
                  "mcp__plugin_serena_serena__replace_content",
                  "mcp__plugin_serena_serena__insert_after_symbol",
                  "mcp__plugin_serena_serena__insert_before_symbol"}

    classification = state.get("classification_type")
    # Use Workflow class if available, fallback to state
    workflow_invoked = Workflow.is_active() if WORKFLOW_AVAILABLE else state.get("workflow_invoked", False)

    # TRIVIAL allows editing without workflow
    if classification == "TRIVIAL":
        pass  # Allow all tools

    # CONVERSATION and RESEARCH block editing unless workflow invoked
    elif classification in ("CONVERSATION", "RESEARCH") and tool_name in edit_tools:
        if not workflow_invoked:
            # Allow /tmp/ utility scripts
            file_path = tool_input.get("file_path", "")
            if not file_path.startswith("/tmp/"):
                return block(
                    f"[BLOCKED] Editing tools blocked in [{classification}] mode.\n\n"
                    "To edit files, invoke a workflow first:\n"
                    "  /iterate    - For autonomous implementation with Greptile review\n"
                    "  /orchestrate - For discovery/design with user checkpoints\n\n"
                    "Or use [TRIVIAL] for one-liner fixes."
                )

    # Block Bash in CONVERSATION/RESEARCH (except gh_wrapper)
    # Note: workflow.py commands are handled by early exit at function start
    if tool_name == "Bash" and classification in ("CONVERSATION", "RESEARCH", None):
        if not workflow_invoked:
            command = tool_input.get("command", "")
            # Allow gh_wrapper calls
            if "gh_wrapper.py" not in command:
                return block(
                    f"[BLOCKED] Bash blocked in [{classification or 'no classification'}] mode.\n\n"
                    "For git/gh commands, use the wrapper:\n"
                    "  python3 scripts/gh_wrapper.py git status\n"
                    "  python3 scripts/gh_wrapper.py git log -5\n"
                    "  python3 scripts/gh_wrapper.py pr list\n\n"
                    "For other shell operations, invoke a workflow first:\n"
                    "  /iterate or /orchestrate"
                )

    # Monitor agent for classification validation
    if MONITOR_AVAILABLE and needs_monitoring(tool_name, tool_input, state):
        decision = call_monitor_agent(tool_name, tool_input, state)
        if decision:
            result = format_monitor_result(decision)
            # format_monitor_result returns proper hook format with hookSpecificOutput
            hook_output = result.get("hookSpecificOutput", {})
            if hook_output.get("permissionDecision") == "deny":
                return result  # Return the properly formatted hook response

    # Enforce rules for code-editing tools
    code_tools = ["Edit", "Write", "mcp__plugin_serena_serena__replace_symbol_body",
                  "mcp__plugin_serena_serena__insert_after_symbol",
                  "mcp__plugin_serena_serena__insert_before_symbol"]

    if tool_name in code_tools:
        # Rule 1: Must give classification first
        # Exempt /tmp/ utility scripts from classification requirement
        classification_given = False

        if tool_name in ["Write", "Edit"] and tool_input:
            file_path = tool_input.get("file_path", "")
            if file_path.startswith("/tmp/"):
                classification_given = True  # /tmp/ scripts are tools, not project code

        if not classification_given:
            # Track edits this response - skip check on first edit (classification in current output)
            edits_this_response = state.get("edits_this_response", 0)

            # Skip check on first edit of response - assume classification in current output
            if edits_this_response == 0:
                classification_given = True
                state["edits_this_response"] = 1
                state["classification_given"] = True  # Persist for subsequent edits in same response
                save_state(state)
            else:
                classification_given = state.get("classification_given")

        if not classification_given:
            return block(
                "[BLOCKED] Classification required before editing code.\n\n"
                "REQUIRED ACTION: Output classification tag as first line of your response\n"
                "✓ DO: Start response with [TRIVIAL], [CONVERSATION], or [RESEARCH]\n"
                "✗ DON'T: Try Edit, Write, or other tools without classification first\n\n"
                "Classification format: [TRIVIAL|CONVERSATION|RESEARCH]\n\n"
                "Criteria:\n"
                "- TRIVIAL: One-liner fix (editing allowed)\n"
                "- CONVERSATION: Default mode (invoke workflow to edit)\n"
                "- RESEARCH: Exploring/reading (no code changes)"
            )

    # Parallelism advisory for Task tool
    if tool_name == "Task":
        recent_tasks = state.get("recent_task_spawns", [])
        current_time = datetime.now()
        recent_tasks.append(current_time.isoformat())
        five_min_ago = (current_time - timedelta(minutes=5)).isoformat()
        recent_tasks = [t for t in recent_tasks if t > five_min_ago]
        state["recent_task_spawns"] = recent_tasks
        one_min_ago = (current_time - timedelta(minutes=1)).isoformat()
        recent_count = len([t for t in recent_tasks if t > one_min_ago])
        if recent_count >= 2 and not state.get("parallelism_tip_shown"):
            log_event("PARALLELISM_ADVISORY", f"Sequential Task spawns: {recent_count}")
            state["parallelism_tip_shown"] = True
            save_state(state)
            return allow_with_warning(
                tool_name, tool_input,
                "💡 PARALLELISM TIP: Spawn multiple agents in ONE message.\n\n"
                "❌ Sequential: Message 1→Wait→Message 2→Wait (slow)\n"
                "✅ Parallel: Multiple Task() in Message 1 (fast)\n\n"
                "All agents run concurrently!"
            )
        save_state(state)

    # === SUBAGENT TRACKING ===
    # Track subagent spawns at PreToolUse (PostToolUse doesn't work for async Task tools)
    if tool_name == "Task":
        # datetime and json already imported at module level

        subagent_type = tool_input.get("subagent_type", "unknown")
        description = tool_input.get("description", "")

        # Log to activity.log
        activity_file = STATE_DIR / "activity.log"
        try:
            with open(activity_file, "a") as f:
                timestamp = datetime.now().isoformat()
                f.write(f"[{timestamp}] SUBAGENT: {subagent_type} - {description}\n")
        except Exception as e:
            log_warning(f"Failed to log activity: {e}")

        # Update subagent_metrics.json
        metrics_file = STATE_DIR / "subagent_metrics.json"
        try:
            if metrics_file.exists():
                metrics = json.loads(metrics_file.read_text())
            else:
                metrics = []

            metrics.append({
                "type": subagent_type,
                "description": description,
                "timestamp": datetime.now().isoformat()
            })

            metrics_file.write_text(json.dumps(metrics, indent=2))
        except Exception as e:
            log_warning(f"Failed to update metrics: {e}")



    return None


def check_agent_spawning_enforcement(tool_name: str, tool_input: dict, state: dict, input_data: dict) -> dict | None:
    """Enforce agent spawning when multiple pending tasks exist.

    If there are >1 pending tasks and <=1 in_progress, the agent should be
    using Task tool to spawn subagents for parallel work. Block other tools
    until this is done.

    Uses check_agent_spawning from verification_gates module.
    """
    if not VERIFICATION_GATES_AVAILABLE:
        return None

    # Allow Task tool - that's how agents are spawned
    if tool_name == "Task":
        return None

    # Allow TodoWrite - needed to manage the task list
    if tool_name == "TodoWrite":
        return None

    # Extract todo list from conversation context
    # The todo list comes from the conversation's TodoWrite state
    todo_list = []

    # Try to get from input_data's conversation/messages
    messages = input_data.get("messages", [])
    for msg in reversed(messages):
        # Look for todo state in the conversation
        if isinstance(msg, dict):
            content = msg.get("content", "")
            if isinstance(content, str) and "[TODO]" in content:
                # Parse todo items from message content
                # Format: [TODO] status: task
                for line in content.split("\n"):
                    if line.strip().startswith("- ["):
                        # Parse checkbox format: - [ ] pending, - [x] completed, - [>] in_progress
                        if "[ ]" in line:
                            todo_list.append({"status": "pending", "content": line})
                        elif "[>]" in line or "[~]" in line:
                            todo_list.append({"status": "in_progress", "content": line})
                        elif "[x]" in line:
                            todo_list.append({"status": "completed", "content": line})

    # Also check state for cached todo list
    if not todo_list and "todo_list" in state:
        todo_list = state.get("todo_list", [])

    # If no todo list found, don't block
    if not todo_list:
        return None

    # Call the verification gate
    block_msg = check_agent_spawning(todo_list, max_inline=1)
    if block_msg:
        return block(block_msg)

    return None



def main():
    # Read input from stdin
    try:
        input_data = json.loads(sys.stdin.read())
    except json.JSONDecodeError:
        print(json.dumps(allow()))
        return

    tool_name = input_data.get("tool_name", "")
    tool_input = input_data.get("tool_input", {})
    messages = input_data.get("messages", [])

    # Load session state
    state = load_json(STATE_FILE)

    # Detect new user turn (reset edits_this_response counter)
    # Check if there's a user message AFTER the last tool execution
    last_tool_time_str = state.get("last_tool_time")

    if messages:
        # Find most recent user message
        for msg in reversed(messages):
            if msg.get("role") == "user":
                # Found user message - check if it's from a new turn
                # Simple heuristic: if counter > 0, assume new user message = new turn
                if state.get("edits_this_response", 0) > 0:
                    # Reset for new turn
                    state["edits_this_response"] = 0
                    log_event("COUNTER_RESET", "New user turn detected, edits counter reset")
                    save_state(state)
                break

    # Check autopilot first
    result = check_autopilot(state)
    if result:
        print(json.dumps(result))
        return

    # Layer 2: Pattern Detection (early intervention for batch operations)
    if MONITOR_AVAILABLE and tool_name in (SEARCH_TOOLS | {"Read"}):
        from monitor_agent import detect_batch_need
        
        batch_decision = detect_batch_need(tool_name, tool_input, state, messages)
        if batch_decision and not batch_decision.get("allowed", True):
            log_event("PATTERN_BLOCK", f"{tool_name}: {batch_decision['message'][:50]}")
            update_stats(False, batch_decision["message"], tool_name)
            print(json.dumps(block(batch_decision["message"])))
            return

    # Reset verify flag on edits (side effect, not a check)
    reset_verify_on_edit(tool_name, tool_input, state)

    # Run all enforcement checks
    checks = [
        check_workflow_compliance(tool_name, tool_input, state, messages),
        check_phase_restrictions(tool_name, state, tool_input),
        check_checkpoint_approval(tool_name, tool_input, state),
        check_verify_required(tool_name, tool_input, state),
        check_verification_claims(tool_name, tool_input, state, messages),  # Block [VERIFY] without runs
        check_tool_version_mismatch(tool_name, tool_input, state),  # Warn on pyproject.toml mismatch
        check_mcp_script_requirement(tool_name, tool_input, state),
        check_smart_tool_usage(tool_name, tool_input, state),
        check_token_efficiency(tool_name, tool_input, state),
        check_scope_discipline(tool_name, tool_input, state),
        check_agent_spawning_enforcement(tool_name, tool_input, state, input_data),  # Enforce agent spawning for parallel work
        check_git_safety(tool_name, tool_input, state),
        check_git_approval_layers(tool_name, tool_input, state, messages),  # 3-layer approval
        check_commit_attribution(tool_name, tool_input, state),  # Block AI attributions
        check_greptile_gate(tool_name, tool_input, state, messages),  # Block commit with unaddressed P0 Greptile comments
        check_coverage_required(tool_name, tool_input, state),  # Enforce coverage threshold
        check_pr_completion_gate(tool_name, tool_input, state, messages),  # PR readiness gate
        check_subagent_model(tool_name, tool_input, state),
        check_episodic_memory_suggestion(tool_name, tool_input, state),
    ]

    for result in checks:
        if result:
            # Log the block
            msg = result.get("hookSpecificOutput", {}).get("permissionDecisionReason", "blocked")
            log_event("BLOCKED", f"{tool_name}: {msg[:50]}")
            update_stats(allowed=False, reason=msg, tool_name=tool_name)
            print(json.dumps(result))
            return

    # Default: allow
    # Enhanced logging for Bash - include command for script detection
    if tool_name == "Bash":
        command = tool_input.get("command", "")
        # Truncate very long commands
        cmd_preview = command[:200] if len(command) <= 200 else command[:200] + "..."
        log_event("ALLOWED", f"Bash: {cmd_preview}")
    else:
        log_event("ALLOWED", tool_name)
    
    update_stats(allowed=True, tool_name=tool_name)
    print(json.dumps(allow()))

if __name__ == "__main__":
    main()
