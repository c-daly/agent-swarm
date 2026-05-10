# `lib/` — Python library modules

## Architecture orientation

The daemon is a long-lived process (port 7523) that owns all of agent-swarm's state. Layers, top-down:

- **`lib/daemon.py`** — entry point. Singleton (flock at `.daemon.lock`). Loads workflow configs from `config/workflows/*.yaml` once at startup; **no hot-reload** — restart after config changes. In-memory state is lost on restart.
- **`lib/router.py`** — TCP server. Accepts both MCP-protocol and internal JSON-RPC connections; translates and delegates to controller.
- **`lib/controller.py`** — RPC handler. Owns permissions + workflow + agent state. Notable entry points:
  - `_prepare_dispatch` (line ~582) — generates a `sub-XXXXXXXX` agent ID, registers in permissions, assembles a role-specific briefing, records agent state. Called by the agent-dispatch hook before subagent `Task()` proceeds.
  - `_get_agent_briefing` — main-agent briefing (subagents get theirs via dispatch hook `additionalContext`).
  - `handle_call(tool_name, args)` — routes named tools (e.g. `prepare_dispatch`, `agent/register`).
- **`lib/permissions.py`** + **`lib/permission_query.py`** — yaml-driven layered allow/block (`global` → `roles` → `agents` → `workflow/phase`). `permission_query._KNOWN_WORKFLOWS` is a hardcoded list — see `config/workflows/CLAUDE.md` for the security gotcha when adding a new workflow.
- **Per-workflow engines** — `lib/implementer_workflow.py`, `lib/develop_workflow.py`, `lib/pr_comment_workflow.py`, etc. These are the only places where YAML fields like `max_iterations` and `max_agents` are read; workflows without a corresponding engine module silently ignore those fields.

## Briefing assembly

`lib/protocol_assembly.py` assembles role/workflow briefings used by `_prepare_dispatch`. If we ever auto-inject project state (vault narrative head, open-recs slice) into subagent briefings, this is the seam — likely a new helper that reads canonical state files and concatenates the result into `assemble_subagent_briefing`'s output.

## DaemonClient (the in-process router)

`lib/daemon_client.py` is the Python client used by hooks, tests, and the orchestrator main agent. Key methods:

- `register(agent_id, agent_type, session_id, workflow_id)` — registers a connection's identity. One register per connection (raises if called twice).
- `call_tool(name, arguments)` — generic `tools/call`. Most agent work goes through here. Requires registration (the `_call` whitelist allows `agent/*` and `workflow/*` without registration).
- `workflow_start`, `workflow_stop`, `workflow_get_state`, `workflow_set_value`, `workflow_is_active`, `workflow_advance_phase`, `workflow_pass_checkpoint` — workflow-state RPCs (no registration required).
- `_call("agent/get_state", {agent_id})` — raw RPC; used by the registration-enforcement hook to verify a fabricated ID was actually issued.
