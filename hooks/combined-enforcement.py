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
from datetime import datetime
from pathlib import Path

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

# Tool categories
WRITE_TOOLS = {"Edit", "Write", "NotebookEdit"}
SEARCH_TOOLS = {"Glob", "Grep"}  # Read has its own counter
RESEARCH_TOOLS = {"WebSearch", "WebFetch"}
SUBAGENT_TOOLS = {"Task"}
GIT_TOOLS = {"Bash"}  # git commands via bash

# Phase restrictions
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
MAX_DIRECT_SEARCHES = 2  # After this, must use scripts
MAX_FILE_READS = 2  # After this, must use subagent

# MCP tools allowed without script (low-cost single operations)
MCP_DIRECT_ALLOWED = {
    "mcp__plugin_serena_serena__find_symbol",
    "mcp__plugin_serena_serena__get_definition",
    "mcp__plugin_serena_serena__get_symbols_overview",
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

def check_autopilot(state: dict) -> dict | None:
    """Autopilot mode bypasses all enforcement."""
    if state.get("autopilot_override", False):
        return allow("[AUTOPILOT] Auto-approved")
    return None

def check_phase_restrictions(tool_name: str, state: dict) -> dict | None:
    """Enforce phase-specific tool restrictions."""
    phase = state.get("phase", "")

    # No phase = no restrictions
    if not phase:
        return None

    # Always allowed tools
    if tool_name in ALWAYS_ALLOWED:
        return None

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
        if tool_name not in allowed_tools and tool_name not in ALWAYS_ALLOWED:
            return block(
                f"[PHASE: {phase}] {tool_name} not allowed in this phase. "
                f"Allowed: {', '.join(allowed_tools)}"
            )

    return None

def check_token_efficiency(tool_name: str, tool_input: dict, state: dict) -> dict | None:
    """Enforce token-saving measures."""

    # Track search tool usage
    if tool_name in SEARCH_TOOLS:
        count = state.get("search_count", 0) + 1
        state["search_count"] = count
        save_state(state)

        if count > MAX_DIRECT_SEARCHES:
            return block(
                f"[TOKEN EFFICIENCY] {count} direct searches used. "
                f"Use a batch script instead:\n"
                f"```python\n"
                f"from mcp_bridge import native_glob, native_grep\n"
                f"# Batch your searches\n"
                f"```\n"
                f"Or spawn an Explorer subagent with Task tool."
            )

    # Track file reads
    if tool_name == "Read":
        count = state.get("read_count", 0) + 1
        state["read_count"] = count
        save_state(state)

        if count > MAX_FILE_READS:
            return block(
                f"[TOKEN EFFICIENCY] {count} direct file reads. "
                f"Spawn an Explorer subagent to aggregate findings, "
                f"or use a script to read and summarize."
            )

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

    # Block after 2nd call of same MCP tool
    if count > 2:
        return block(
            f"[MCP SCRIPT] {tool_name} called {count} times.\n"
            f"Batch repeated calls into a script."
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
                    f"[SMART TOOLS] Use Serena instead of Read for code understanding:\n"
                    f"  mcp__plugin_serena_serena__find_symbol - locate definitions\n"
                    f"  mcp__plugin_serena_serena__get_definition - get signature + docs\n"
                    f"  mcp__plugin_serena_serena__find_references - find usages\n"
                    f"Serena extracts structure. Read dumps entire files into context."
                )

    # Bash for git → suggest gh_wrapper for queries
    if tool_name == "Bash":
        cmd = tool_input.get("command", "")
        if cmd.startswith("gh ") and not any(x in cmd for x in ["create", "merge", "close", "edit"]):
            # Query commands, not mutating commands
            if any(x in cmd for x in ["list", "view", "status", "search"]):
                return block(
                    f"[SMART TOOLS] Use gh_wrapper.py for summarized output:\n"
                    f"  python3 ~/.claude/plugins/agent-swarm/scripts/gh_wrapper.py {cmd[3:]}\n"
                    f"Raw gh output floods context. Wrapper extracts key info only."
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
                f"This operation is destructive. Use explicit approval."
            )

    # Warn about amending
    if "git commit --amend" in command:
        phase = state.get("phase", "")
        if phase != "git":
            return block(
                f"[GIT SAFETY] Amend outside git phase. "
                f"Switch to git phase first, or get explicit approval."
            )

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

    # Load session state
    state = load_json(STATE_FILE)

    # Check autopilot first
    result = check_autopilot(state)
    if result:
        print(json.dumps(result))
        return

    # Run all enforcement checks
    checks = [
        check_phase_restrictions(tool_name, state),
        check_mcp_script_requirement(tool_name, tool_input, state),
        check_smart_tool_usage(tool_name, tool_input, state),
        check_token_efficiency(tool_name, tool_input, state),
        check_scope_discipline(tool_name, tool_input, state),
        check_git_safety(tool_name, tool_input, state),
    ]

    for result in checks:
        if result:
            # Log the block
            msg = result.get("hookSpecificOutput", {}).get("message", "blocked")
            log_event("BLOCKED", f"{tool_name}: {msg[:50]}")
            update_stats(allowed=False, reason=msg, tool_name=tool_name)
            print(json.dumps(result))
            return

    # Default: allow
    log_event("ALLOWED", tool_name)
    update_stats(allowed=True, tool_name=tool_name)
    print(json.dumps(allow()))

if __name__ == "__main__":
    main()
