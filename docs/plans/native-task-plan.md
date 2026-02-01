# Plan: Implement `native__task` — Router-Owned Subagent Execution

## Goal

Replace Claude Code's built-in Task tool with `native__task` on the router. The router spawns subagents via the `claude_agent_sdk` (v0.1.27), owning the full lifecycle: enforcement, context injection, execution, and completion processing. Three hooks are deleted.

## Architecture

```
Before:  Claude Code -> Task -> hooks (enforce, inject, complete)
After:   Claude Code -> mcp__router__native__task -> controller -> claude_agent_sdk.query() -> result
```

`native-tool-blocking.py` denies the built-in `Task` (same hook that blocks raw Bash).

The SDK uses Claude Code CLI for auth (no API key needed — subscription works). It internally spawns a `claude` subprocess via `SubprocessCLITransport`.

## Files

| File | Action |
|------|--------|
| `lib/prompt_builder.py` | NEW — PromptBuilder class, loads markdown templates |
| `config/prompts/*.md` | NEW — prompt template files (~6) |
| `lib/controller.py` | Add `_native_task()` handler |
| `lib/router.py` | Add `native__task` schema + dispatch |
| `hooks/native-tool-blocking.py` | Add `Task` to unconditional blocking |
| `hooks/hooks.json` | Remove SubagentStart, SubagentStop, PreToolUse:Task |
| `hooks/task-enforcement.py` | DELETE |
| `hooks/subagent-enforcement.py` | DELETE |
| `hooks/subagent-complete.py` | DELETE |

---

## Step 1: Prompt Templates (`config/prompts/*.md`)

Extract hardcoded f-strings from `subagent-enforcement.py` into markdown files with `{{placeholder}}` syntax:

- `tdd.md` — base TDD context (tools, phases, completion format)
- `test_writing.md` — test_writing phase instructions
- `implement.md` — implement phase instructions
- `test.md` — test phase instructions
- `review.md` — review phase instructions
- `restrictions.md` — blocked tools list

## Step 2: PromptBuilder (`lib/prompt_builder.py`)

Minimal class:

```python
class PromptBuilder:
    def __init__(self, templates_dir: Path = None):
        self.templates_dir = templates_dir or Path(__file__).parent.parent / "config" / "prompts"
        self._cache: dict[str, str] = {}

    def render(self, name: str, **kwargs) -> str:
        """Load template and fill {{placeholders}}."""

    def build(self, prompt: str, workflow_state: dict,
              subagent_type: str, agent_id: str) -> str:
        """Assemble enriched prompt from templates + workflow state."""
```

## Step 3: Tool Schema (`lib/router.py`)

Add `native__task` to `_get_native_tool_schemas()`:
- required: `prompt`, `subagent_type`
- optional: `model`, `description`

Add `"task": self._native_task` to `_handle_native()` dispatch dict.

## Step 4: Handler (`lib/controller.py`)

### 4a: Enforcement
- Implementer-only during iterate/orchestrate
- Read from `self._workflow_state` (in-memory)

### 4b: Context + Agent Registration
- Generate agent_id, register in `self._agent_state`, track `active_agents`
- Use `self._prompt_builder.build()` for enriched context

### 4c: Execution via SDK

```python
import asyncio
from claude_agent_sdk import query, ClaudeAgentOptions

async def _run_subagent(self, prompt, context, model, subagent_type):
    options = ClaudeAgentOptions(
        system_prompt=context,
        allowed_tools=["Bash(mcp-call*)", "Bash(mcp*)"],
        permission_mode="bypassPermissions",
        cwd=str(self._project_root),  # or from workflow state
    )
    if model:
        options.extra_args = {"model": model}

    messages = []
    async for message in query(prompt=prompt, options=options):
        messages.append(message)
    return messages
```

Called from synchronous handler via `asyncio.run()`:

```python
def _native_task(self, args: dict) -> dict:
    # ... enforcement, context injection ...
    try:
        messages = asyncio.run(self._run_subagent(prompt, context, model, subagent_type))
        # Extract result from last ResultMessage
        result_msg = next((m for m in reversed(messages) if hasattr(m, 'total_cost_usd')), None)
        text_content = []
        for msg in messages:
            if hasattr(msg, 'content') and isinstance(msg.content, list):
                for block in msg.content:
                    if hasattr(block, 'text'):
                        text_content.append(block.text)
        output = {
            "output": "\n".join(text_content),
            "cost_usd": result_msg.total_cost_usd if result_msg else None,
            "stop_reason": result_msg.stop_reason if result_msg else None,
        }
    except Exception as e:
        output = {"error": str(e), "isError": True}
    # ... completion processing ...
    return output
```

### 4d: Completion Processing
- Extract learnings (LEARNING: regex) from output text
- Move agent `active_agents` -> `completed_tasks`
- Detect failure -> mark agent state
- Return output (caching/summarization in handle_call)

## Step 5: Block Task (`hooks/native-tool-blocking.py`)

```python
if tool_name == "Task":
    block("[BLOCKED] Task blocked — use mcp__router__native__task instead.")
    return
```

## Step 6: Update `hooks/hooks.json`

Remove:
- `PreToolUse:Task` -> `task-enforcement.py`
- `SubagentStart:*` -> `subagent-enforcement.py`
- `SubagentStop:*` -> `subagent-complete.py`

## Step 7: Delete Hook Files

- `hooks/task-enforcement.py`
- `hooks/subagent-enforcement.py`
- `hooks/subagent-complete.py`

## Step 8: Clean Up

- Remove `router__check_task_enforcement` from controller + router schemas
- Init `PromptBuilder` in Controller.__init__()
- Update/remove tests that imported from deleted hooks

---

## Verification

1. Start daemon -> confirm `native__task` in `tools/list`
2. Verify built-in `Task` blocked by hook
3. Call `mcp__router__native__task` with simple prompt -> verify SDK executes
4. Test with iterate workflow active -> verify enriched prompt includes TDD context
5. Test enforcement: non-implementer during orchestrate -> denied
6. Test learning capture from subagent output
7. `pytest tests/`
