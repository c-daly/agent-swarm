"""Protocol assembly for agent briefings.

Assembles protocol briefings from universal, context-specific, and role-specific
components. Queries controller for workflow/phase state to build complete briefings.

Used by both session-start (main agent) and prepare_dispatch (subagents).
"""

from pathlib import Path
from typing import Optional, Tuple
import sys
import os

sys.path.insert(0, str(Path(__file__).parent.parent))


# =============================================================================
# UNIVERSAL PROTOCOL - applies to ALL agents (main and subagents)
# =============================================================================

UNIVERSAL_PROTOCOL = """## Universal Protocol

### Efficiency
- 3+ reads/searches -> batch script
- Return summaries, not raw content
- No duplicate reads
- Track what you have already read

### Parallel Execution
- Independent tool calls in ONE message
- Do not: call -> wait -> call again
- Do: single message with multiple calls

### Output
- Bullets, not prose
- File refs: path:line
- Max 100 chars for summaries

### Failure
- Fail fast, do not guess or hallucinate
- 3 failed attempts -> escalate to user
- Check permissions before operations
"""


# =============================================================================
# AGENT PROTOCOL - main agent specifics (MCP router tools)
# =============================================================================

AGENT_PROTOCOL = """## Main Agent Protocol

### Tool Access
Tools via MCP router: mcp__plugin_agent-swarm_router__<server>__<tool>

| Operation | Tool |
|-----------|------|
| Read file | mcp__plugin_agent-swarm_router__serena__read_file, mcp__plugin_agent-swarm_router__native__read_file |
| Search | mcp__plugin_agent-swarm_router__native__grep, mcp__plugin_agent-swarm_router__serena__search_for_pattern |
| Find files | mcp__plugin_agent-swarm_router__native__glob, mcp__plugin_agent-swarm_router__serena__find_file |
| Find symbols | mcp__plugin_agent-swarm_router__serena__find_symbol, mcp__plugin_agent-swarm_router__serena__get_symbols_overview |
| Edit code | mcp__plugin_agent-swarm_router__serena__replace_content, mcp__plugin_agent-swarm_router__serena__replace_symbol_body |
| Run command | mcp__plugin_agent-swarm_router__native__bash |
| Write file | mcp__plugin_agent-swarm_router__serena__create_text_file |
| Web fetch | mcp__plugin_agent-swarm_router__native__web_fetch |
| Web search | mcp__plugin_agent-swarm_router__native__web_search |

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

### Identity
Your agent ID is provided at the top of your briefing. Pass it with EVERY
mcp-call invocation using `--caller-id=<your_agent_id>`. This lets the
router resolve your permissions. Without it, tool calls will be denied.

### Tool Access
All tools via `mcp-call` in Bash. Always include `--caller-id`. Two forms:

**Shell aliases** (raw args -> routed to native__bash):
```
mcp-call --caller-id=YOUR_AGENT_ID pytest -v tests/
mcp-call --caller-id=YOUR_AGENT_ID git status
mcp-call --caller-id=YOUR_AGENT_ID ruff check src/
```

**MCP tools** (JSON args):
```
mcp-call native__read_file '{"file_path": "/path"}'
mcp-call native__write_file '{"file_path": "/path", "content": "..."}'
mcp-call native__grep '{"pattern": "...", "path": "/dir"}'
mcp-call native__glob '{"pattern": "**/*.py", "path": "/dir"}'
mcp-call native__bash '{"command": "..."}'
mcp-call native__web_fetch '{"url": "https://..."}'
mcp-call native__web_search '{"query": "..."}'
mcp-call serena__find_symbol '{"name_path_pattern": "ClassName"}'
mcp-call serena__read_file '{"relative_path": "src/foo.py"}'
```

### Editing Files
Prefer `serena__replace_content` over `native__edit_file` -- regex mode avoids
JSON escaping issues with multi-line code:
```
mcp-call serena__replace_content '{"relative_path": "src/foo.py", "needle": "def old_fn.*?return None", "repl": "def new_fn():\\n    return 42", "mode": "regex"}'
```
For exact string replacement, use `"mode": "literal"`.

### Expanding Summarized Output
Large outputs are summarized with a `content_id`. To get the full content:
```
mcp-call router__get_full '{"content_id": "c1234abcdef56"}'
```

### How To Work
1. Understand the task -- read the prompt carefully
2. Find relevant code: `mcp-call native__grep` / `mcp-call serena__find_symbol`
3. Read before editing: `mcp-call native__read_file`
4. Make targeted changes: `mcp-call serena__replace_content`
5. Verify: `mcp-call pytest -v <test_file>`
6. If tests fail, read the output and fix -- don't guess

### Long-Running Commands
MCP calls timeout at ~30s. For longer commands:
```
mcp-call native__bash '{"command": "nohup pytest --tb=long > /tmp/out.txt 2>&1 &"}'
# then later:
mcp-call native__read_file '{"file_path": "/tmp/out.txt"}'
```

### When Things Go Wrong
- JSON escaping failing? Use shell aliases: `mcp-call git status` not `mcp-call native__bash '{"command": "git status"}'`
- Permission denied? You may not have access to that tool in your current role/phase.
- Run `mcp-call` with no args to see available backends and examples.

### Constraints
- No direct workflow state modification (orchestrator manages phases)
- No access to main conversation context
- Must complete task independently
"""


# =============================================================================
# ROLE PROTOCOLS - role constraints and permissions
# =============================================================================

ROLE_PROTOCOLS = {
    "implementer": """## Implementer Role
- Can read, write, edit files
- Can run tests (pytest, ruff, mypy)
- Can commit (git add, git commit) -- do NOT push
- Minimal changes only -- no speculative features or refactoring beyond scope
- Follow existing patterns in the codebase
""",
    "explorer": """## Explorer Role
- Read-only -- no file writes or edits
- Search, read, and report findings
- Return structured summaries, not raw dumps
""",
    "reviewer": """## Reviewer Role
- Read-only -- no file writes or edits
- Check conventions, patterns, correctness
- Flag issues with file:line references
- Suggest improvements, don't implement them
""",
    "architect": """## Architect Role
- Read-only -- no file writes or edits
- Design structure and interfaces
- Consider dependencies and trade-offs
- Document decisions clearly
""",
    "debugger": """## Debugger Role
- Can read files and run tests
- Trace execution paths, identify root causes
- Suggest minimal fixes with file:line references
- Can write fixes if explicitly tasked
""",
    "git-agent": """## Git Agent Role
- Can run git and gh commands
- Follow commit conventions
- No force pushes
- No pushing unless explicitly instructed
""",
    "researcher": """## Researcher Role
- Read-only -- no file writes or edits
- Can use web_fetch and web_search
- Gather information, summarize findings
- Return structured results
""",
    "pm": """## PM Role
- Stakeholder proxy -- owns the feature from intake to acceptance
- Write user stories with clear acceptance criteria at intake
- Approve or reject design specs from Architect
- Schedule subtasks based on Architect's dependency graph
- Monitor kickback history -- intervene if progress stalls
- Validate implementation against original user stories at acceptance
- Can create GitHub tickets when ticket config is enabled
- Read-only for code -- no file writes, edits, or bash
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
    "iterate": """## Iterate Workflow (engine-governed TDD)
Phases: test_writing -> implement -> test -> review -> complete.
Your workflow instance is `__WF_ID__`. Pass it as `workflow_id` in EVERY workflow
call below (always with your `--caller-id`). The router enforces each phase's tool
permissions; you move the engine forward yourself. You START in **test_writing**.

### test_writing  (write the spec as tests)
Write the test file(s) first -- they define "done". File writes are allowed here.
When the tests are written, advance:
```
mcp-call workflow__workflow_advance_phase '{"workflow_id": "__WF_ID__", "target_phase": "implement"}'
```

### implement  (make them pass)
Write the implementation. When you believe the tests will pass, advance:
```
mcp-call workflow__workflow_advance_phase '{"workflow_id": "__WF_ID__", "target_phase": "test"}'
```

### test  (run, commit, hand off)
Run them: `mcp-call pytest -v <test_file>`
- Any failure -> back to implement (file writes are blocked in `test`):
  ```
  mcp-call workflow__workflow_advance_phase '{"workflow_id": "__WF_ID__", "target_phase": "implement"}'
  ```
- All green -> commit (do NOT push), pass the checkpoint, advance to review, then STOP:
  ```
  mcp-call git add <files>
  mcp-call git commit -m "<group>: <descriptive message>"
  mcp-call workflow__workflow_pass_checkpoint '{"workflow_id": "__WF_ID__", "phase": "test"}'
  mcp-call workflow__workflow_advance_phase '{"workflow_id": "__WF_ID__", "target_phase": "review"}'
  ```

### review
Review, push, and PR are handled by the orchestrator and a separate reviewer
(you have no write/bash access in `review`). Once you have advanced to review,
your task is done -- report your branch, the files you wrote, and the passing
test count, then stop.
""",
    "orchestrate": """## Orchestrate Workflow
Phases: intake -> design -> orchestrate

- Orchestrator decides, subagents execute
- No direct implementation -- delegate everything
- Task queue in workflow state, orchestrator owns exclusively
- Subagents run iterate workflow independently
""",
    "develop": """## Develop Workflow
PR-based SE team: intake -> research -> design -> branch -> test_writing -> implement -> test -> review -> merge -> acceptance -> complete

### Team Coordination
- PM is team lead via Claude Code Teams (TeamCreate/SendMessage).
- All phase transitions decided by PM.
- Agents communicate via SendMessage. PM assigns work, receives results.
- Kickbacks target implement (code issue) or test_writing (test gap).
- Retry counters tracked per kickback source in workflow state.

### Subtask Parallelism
- Architect produces dependency graph. Independent subtasks run in parallel.
- Each parallel Implementer gets isolated worktree.
- Idle agents stay alive, PM messages to wake when work unblocks.
""",
}


# =============================================================================
# PHASE PROTOCOLS - phase-specific rules within workflows
# =============================================================================

PHASE_PROTOCOLS = {
    "intake": """## Phase: Intake
- Gather missing info, clarify requirements
- Read relevant code to understand scope
- -> design when requirements are clear
""",
    "design": """## Phase: Design
- Create plan from intake findings
- Break work into tasks with clear boundaries
- -> orchestrate when plan is complete
""",
    "orchestrate": """## Phase: Orchestrate
- Dequeue pending tasks, dispatch subagents with iterate workflow
- On subagent return: mark complete, check for unblocked tasks
- Group complete -> create PR
- Monitor: dead agents -> reset task; PR comments -> new tasks
- Done when: queue empty and no active agents and clean tree
""",
    "test_writing": """## Phase: Test Writing
- Write tests FIRST (TDD)
- Cover edge cases
- No implementation yet
- -> implement when tests are written
""",
    "implement": """## Phase: Implement
- Make tests pass
- Follow existing patterns
- Minimal changes only
- When tests pass -> advance to test phase
""",
    "test": """## Phase: Test
- Run: `mcp-call pytest -v <test_file>`
- Run: `mcp-call ruff check <files>`
- All pass -> advance to review
- Failures -> back to implement
""",
    "review": """## Phase: Review
- Review your changes: `mcp-call git diff`
- Check: conventions, correctness, no debug artifacts
- Clean -> commit:
  ```
  mcp-call git add <files>
  mcp-call git commit -m "<group>: <descriptive message>"
  ```
- Do NOT push
- Issues found -> back to implement
""",
    "research": """## Phase: Research
- Investigate codebase, APIs, libraries, prior art
- Produce structured context document for Architect
- -> design when context is sufficient
""",
    "branch": """## Phase: Branch
- Create feature branch from main
- If ticket exists, reference ticket ID in branch name
- -> test_writing when branch is created
""",
    "merge": """## Phase: Merge
- Create PR linking to feature ticket if tickets enabled
- Attempt merge
- If merge conflicts -> kickback to implement with list of conflicting files
- If clean -> advance to acceptance
""",
    "acceptance": """## Phase: Acceptance
- PM validates implementation against original user stories
- Check each acceptance criterion from the stories
- Accept -> complete (workflow done)
- Reject (code issue) -> kickback to implement with feedback
- Reject (insufficient tests) -> kickback to test_writing with feedback
""",
}


# =============================================================================
# STATE QUERYING
# =============================================================================

# Known workflow IDs to check (matches permission_query._KNOWN_WORKFLOWS)
_KNOWN_WORKFLOWS = ["iterate", "debug", "pr_comment", "implementer", "develop"]


def get_workflow_state():
    """Query controller for current workflow and phase."""
    try:
        from daemon_client import DaemonClient
        with DaemonClient() as dc:
            for wf_id in _KNOWN_WORKFLOWS:
                if dc.workflow_is_active(wf_id):
                    state = dc.workflow_get_state(wf_id)
                    if state:
                        return state.get("workflow", wf_id), state.get("phase")
        return None, None
    except Exception:
        return None, None


# =============================================================================
# ASSEMBLY FUNCTIONS
# =============================================================================

def get_role_protocol(role):
    """Get role-specific protocol rules."""
    return ROLE_PROTOCOLS.get(role.lower(), DEFAULT_ROLE)


def get_workflow_protocol(workflow):
    """Get workflow-specific protocol rules."""
    return WORKFLOW_PROTOCOLS.get(workflow.lower(), "")


def get_phase_protocol(phase):
    """Get phase-specific protocol rules."""
    return PHASE_PROTOCOLS.get(phase.lower(), "")


def assemble_agent_briefing():
    """Assemble complete briefing for main agent."""
    parts = [UNIVERSAL_PROTOCOL, AGENT_PROTOCOL]
    workflow, phase = get_workflow_state()
    if workflow:
        parts.append(get_workflow_protocol(workflow))
    if phase:
        parts.append(get_phase_protocol(phase))
    return "\n".join(parts)


def assemble_subagent_briefing(
    role,
    workflow_override=None,
    phase_override=None,
    workflow_instance_id=None,
):
    """Assemble complete briefing for subagent.

    workflow_instance_id, when given, replaces the __WF_ID__ placeholder in the
    workflow protocol text so the transition examples name the subagent's own
    engine instance (e.g. 'iterate:sub-abc123') -- without it the worker cannot
    address the workflow it is bound to.
    """
    parts = [UNIVERSAL_PROTOCOL, SUBAGENT_PROTOCOL, get_role_protocol(role)]

    workflow, phase = get_workflow_state()
    workflow = workflow_override or workflow
    phase = phase_override or phase

    if workflow:
        # A per-instance id (iterate:<agent_id>) resolves to its base workflow's
        # protocol text; the full id is still used for the __WF_ID__ substitution
        # so transition examples name the worker's own instance.
        parts.append(get_workflow_protocol(workflow.split(":", 1)[0]))
    if phase:
        parts.append(get_phase_protocol(phase))

    briefing = "\n".join(parts)
    return briefing.replace("__WF_ID__", workflow_instance_id or workflow or "")


def estimate_tokens(text):
    """Estimate token count (rough: 4 chars per token)."""
    return len(text) // 4


# =============================================================================
# BACKWARDS COMPATIBILITY
# =============================================================================

COMPRESSED_PROTOCOLS = ROLE_PROTOCOLS
DEFAULT_PROTOCOL = DEFAULT_ROLE

def get_compressed_protocol(agent_type):
    """Deprecated: use get_role_protocol instead."""
    return get_role_protocol(agent_type)

def generate_agent_briefing(
    agent_type,
    phase=None,
    max_tokens=1000,
    include_context=True,
):
    """Deprecated: use assemble_subagent_briefing instead."""
    return assemble_subagent_briefing(role=agent_type)
