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

### Tool Access
Use `mcp-call` via Bash. Two forms:

**Shell aliases** (raw args, routed to bash): pytest, ruff, mypy, black, git, gh, python, python3, poetry
```
mcp-call pytest -v tests/
mcp-call git status
```

**MCP tools** (JSON args):
```
mcp-call native__read_file '{"file_path": "/path"}'
mcp-call native__write_file '{"file_path": "/path", "content": "..."}'
mcp-call native__edit_file '{"file_path": "/path", "old_string": "...", "new_string": "..."}'
mcp-call native__grep '{"pattern": "...", "path": "/dir"}'
mcp-call native__glob '{"pattern": "**/*.py", "path": "/dir"}'
mcp-call native__bash '{"command": "..."}'
mcp-call serena__find_symbol '{"name_path_pattern": "X"}'
```

### Long-Running Commands
MCP calls timeout at ~30s. For longer commands:
```bash
nohup <command> > /tmp/output.txt 2>&1 &
# then later:
cat /tmp/output.txt
```

### Process Constraints
- No direct workflow state access
- No access to main conversation context
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
Phases: implement → test → review

1. **implement**: Write code to make tests pass
2. **test**: Run all tests via `mcp-call pytest -v <test_file>`
3. **review**: If all tests pass, commit:
   ```
   mcp-call git add <files you created or modified>
   mcp-call git commit -m "<group>: <descriptive message>"
   ```
   Do NOT push — orchestrator handles that.
   If tests fail, go back to implement.
""",
    "orchestrate": """## Orchestrate
Phases: [intake] → [design] → orchestrate
- Build task queue from input, dispatch subagents, manage completion
- Orchestrator decides, subagents execute
- No direct implementation
- Task queue in workflow state, orchestrator owns exclusively
""",
}


# =============================================================================
# PHASE PROTOCOLS - phase-specific rules within workflows
# =============================================================================

PHASE_PROTOCOLS = {
    "intake": """## Phase: Intake
- Gather missing info, clarify requirements
- → design when sufficient
""",
    "design": """## Phase: Design
- Create plan doc from intake findings
- → orchestrate when complete
""",
    "orchestrate": """## Phase: Orchestrate
- Read input → build task queue → dispatch loop
- Dequeue pending tasks, launch subagents (iterate)
- On return: mark complete, check unblocked, group complete → PR
- Monitor: dead agents → reset task; PR comments → new tasks
- Stop: queue empty ∧ no agents ∧ no PR comments ∧ clean tree ∧ all groups have PR
""",
    "test_writing": """## Phase: Test Writing
- Write tests FIRST (TDD)
- Cover edge cases
- No implementation yet
- → implement
""",
    "implement": """## Phase: Implement
- Make tests pass
- Follow existing patterns
- Minimal changes only
- → test
""",
    "test": """## Phase: Test
- Run pytest, ruff, coverage
- Call adversary_gate tool (autonomous: analyzes, writes adversarial tests, runs them)
- No manual editing — adversary writes directly
- pass + confident → review | adversary fail → implement | pass + weak → test_writing
""",
    "review": """## Phase: Review
- Check quality, conventions, correctness
- clean → commit + push → done
- issues → implement
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


def assemble_subagent_briefing(
    role: str,
    max_tokens: int = 1500,
    workflow_override: Optional[str] = None,
    phase_override: Optional[str] = None,
) -> str:
    """Assemble complete briefing for subagent.

    Queries controller for workflow/phase state and builds
    appropriate briefing including role-specific rules.

    Args:
        role: Subagent role (implementer, explorer, etc.)
        max_tokens: Maximum token budget for briefing.
        workflow_override: Override global workflow (e.g. "iterate" for orchestrate-dispatched tasks).
        phase_override: Override global phase.

    Returns:
        Complete briefing for subagent within token budget.
    """
    parts = [UNIVERSAL_PROTOCOL, SUBAGENT_PROTOCOL, get_role_protocol(role)]

    workflow, phase = get_workflow_state()
    workflow = workflow_override or workflow
    phase = phase_override or phase
    
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
