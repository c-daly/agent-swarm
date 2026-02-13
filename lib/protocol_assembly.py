"""Protocol assembly for agent briefings.

Assembles protocol briefings from universal, context-specific, and role-specific
components. Queries controller for workflow/phase state to build complete briefings.

Used by both session-start (main agent) and native__task (subagents).
"""

from pathlib import Path
from typing import Optional, Tuple
import sys
import os

# Add context module to path
sys.path.insert(0, str(Path(__file__).parent.parent))


# =============================================================================
# UNIVERSAL PROTOCOL - applies to ALL agents (main and subagents)
# =============================================================================

UNIVERSAL_PROTOCOL = """## Universal Protocol

### Efficiency
- 3+ reads/searches → batch script
- Return summaries, not raw content
- No duplicate reads
- Track what you've already read

### File Reading
- Full file reads are rarely the right tool — prefer targeted approaches
- `find_symbol` with `include_body=true`: get exactly the function/class you need
- `search_for_pattern` with `context_lines_after`: find code + surrounding context
- `get_symbols_overview`: understand file structure without reading content
- `read_file` with `start_line`/`end_line`: read a known range, not the whole file
- Only read full files for small config/data files or when you truly need everything

### Parallel Execution
- Independent tool calls in ONE message
- Don't: call → wait → call again
- Do: single message with multiple calls

### Output
- Bullets, not prose
- File refs: `path:line`
- Max 100 chars for summaries

### Failure
- Fail fast, don't guess or hallucinate
- 3 failed attempts → escalate to user
- Check permissions before operations
"""


# =============================================================================
# AGENT PROTOCOL - main agent specifics (MCP router tools)
# =============================================================================

AGENT_PROTOCOL = """## Main Agent Protocol

### Tool Access
Tools via MCP router: `mcp__router__<server>__<tool>`

| Operation | Tool |
|-----------|------|
| Read file | `serena__read_file`, `native__read_file` |
| Search | `native__grep`, `serena__search_for_pattern` |
| Find files | `native__glob`, `serena__find_file` |
| Find symbols | `serena__find_symbol`, `serena__get_symbols_overview` |
| Edit code | `serena__replace_content`, `serena__replace_symbol_body` |
| Run command | `native__bash` |
| Write file | `serena__create_text_file` |

### Tool Priority
1. Serena symbolic tools (code understanding)
2. Context7 (library docs)
3. Batch scripts (3+ operations)
4. Native tools (single operations)
"""


# =============================================================================
# SUBAGENT PROTOCOL - subagent specifics (mcp-call in independent process)
# =============================================================================

SUBAGENT_PROTOCOL = """## Subagent Protocol

### Tool Access — mcp-call
All tools via `mcp-call <tool> '<json_args>'` in Bash.

| Operation | Command |
|-----------|---------|
| Read file | `mcp-call serena__read_file '{"relative_path": "src/main.py"}'` |
| Search | `mcp-call serena__search_for_pattern '{"substring_pattern": "TODO"}'` |
| Find files | `mcp-call serena__find_file '{"file_mask": "*.py", "relative_path": "."}'` |
| Find symbols | `mcp-call serena__find_symbol '{"name_path_pattern": "MyClass"}'` |
| Edit code | `mcp-call serena__replace_content '{"relative_path": "f.py", "needle": "old", "repl": "new", "mode": "literal"}'` |
| Write file | `mcp-call serena__create_text_file '{"relative_path": "f.py", "content": "..."}'` |

### Shell Commands — aliases
Run directly: `mcp-call pytest tests/`, `mcp-call git status`, `mcp-call ruff check .`
Available: pytest, ruff, mypy, black, git, gh, python3

### Constraints
- Router enforces all permissions — blocked tools will return errors
- Must complete task independently
"""


# =============================================================================
# ROLE PROTOCOLS - role-specific additions
# =============================================================================

ROLE_PROTOCOLS = {
    "implementer": """## Implementer Role
- Write code to make tests pass
- Follow existing conventions
- No over-engineering
- Commit frequently
""",
    "explorer": """## Explorer Role
- Search and understand codebase
- Report findings clearly
- No editing allowed
""",
    "reviewer": """## Reviewer Role
- Check conventions and patterns
- Note pitfalls
- Suggest improvements
""",
    "architect": """## Architect Role
- Design structure and interfaces
- Consider dependencies
- Document decisions
""",
    "debugger": """## Debugger Role
- Trace execution paths
- Identify root causes
- Suggest minimal fixes
""",
    "git-agent": """## Git Agent Role
- Follow commit conventions
- No force pushes
- Clear commit messages
""",
    "researcher": """## Researcher Role
- Gather information
- Summarize findings
- No code changes
""",
}

DEFAULT_ROLE = """## Agent Role
- Follow instructions precisely
- Use appropriate tools
- Report progress clearly
"""


# =============================================================================
# WORKFLOW PROTOCOLS - workflow-specific rules
# =============================================================================

WORKFLOW_PROTOCOLS = {
    "iterate": """## Iterate Workflow
- TDD discipline: tests FIRST, then implementation
- Phases: test_writing → implement → test → review
- Kick-back on failures
""",
    "orchestrate": """## Orchestrate Workflow
- Spawn subagents for all work
- No direct implementation
- Coordinate and monitor
""",
}


# =============================================================================
# PHASE PROTOCOLS - phase-specific rules within workflows
# =============================================================================

PHASE_PROTOCOLS = {
    "orchestrate": """## Phase: Orchestrate
- Spawn subagents for all work
- No direct implementation
- Use TaskOutput(block=false) for monitoring
""",
    "test_writing": """## Phase: Test Writing
- Write tests FIRST (TDD)
- Cover edge cases
- No implementation yet
""",
    "implement": """## Phase: Implement
- Make tests pass
- Follow existing patterns
- Minimal changes only
""",
    "test": """## Phase: Test
- Run pytest, ruff, coverage
- No editing allowed
- Report results only
""",
    "review": """## Phase: Review
- Check for issues
- Commit if clean
- Report problems
""",
}


# =============================================================================
# STATE QUERYING
# =============================================================================

def _get_daemon_client():
    """Get daemon client for state queries."""
    try:
        from lib.daemon_client import DaemonClient
        return DaemonClient()
    except ImportError:
        return None


def get_workflow_state() -> Tuple[Optional[str], Optional[str]]:
    """Query controller for current workflow and phase.
    
    Returns:
        Tuple of (workflow_name, phase_name), either can be None.
    """
    try:
        client = _get_daemon_client()
        if not client:
            return None, None
        
        with client:
            if not client.workflow_is_active():
                return None, None
            
            state = client.workflow_get_state()
            workflow = state.get("workflow")
            phase = state.get("phase")
            return workflow, phase
    except Exception:
        return None, None


# =============================================================================
# ASSEMBLY FUNCTIONS
# =============================================================================

def get_role_protocol(role: str) -> str:
    """Get role-specific protocol rules."""
    return ROLE_PROTOCOLS.get(role.lower(), DEFAULT_ROLE)


def get_workflow_protocol(workflow: str) -> str:
    """Get workflow-specific protocol rules."""
    return WORKFLOW_PROTOCOLS.get(workflow.lower(), "")


def get_phase_protocol(phase: str) -> str:
    """Get phase-specific protocol rules."""
    return PHASE_PROTOCOLS.get(phase.lower(), "")


def assemble_agent_briefing() -> str:
    """Assemble complete briefing for main agent.
    
    Queries controller for workflow/phase state and builds
    appropriate briefing.
    
    Returns:
        Complete briefing for main agent.
    """
    parts = [UNIVERSAL_PROTOCOL, AGENT_PROTOCOL]
    
    workflow, phase = get_workflow_state()
    
    if workflow:
        parts.append(get_workflow_protocol(workflow))
    
    if phase:
        parts.append(get_phase_protocol(phase))
    
    return "\n".join(parts)


def assemble_subagent_briefing(role: str, max_tokens: int = 1500) -> str:
    """Assemble complete briefing for subagent.
    
    Queries controller for workflow/phase state and builds
    appropriate briefing including role-specific rules.
    
    Args:
        role: Subagent role (implementer, explorer, etc.)
        max_tokens: Maximum token budget for briefing.
    
    Returns:
        Complete briefing for subagent within token budget.
    """
    parts = [UNIVERSAL_PROTOCOL, SUBAGENT_PROTOCOL, get_role_protocol(role)]
    
    workflow, phase = get_workflow_state()
    
    if workflow:
        parts.append(get_workflow_protocol(workflow))
    
    if phase:
        parts.append(get_phase_protocol(phase))
    
    briefing = "\n".join(parts)
    
    # Truncate if over budget
    if estimate_tokens(briefing) > max_tokens:
        briefing = briefing[:int(max_tokens * 3.5)]  # 3.5 for safety margin
    
    return briefing


def estimate_tokens(text: str) -> int:
    """Estimate token count (rough: 4 chars per token)."""
    return len(text) // 4


# =============================================================================
# BACKWARDS COMPATIBILITY
# =============================================================================

COMPRESSED_PROTOCOLS = ROLE_PROTOCOLS
DEFAULT_PROTOCOL = DEFAULT_ROLE


def get_compressed_protocol(agent_type: str) -> str:
    """Deprecated: use get_role_protocol instead."""
    return get_role_protocol(agent_type)


def generate_agent_briefing(
    agent_type: str,
    phase: Optional[str] = None,
    max_tokens: int = 1000,
    include_context: bool = True,
) -> str:
    """Deprecated: use assemble_subagent_briefing instead."""
    return assemble_subagent_briefing(role=agent_type, max_tokens=max_tokens)
