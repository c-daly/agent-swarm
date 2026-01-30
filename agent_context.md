# Subagent Operating Context

Injected into subagent prompts for project awareness.

## Project: agent-swarm

Plugin for Claude Code that adds orchestrated multi-agent workflows. Subagents are spawned via Claude Code's `Task` tool and communicate through MCP router tools.

## Key Abstractions

| Concept | Location | Purpose |
|---------|----------|---------|
| Workflow state | `lib/workflow_state_service.py` | Persistent state across workflow phases |
| Workflow client | `lib/workflow_client.py` | Agent-side API for reading/writing state |
| Task queue | `lib/workflow_queue.py` | Ordered task list for iterate workflow |
| Router | `lib/routing_service.py` | MCP tool routing between servers |
| Hook enforcement | `hooks/combined_enforcement.py` | Tool permission gates per workflow phase |
| Agent protocol | `lib/agent_protocol.py` | Structured agent communication format |

## Architecture Layers

1. **Skills** (`skills/`) — User-invocable workflows (iterate, debug, implement, spawn)
2. **Agents** (`agents/`) — Subagent role definitions (implementer, explorer, reviewer, etc.)
3. **Lib** (`lib/`) — Core logic (workflows, state, routing, queues)
4. **Hooks** (`hooks/`) — Enforcement gates (tool blocking, context injection, agent limits)
5. **Scripts** (`scripts/`, `lib/scripts/`) — Batch utilities for token efficiency

## Common Patterns

- **State persistence**: Use `workflow_client.get/set` for cross-phase data
- **Tool access**: All tools via MCP router (`serena__*`, `native__*`, `context7__*`)
- **Batch operations**: 3+ similar operations → use scripts in `lib/scripts/`
- **Testing**: `pytest tests/` with `ruff check .` for linting

## Key Paths

- Plugin root: `~/.claude/plugins/agent-swarm/`
- Agent definitions: `agents/*.md`
- Workflow skills: `skills/*/SKILL.md`
- Enforcement hooks: `hooks/*.py`
- Batch scripts: `lib/scripts/`, `scripts/`
