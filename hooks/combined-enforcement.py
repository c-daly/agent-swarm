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
from datetime import datetime
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
MAX_DIRECT_SEARCHES = 2  # After this, must use scripts
MAX_FILE_READS = 2  # After this, must use subagent

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
    if tool_name == "Bash" and tool_input:
        command = tool_input.get("command", "").strip()
        if '.state' in command or 'session.json' in command:
            return block(
                "[STATE PROTECTION] Cannot access state files\n"
                "State management is handled by the enforcement system.\n"
                "Use AskUserQuestion if you need checkpoint approval."
            )
    
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
            import sys; print(f'DEBUG: AGENT_PHASE exemption triggered!', file=sys.stderr)
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

    # Detect phase changes and reset counters
    current_phase = state.get("phase", "")
    last_phase = state.get("last_phase", "")
    
    if current_phase != last_phase and last_phase:
        # Phase changed, reset counters
        state["search_count"] = 0
        state["read_count"] = 0
        state["files_read"] = []
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

    # Track file reads and detect duplicates
    if tool_name == "Read":
        file_path = tool_input.get("file_path", "")

        # Track which files have been read
        files_read = state.get("files_read", [])

        # Check for duplicate
        if file_path in files_read:
            return block(
                f"[DUPLICATE READ] File already read in this session:\n"
                f"  {file_path}\n\n"
                f"Reading the same file multiple times wastes tokens.\n"
                f"If you need to re-check: review conversation history.\n"
                f"If content changed: explain why re-reading is necessary."
            )

        # Track this file
        files_read.append(file_path)
        state["files_read"] = files_read

        count = state.get("read_count", 0) + 1
        state["read_count"] = count
        save_state(state)

        if count > MAX_FILE_READS:
            return block(
                f"[TOKEN EFFICIENCY] {count} direct file reads. "
                f"Spawn an Explorer subagent to aggregate findings, "
                f"or use a script to read and summarize."
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
                    f"[BASH ABUSE] Don't use 'cat' for reading - use Read tool instead\n"
                    f"❌ Bash: {cmd[:60]}\n"
                    f"✅ Read: {{'file_path': '<path>'}}\n"
                    f"Bash cat wastes tokens and bypasses tracking."
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
                f"[BASH ABUSE] Don't use grep/rg via Bash - use Grep tool instead\n"
                f"❌ Bash: {cmd[:60]}\n"
                f"✅ Grep: {{'pattern': '<regex>', 'path': '.', 'output_mode': 'files_with_matches'}}\n"
                f"The Grep tool is powered by ripgrep (rg) and has proper output formatting."
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
                f"[BASH ABUSE] Don't use sed/awk for file editing - use Edit tool\n"
                f"❌ Bash: {cmd[:60]}\n"
                f"✅ Edit: {{'file_path': '<path>', 'old_string': '...', 'new_string': '...'}}\n"
                f"Edit tool is atomic and tracked."
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
    """
    if tool_name != "Bash":
        return None
    
    command = tool_input.get("command", "")
    
    # Detect git commit or push
    is_commit = re.search(r'\bgit\s+commit\b', command)
    is_push = re.search(r'\bgit\s+push\b', command)
    
    if not (is_commit or is_push):
        return None
    
    # LAYER 1: User Approval Detection
    # Scan recent user messages for approval keywords
    approval_keywords = [
        "approve", "approved", "go ahead", "proceed", "yes",
        "commit it", "push it", "create commit", "make the commit",
        "create the commit", "do it", "please commit", "please push"
    ]
    
    user_approved = state.get("user_approved_commit", False)
    
    if not user_approved:
        # Scan last 20 messages for user approval
        recent_messages = messages[-20:] if len(messages) > 20 else messages
        for msg in reversed(recent_messages):
            if msg.get("role") == "user":
                msg_content = msg.get("content", "").lower()
                if any(keyword in msg_content for keyword in approval_keywords):
                    state["user_approved_commit"] = True
                    save_state(state)
                    user_approved = True
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
    """Suggest episodic memory search for research/exploration tasks"""

    # Only suggest once per session
    if state.get("memory_search_suggested"):
        return None

    # Suggest for Task tool with exploration/research keywords
    if tool_name == "Task":
        subagent_type = tool_input.get("subagent_type", "")
        prompt = tool_input.get("prompt", "").lower()

        # Check if this is a research/exploration task
        research_keywords = ["explore", "investigate", "understand", "how does", "find out", "research"]
        is_research = (subagent_type in ["Explore", "explorer", "research", "researcher"] or
                      any(keyword in prompt for keyword in research_keywords))

        if is_research:
            # Mark as suggested
            state["memory_search_suggested"] = True
            save_json(STATE_FILE, state)

            # Return suggestion (not blocking, just informative)
            return {
                "hookSpecificOutput": {
                    "permissionDecision": "allow",
                    "message": "[MEMORY] Consider searching episodic memory first:\n"
                    "  Skill: episodic-memory:search-conversations\n"
                    "  OR use: mcp__plugin_episodic-memory_episodic-memory__search(query='<keywords>', limit=5)\n"
                    "  This can recover relevant context from past sessions."
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
            if file_path not in state["files_edited_this_session"]:
                state["files_edited_this_session"].append(file_path)
                save_state(state)

            # Block 2nd+ file with SIMPLE classification
            if len(state["files_edited_this_session"]) > 1:
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
        if not state.get("classification_given"):
            return block(
                "[PROCESS VIOLATION] Classification required before editing code.\n"
                "Output classification as first line: [TRIVIAL|SIMPLE|COMPLEX|RESEARCH|CONVERSATION]\n\n"
                "Classification criteria:\n"
                "- TRIVIAL: One-liner fix\n"
                "- SIMPLE: Single file, <50 lines, clear requirements\n"
                "- COMPLEX: Multiple files OR architectural decisions OR unclear scope\n"
                "- RESEARCH: Exploring/reading, no code changes\n"
                "- CONVERSATION: Discussion only"
            )
        
        # Rule 2: COMPLEX tasks must invoke workflow
        if state.get("classification_type") == "COMPLEX" and not state.get("workflow_invoked"):
            return block(
                "[PROCESS VIOLATION] [COMPLEX] tasks require workflow:orchestrate.\n"
                "From CLAUDE.md: 'Invoke workflow:orchestrate BEFORE any work'\n\n"
                "Do NOT skip because you 'already know what to do'\n"
                "Do NOT rationalize your way out of this\n\n"
                "Use: Skill(skill='agent-swarm:orchestrate', args='<task description>')"
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
    messages = input_data.get("messages", [])

    # Load session state
    state = load_json(STATE_FILE)

    # Check autopilot first
    result = check_autopilot(state)
    if result:
        print(json.dumps(result))
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
    log_event("ALLOWED", tool_name)
    update_stats(allowed=True, tool_name=tool_name)
    print(json.dumps(allow()))

if __name__ == "__main__":
    main()
