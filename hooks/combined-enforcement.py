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
from datetime import datetime, timedelta
from pathlib import Path

# Try to import monitor agent (optional dependency)
try:
    from monitor_agent import needs_monitoring, call_monitor_agent, format_monitor_result
    MONITOR_AVAILABLE = True
except ImportError:
    MONITOR_AVAILABLE = False

# Configuration
STATE_FILE = Path.home() / ".claude/plugins/agent-swarm/.state/session.json"
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
        except:
            pass

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

def load_json(path: Path) -> dict:
    """Load JSON file safely."""
    if path.exists():
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, IOError):
            pass
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
    
    # FIRST: State file protection (always enforced, regardless of phase)
    # Only block WRITES to state files, allow reads (ls, cat, grep, etc.)
    if tool_name == "Bash" and tool_input:
        command = tool_input.get("command", "").strip()
        if '.state' in command or 'session.json' in command:
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
            if any(re.search(pattern, command) for pattern in write_patterns):
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
    
    # SECOND: Allow critical documentation files (handoffs, notes) from any phase
    if tool_name == "Write" and tool_input:
        from pathlib import Path
        file_path = tool_input.get("file_path", "")
        filename = Path(file_path).name
        CRITICAL_FILES = {"HANDOFF.md", "SESSION_NOTES.md"}
        if filename in CRITICAL_FILES:
            return None  # Allow handoff writes from any phase

    phase = state.get("phase", "").lower()

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
            f"[PHASE: intake] Bash restricted to Python execution only.\n"
            f"Allowed patterns:\n"
            f"  - python3 -c \"...\"\n"
            f"  - cat > /tmp/script.py << 'EOF'\n"
            f"  - python3 /tmp/script.py\n"
            f"  - rm /tmp/*.py\n"
            f"For other operations, use allowed tools: Read, Glob, Grep, AskUserQuestion"
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
        # Check both specific tool name AND tool category
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
    from datetime import datetime, timedelta

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
    current_phase = state.get("phase", "")
    last_phase = state.get("last_phase", "")
    
    if current_phase != last_phase and last_phase:
        # Phase changed, reset counters
        state["search_count"] = 0
        state["read_count"] = 0
        state["files_read"] = []
        state["edits_this_response"] = 0  # Reset classification enforcement counter
        state["last_phase"] = current_phase
        log_event("COUNTER_RESET", f"Phase changed from '{last_phase}' to '{current_phase}', counters reset")
        save_state(state)
    elif not last_phase:
        # Initialize last_phase tracking
        state["last_phase"] = current_phase
        save_state(state)

    # Detect new conversation and reset counters
    # If more than 30 minutes since last tool use, consider it a new conversation
    last_tool_time = state.get("last_tool_time")
    current_time = datetime.now().isoformat()

    if last_tool_time:
        try:
            last_time = datetime.fromisoformat(last_tool_time)
            time_since_last = datetime.now() - last_time

            # Reset counters if been idle for 30+ minutes (new conversation)
            if time_since_last > timedelta(minutes=30):
                state["search_count"] = 0
                state["read_count"] = 0
                state["files_read"] = []
                state["edits_this_response"] = 0  # Reset classification enforcement counter
                log_event("COUNTER_RESET", "New conversation detected, counters reset")
                save_state(state)  # Persist reset immediately
        except (ValueError, TypeError):
            pass  # Invalid timestamp, ignore

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
    phase = state.get("phase", "")
    task_summary = state.get("task_summary", "")

    # Only enforce during active phases
    if not phase or phase in ("intake", "research", "explore"):
        return None

    # Check if spawning subagent without clear purpose
    if tool_name == "Task":
        prompt = tool_input.get("prompt", "")
        if len(prompt) < 20:
            return block(
                f"[SCOPE] Subagent prompt too vague. "
                f"Provide clear, specific instructions for the subagent."
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

    # Track repeated MCP calls of same type
    mcp_counts = state.get("mcp_counts", {})
    count = mcp_counts.get(tool_name, 0) + 1
    mcp_counts[tool_name] = count
    state["mcp_counts"] = mcp_counts
    save_state(state)

    # Block after 5th call of same MCP tool (allow sequential edits)
    if count > 5:
        return block(
            f"[BLOCKED] {tool_name} called {count} times.\n\n"
            f"REQUIRED ACTION: Write a Python script to batch operations\n"
            f"✓ DO: Create /tmp/batch_ops.py using mcp_bridge\n"
            f"✗ DON'T: Try calling the tool 'just one more time'\n"
            f"✗ DON'T: Switch to Edit, Read, or other workarounds\n\n"
            f"Why: Repeated tool calls waste tokens. Scripts are faster and tracked.\n"
            f"Ignoring this will trigger more blocks."
        )

    return None

def check_smart_tool_usage(tool_name: str, tool_input: dict, state: dict) -> dict | None:
    """Block dumb methods when smarter alternatives exist."""

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
                    f"[SMART TOOLS] Use Context7 instead of WebSearch for docs:\n"
                    f"  1. mcp__context7__resolve-library-id\n"
                    f"  2. mcp__context7__query-docs\n"
                    f"Context7 has curated, up-to-date docs. WebSearch wastes tokens on noise."
                )

    # Read for code understanding → use Serena
    if tool_name == "Read":
        file_path = tool_input.get("file_path", "")
        # Code file extensions
        code_exts = [".py", ".ts", ".js", ".tsx", ".jsx", ".go", ".rs", ".java", ".rb"]

        if any(file_path.endswith(ext) for ext in code_exts):
            # Check if this looks like exploration vs targeted read
            phase = state.get("phase", "")
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

        # CRITICAL: Detect Bash abuse patterns (cat/grep/find)
        # These should NEVER be done via Bash - proper tools exist

        # cat abuse → use Read or Write tools
        # Block cat UNLESS it's receiving piped input (e.g., grep | cat)
        if 'cat' in cmd and not re.search(r'\|\s*cat\s*(?:[|;]|$)', cmd):
            # Cat reading files
            if re.search(r'\bcat\s+[^\|<>]', cmd):
                return block(
                    f"[BLOCKED] Don't use 'cat' for reading files.\n\n"
                    f"REQUIRED ACTION: Use the Read tool\n"
                    f"✓ DO: Read({{'file_path': '<path>'}})\n"
                    f"✗ DON'T: Try bash cat, sed, awk, or other shell workarounds\n\n"
                    f"Why: Bash cat wastes tokens and bypasses activity tracking.\n"
                    f"Current command: {cmd[:60]}"
                )
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
    phase = state.get("phase", "")
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

    # Monitor agent for commit message validation
    if MONITOR_AVAILABLE and "git commit" in command:
        if needs_monitoring("Bash", tool_input, state):
            decision = call_monitor_agent("Bash", tool_input, state)
            if decision:
                result = format_monitor_result(decision)
                if not result.get("allowed", True):
                    return block(result["message"])

    return None





def check_git_approval_layers(tool_name: str, tool_input: dict, state: dict, messages: list) -> dict | None:
    """
    3-layer git safety system to prevent agents from committing/pushing without proper validation.
    
    Layer 1: User approval detection - scan messages for approval keywords
    Layer 2: Test execution requirement - track test runs, block commits without tests
    Layer 3: [VERIFY] signal - require quality check signal before commits
    
    Orchestrator mode: Skips Layer 2 & 3 for workflow-initiated commits
    """
    if tool_name != "Bash":
        return None
    
    command = tool_input.get("command", "")
    
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
                    msg_content = msg.get("content", "").lower()
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
        # Scan assistant messages for [VERIFY] pattern
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

def check_subagent_model(tool_name: str, tool_input: dict, state: dict) -> dict | None:
    """Enforce correct model usage when spawning subagents."""
    if tool_name != "Task":
        return None
    
    subagent_type = tool_input.get("subagent_type", "")
    specified_model = tool_input.get("model", "")
    
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
                    "permissionDecision": "allow",
                    "message": "\n============================================================\n"
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
                "permissionDecision": "allow",
                "message": "\n============================================================\n"
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
    
    # Parse messages to detect classification and workflow invocation
    classification_pattern = r'\[(TRIVIAL|SIMPLE|COMPLEX|RESEARCH|CONVERSATION)\]'
    
    for msg in messages:
        if msg.get("role") == "assistant":
            content = msg.get("content", "")
            
            # Check for classification
            import re
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
            # Check for workflow invocation
            if '"skill": "agent-swarm:orchestrate"' in content or 'Skill(skill="agent-swarm:orchestrate")' in content:
                state["workflow_invoked"] = True
                save_state(state)
            
            # Check for episodic memory search
            if 'episodic-memory' in content and 'search' in content:
                state["episodic_search_done"] = True
                save_state(state)

    # Track file edits per session for multi-file COMPLEX enforcement
    if tool_name in {"Write", "Edit", "mcp__plugin_serena_serena__replace_symbol_body",
                     "mcp__plugin_serena_serena__create_text_file",
                     "mcp__plugin_serena_serena__replace_content"}:

        if "files_edited_this_session" not in state:
            state["files_edited_this_session"] = []

        file_path = tool_input.get("file_path") or tool_input.get("relative_path")
        if file_path:
            # Block 2nd+ file with SIMPLE classification BEFORE adding to list
            if file_path not in state["files_edited_this_session"] and len(state["files_edited_this_session"]) >= 1:
                classification = state.get("classification_type")
                if classification == "SIMPLE":
                    return {
                        "allowed": False,
                        "message": (
                            "[WORKFLOW VIOLATION] Multi-file edit detected.\n"
                            f"   Files edited: {', '.join(sorted(state['files_edited_this_session']))}\n"
                            f"   Current classification: [SIMPLE]\n"
                            "\n"
                            "Multi-file edits require [COMPLEX] classification.\n"
                            "Either:\n"
                            "1. Reclassify as [COMPLEX] and invoke workflow:orchestrate\n"
                            "2. Complete current file, then handle second file separately"
                        )
                    }

            # Add file to tracking list if not already there
            if file_path not in state["files_edited_this_session"]:
                state["files_edited_this_session"].append(file_path)
                save_state(state)

    # Monitor agent for classification validation
    if MONITOR_AVAILABLE and needs_monitoring(tool_name, tool_input, state):
        decision = call_monitor_agent(tool_name, tool_input, state)
        if decision:
            result = format_monitor_result(decision)
            if not result.get("allowed", True):
                return {
                    "allowed": False,
                    "message": result["message"]
                }

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

            # Skip check on first edit of response
            if edits_this_response == 0:
                classification_given = True
                state["edits_this_response"] = 1
                save_state(state)
            else:
                classification_given = state.get("classification_given")

        if not classification_given:
            return block(
                "[BLOCKED] Classification required before editing code.\n\n"
                "REQUIRED ACTION: Output classification tag as first line of your response\n"
                "✓ DO: Start response with [SIMPLE] or [COMPLEX] before any tool use\n"
                "✗ DON'T: Try Edit, Write, or other tools without classification first\n\n"
                "Classification format: [TRIVIAL|SIMPLE|COMPLEX|RESEARCH|CONVERSATION]\n\n"
                "Criteria:\n"
                "- TRIVIAL: One-liner fix\n"
                "- SIMPLE: Single file, <50 lines, clear requirements\n"
                "- COMPLEX: Multiple files OR architectural decisions OR unclear scope\n"
                "- RESEARCH: Exploring/reading, no code changes\n"
                "- CONVERSATION: Discussion only"
            )

        # Rule 2: COMPLEX tasks must invoke workflow
        if state.get("classification_type") == "COMPLEX" and not state.get("workflow_invoked"):
            return block(
                "[BLOCKED] [COMPLEX] tasks require workflow orchestration.\n\n"
                "REQUIRED ACTION: Invoke the orchestrator NOW\n"
                "✓ DO: Skill(skill='agent-swarm:orchestrate', args='<full task description>')\n\n"
                "✗ DON'T: Skip because you 'already know what to do'\n"
                "✗ DON'T: Rationalize that it's not really complex\n"
                "✗ DON'T: Start coding without workflow approval\n\n"
                "From CLAUDE.md: 'Invoke workflow:orchestrate BEFORE any work'\n"
                "Why: Complex tasks need planning, checkpoints, and review phases."
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
        from datetime import datetime
        import json

        subagent_type = tool_input.get("subagent_type", "unknown")
        description = tool_input.get("description", "")

        # Log to activity.log
        activity_file = STATE_DIR / "activity.log"
        try:
            with open(activity_file, "a") as f:
                timestamp = datetime.now().isoformat()
                f.write(f"[{timestamp}] SUBAGENT: {subagent_type} - {description}\n")
        except Exception:
            pass

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
        except Exception:
            pass



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

    # Run all enforcement checks
    checks = [
        check_workflow_compliance(tool_name, tool_input, state, messages),
        check_phase_restrictions(tool_name, state, tool_input),
        check_checkpoint_approval(tool_name, tool_input, state),
        check_mcp_script_requirement(tool_name, tool_input, state),
        check_smart_tool_usage(tool_name, tool_input, state),
        check_token_efficiency(tool_name, tool_input, state),
        check_scope_discipline(tool_name, tool_input, state),
        check_git_safety(tool_name, tool_input, state),
        check_git_approval_layers(tool_name, tool_input, state, messages),  # 3-layer approval
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
