# Handoff: Hooks Refactor Session 4 (2026-02-01)

## Branch
`feature/hooks-refactor` — continuing from session 3

## No Code Changes This Session
This was a planning/research session. No commits, no code edits.

## Key Discovery: `claude_agent_sdk` (v0.1.27)
- Installed and confirmed working
- Import: `from claude_agent_sdk import query, ClaudeAgentOptions`
- **No API key needed** — uses Claude Code CLI auth (subscription works)
- Async API: `async for message in query(prompt=..., options=...)`
- Supports: `allowed_tools`, `permission_mode`, `system_prompt`, `cwd`, in-process MCP servers, hooks
- Known issue: anyio cancel scope error on Python 3.13 (cosmetic, doesn't affect results)
- `ResultMessage` has `total_cost_usd` but NOT `stop_reason`
- Test script: `test_sdk.py` in project root (can delete)

## Plan: `native__task` on Router
Full plan at `docs/plans/native-task-plan.md`. Summary:

### What Gets Built
1. **`lib/prompt_builder.py`** — PromptBuilder class loads markdown templates from `config/prompts/*.md`, fills `{{placeholders}}`, assembles enriched prompts from workflow state
2. **`config/prompts/*.md`** — ~6 template files (tdd, test_writing, implement, test, review, restrictions) extracted from subagent-enforcement.py
3. **`native__task` tool** — schema in router.py, handler in controller.py
4. **Handler flow**: enforcement → context injection (PromptBuilder) → `claude_agent_sdk.query()` → completion processing (learnings, workflow state, failure detection)

### What Gets Deleted
- `hooks/task-enforcement.py`
- `hooks/subagent-enforcement.py`
- `hooks/subagent-complete.py`
- Their entries in `hooks/hooks.json` (PreToolUse:Task, SubagentStart, SubagentStop)
- `router__check_task_enforcement` from controller/router

### What Gets Modified
- `hooks/native-tool-blocking.py` — add `Task` to unconditional blocking
- `hooks/hooks.json` — remove 3 entries
- `lib/controller.py` — add `_native_task()`, init PromptBuilder
- `lib/router.py` — add schema, add dispatch

### Architecture After
```
Claude Code -> native-tool-blocking.py blocks Task
           -> mcp__router__native__task -> controller
           -> PromptBuilder enriches prompt
           -> claude_agent_sdk.query() spawns subagent
           -> completion processing (learnings, state, failures)
           -> result returned through caching/summarization
```

One hook remains: `native-tool-blocking.py` (blocks Task + non-mcp Bash).

### Open Considerations
- SDK is async; controller is sync. Use `asyncio.run()` in handler.
- `--allowedTools "Bash(mcp-call*)"` pattern needs verification with SDK's `allowed_tools`
- SDK supports in-process MCP servers — future path to expose router tools directly to subagents instead of mcp-call

## Stale Files
- `test_sdk.py` — test script, can delete
- `tempfile` — leftover from session 2/3, can delete
