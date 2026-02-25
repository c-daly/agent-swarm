# Plan: Implement `native__task` — Router-Owned Subagent Execution

## Context

This is the keystone of the hooks-to-router refactor (`feature/hooks-refactor`). Most hooks have already been migrated to the controller, but `subagent-enforcement.py` and `subagent-complete.py` require owning the subagent lifecycle — which the hook system can't provide. `native__task` is the solution that unblocks completing the refactor.

## Goal

Replace Claude Code's built-in Task tool with `native__task` on the router. The router spawns subagents via `claude_code_sdk` (v0.1.27), owning the full lifecycle: enforcement, context injection, execution, and completion processing. Three hooks are deleted.

The SDK uses Claude Code CLI for auth (no API key needed — subscription works). It internally spawns a `claude` subprocess via `SubprocessCLITransport`.

## Architecture

```
Before:  Claude Code -> Task -> hooks (enforce, inject, complete)
After:   Claude Code -> mcp__router__native__task -> controller -> claude_code_sdk.query() -> result
```

### Component Boundaries

| Component | Owns | Does Not Own |
|-----------|------|--------------|
| **Router** | Protocol translation only — MCP JSON-RPC ↔ internal format, SDK messages ↔ internal format. Mechanical parsing. | Business logic, summarization, caching |
| **Controller** | Dispatches to handlers, enforcement, state management. Thin glue for `native__task`. | Wire formats |
| **PromptBuilder** | All prompt concerns — spawn context, phase transitions, workflow transitions. Reads workflow state directly. | Result processing, tool permissions |
| **ResultProcessor** | Post-execution business logic — learnings extraction, state transitions, failure detection. Decoupled class, exact ownership (independent vs. part of state management) TBD during implementation. | Wire format parsing, prompt assembly |
| **Permission system** | Decides what tools an agent can call, per identity/phase. Queried at spawn and at each MCP call. | Prompt construction |

### Subagent Tool Access

Subagents behave the same as the main agent in terms of tools and access. All tool calls route through MCP to the router — **no native tools for subagents**. The router's permission system gates each call based on agent identity and current phase.

Four mechanisms enforce discipline:
1. **`allowed_tools` at spawn** — outer boundary (SDK parameter). TBD whether this can reference router MCP tools directly or still requires `Bash(mcp*)` bridge. If SDK can't connect subagent to router MCP directly, `native-tool-blocking.py` hook may need to stay.
2. **Injected prompts** — PromptBuilder injects phase-appropriate instructions telling the subagent what to do.
3. **`router__get_allowed_tools`** — subagent can query what's currently permitted for its phase.
4. **Router enforcement** — every MCP call checked against current phase permissions, blocked if not allowed.

### Iterate Workflow: Single Subagent, Multiple Phases

In iterate, one subagent runs through all TDD phases (test_writing → implement → test → review) sequentially. It is not one subagent per phase.

- PromptBuilder assembles full context at spawn (base TDD workflow + all phase instructions + current phase emphasis)
- Subagent self-advances phases via workflow tools (`workflow__workflow_advance_phase`)
- `get_allowed_tools` reflects the new phase after advancement
- Router enforcement blocks tools not permitted for the current phase
- Tool permissions update when phase changes — no mid-execution prompt injection needed

### Threading Model

The router uses thread-per-connection (up to 64). The `native__task` handler blocks its thread while the SDK runs `query()` via `asyncio.run()`. Other connections remain responsive. This is equivalent to the current model where Claude Code blocks waiting on Task tool results.

## Files

| File | Action |
|------|--------|
| `lib/prompt_builder.py` | NEW — PromptBuilder class, reads workflow state, loads and assembles templates |
| `lib/result_processor.py` | NEW — ResultProcessor class (name/structure TBD), post-execution business logic |
| `config/prompts/*.md` | NEW — prompt template files for iterate + implementer workflows |
| `lib/controller.py` | Add `_native_task()` handler |
| `lib/router.py` | Add `native__task` schema, dispatch, SDK message parsing |
| `hooks/native-tool-blocking.py` | Add `Task` to blocked list |
| `hooks/hooks.json` | Remove SubagentStart, SubagentStop, PreToolUse:Task entries |
| `hooks/task-enforcement.py` | DELETE |
| `hooks/subagent-enforcement.py` | DELETE |
| `hooks/subagent-complete.py` | DELETE |

---

## Step 1: PromptBuilder (`lib/prompt_builder.py`)

PromptBuilder owns everything prompt-related. It reads workflow state internally — callers don't pass state in, they just call `build()` and get a complete context string.

```python
class PromptBuilder:
    def __init__(self, templates_dir: Path = None, workflow_client=None):
        self.templates_dir = templates_dir or Path(__file__).parent.parent / "config" / "prompts"
        self._cache: dict[str, str] = {}
        self._workflow_client = workflow_client

    def render(self, name: str, **kwargs) -> str:
        """Load template file and fill {{placeholders}}."""

    def build(self, prompt: str, subagent_type: str, agent_id: str) -> str:
        """Assemble complete enriched prompt.

        Reads workflow state internally to determine:
        - Active workflow (iterate, orchestrate, implementer)
        - Current phase
        - Mode, group, repo path
        - Permissions/restrictions

        Returns a single context string ready for the SDK.
        """

    def build_phase_context(self, phase: str, agent_id: str) -> str:
        """Build context for a phase transition.

        Called when PromptBuilder needs to generate context
        outside of spawn (e.g., phase or workflow transitions).
        """
```

## Step 2: Prompt Templates (`config/prompts/*.md`)

Extract from `subagent-enforcement.py`'s f-strings into markdown with `{{placeholder}}` syntax. Initial set covers iterate + implementer only:

- `tdd_base.md` — base TDD context (tool usage, phase sequence, completion format)
- `test_writing.md` — test_writing phase instructions
- `implement.md` — implement phase instructions
- `test.md` — test/verification phase instructions
- `review.md` — review/git phase instructions
- `restrictions.md` — phase restriction block (blocked tools list)
- `base_briefing.md` — universal subagent briefing (migrated from `hooks/subagent-briefing.md`)

All subagent types get `base_briefing.md`. Iterate subagents additionally get TDD templates.
Adding new workflow/type support means adding template files.

## Step 3: Tool Schema + SDK Parsing (`lib/router.py`)

Add `native__task` to `_get_native_tool_schemas()`:
- required: `prompt`, `subagent_type`
- optional: `model`, `description`

Add `"task": self._native_task` to `_handle_native()` dispatch dict.

SDK message parsing in the router (mechanical only):
- Extract text blocks from message stream
- Extract cost/token metadata from ResultMessage
- Return normalized internal format dict to controller

## Step 4: Handler (`lib/controller.py`)

The handler is thin glue connecting the components:

### 4a: Enforcement
- Check: can this agent spawn a subagent? (implementer-only during iterate/orchestrate)
- Read from workflow state (in-memory)

### 4b: Prompt Assembly + Agent Registration
- Generate agent_id
- Register in agent state, track in `active_agents`
- Call `PromptBuilder.build(prompt, subagent_type, agent_id)` → complete context string

### 4c: Execution via SDK

```python
import asyncio
from claude_code_sdk import query, ClaudeCodeOptions

async def _run_subagent(self, prompt, context, model, subagent_type):
    options = ClaudeCodeOptions(
        system_prompt=context,
        # TBD: allowed_tools — either router MCP tool names directly,
        # or Bash(mcp*) if SDK can't connect subagent to router MCP
        permission_mode="bypassPermissions",
        cwd=str(self._project_root),
    )
    if model:
        options.model = model

    messages = []
    async for message in query(prompt=prompt, options=options):
        messages.append(message)
    return messages
```

Called from synchronous handler via `asyncio.run()` (blocks handler thread, other connections unaffected):

```python
def _native_task(self, args: dict) -> dict:
    # 4a: enforcement
    # 4b: prompt assembly + registration
    # 4c: execution
    messages = asyncio.run(self._run_subagent(...))
    # Router parses SDK messages into internal format
    parsed = self._parse_sdk_result(messages)
    # 4d: result processing
    result = self._result_processor.process(parsed, agent_id)
    return result
```

### 4d: Result Processing (via ResultProcessor)

- Extract learnings (`LEARNING:` regex) from output text → write to memory
- Move agent from `active_agents` → `completed_tasks` in workflow state
- Detect failure (agent reported blocked/failed) → mark agent state
- Return structured output dict for parent agent

## Step 5: Block Task (`hooks/native-tool-blocking.py`)

```python
if tool_name == "Task":
    block("[BLOCKED] Task blocked — use mcp__router__native__task instead.")
    return
```

## Step 6: Update `hooks/hooks.json`

Remove:
- `PreToolUse:Task` → `task-enforcement.py`
- `SubagentStart:*` → `subagent-enforcement.py`
- `SubagentStop:*` → `subagent-complete.py`

## Step 7: Delete Hook Files

- `hooks/task-enforcement.py`
- `hooks/subagent-enforcement.py`
- `hooks/subagent-complete.py`

## Step 8: Clean Up

- Remove `router__check_task_enforcement` from controller + router schemas
- Init PromptBuilder + ResultProcessor in `Controller.__init__()`
- Migrate `hooks/subagent-briefing.md` → `config/prompts/base_briefing.md`
- Update/remove tests that imported from deleted hooks

---

## Open Questions

1. **SDK tool access:** Can the SDK connect the subagent to the router as an MCP server directly (subagent sees `mcp__router__*` tools natively)? Or must subagents use `Bash(mcp*)` bridge? This determines whether `native-tool-blocking.py` hook can be removed.

2. **ResultProcessor ownership:** Independent class or part of a state management service? To be determined during implementation.

3. **`asyncio.run()` per call:** Creates a new event loop each time. Fine for subagent execution but worth noting if async state sharing is ever needed across calls.

## Verification

1. Start daemon → confirm `native__task` in `tools/list`
2. Verify built-in `Task` blocked by hook
3. Call `mcp__router__native__task` with simple prompt → verify SDK executes and returns result
4. Test with iterate workflow active → verify enriched prompt includes TDD context for all phases
5. Test enforcement: non-implementer during orchestrate → denied
6. Test phase advancement within iterate subagent → permissions update correctly
7. Test learning capture from subagent output
8. Test failure detection and state marking
9. `pytest tests/`
