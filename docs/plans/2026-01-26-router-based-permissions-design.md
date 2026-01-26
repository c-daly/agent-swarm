# Router-Based Permissions Design

## Overview

Add permission enforcement to the MCP router. The router becomes the single authority for tool access control, replacing self-enforced agent permissions.

## Goals

1. **Enforcement gap** - Router blocks unauthorized calls (not just agent self-enforcement)
2. **Dynamic permissions** - Vary by agent type, roles, and workflow phase
3. **Centralized config** - Single `permissions.yaml` file for all rules

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                      MCP Router                         │
│                                                         │
│   self.telemetry = TelemetryCollector(...)             │
│   self.permissions = PermissionChecker(...)  ← NEW     │
│                                                         │
│   def route(tool_name, args):                          │
│       agent_id = args.pop("_agent_id")  # required     │
│       agent_info = self.agent_registry.get(agent_id)   │
│       phase = self.get_workflow_phase()                │
│                                                         │
│       allowed, response = self.permissions.check(      │
│           tool=tool_name,                              │
│           args=args,                                   │
│           agent_type=agent_info.type,                  │
│           roles=agent_info.roles,                      │
│           phase=phase,                                 │
│       )                                                │
│       if not allowed:                                  │
│           return response  # BlockedResponse           │
│                                                         │
│       return self._forward_to_server(...)              │
└─────────────────────────────────────────────────────────┘
```

## New Files

- `lib/mcp_permissions.py` - Permission checker class
- `config/permissions.yaml` - Permission rules

## Modified Files

- `lib/mcp_router.py` - Incorporates PermissionChecker, adds agent registry

## Permissions File Format

`config/permissions.yaml`:

```yaml
global:
  allowed: [mcp__router__*]
  blocked: [Bash, Edit, Write]
  superblocked: [Bash(rm -rf*), Bash(sudo*)]

roles:
  read_only:
    allowed: [Read, Glob, Grep, WebSearch, WebFetch]
    blocked: []
  editor:
    allowed: [Edit, Write, Bash(mcp-call*)]
    blocked: []
  workflow_control:
    allowed: [mcp__router__workflow__*]
    blocked: []

agents:
  explorer:
    allowed: []
    blocked: [Task]
  implementer:
    allowed: []
    blocked: [Bash(rm*)]
  orchestrator:
    allowed: [Task]
    blocked: []

workflows:
  debug:
    triage:
      allowed: []
      blocked: [Edit, Write]
    fix:
      allowed: [Edit, Write]
      blocked: []
  iterate:
    orchestrate:
      allowed: []
      blocked: [Edit, Write, Bash]
    implement:
      allowed: [Edit, Write]
      blocked: []
```

### Structure

- **global**: Base rules for all callers
  - `allowed`: Default allowed tools
  - `blocked`: Default blocked tools (can be overridden by more specific layers)
  - `superblocked`: Never overridable, checked first
- **roles**: Named permission bundles (allowed + blocked lists)
- **agents**: Agent-specific overrides (allowed + blocked lists)
- **workflows**: Workflow/phase specific rules (allowed + blocked lists)

### Key Points

- All fields are explicit lists (use `[]` for empty)
- Role assignment comes from agent definitions or spawn context, not this file
- Superblocked only defined at global level

## Evaluation Logic

```python
def check(tool, args, agent_type, roles, workflow, phase):
    # 1. Superblocked (global only) - immediate reject
    if matches_any(tool, args, global.superblocked):
        return Blocked("superblocked - cannot override")

    # 2. Build effective permissions by layer (more specific wins)
    effective = {"allowed": set(), "blocked": set()}

    apply_rules(effective, global)                      # Layer 1
    for role in roles:
        apply_rules(effective, roles[role])             # Layer 2
    apply_rules(effective, agents[agent_type])          # Layer 3
    if workflow and phase:
        apply_rules(effective, workflows[workflow][phase])  # Layer 4

    # 3. Check blocked first
    if matches_any(tool, args, effective.blocked):
        return Blocked("blocked")

    # 4. Must be explicitly allowed
    if matches_any(tool, args, effective.allowed):
        return Allowed()

    # 5. Default deny
    return Blocked("not in allowed list")
```

### Layer Precedence

Each layer can add to `allowed` or `blocked`. More specific layers override less specific:

```
global → roles → agents → workflow/phase
```

Example: Global blocks `Bash`, but `editor` role allows `Bash(mcp-call*)`. An agent with `editor` role can use `Bash(mcp-call*)`.

## Agent Registry

In-memory dict in router, tracks `agent_id → {type, roles}`.

### Registration

Happens automatically when router sees Task spawn:

```python
# Router intercepts Task call
if tool_name == "Task":
    agent_id = generate_unique_id(session_id)
    agent_type = args.get("subagent_type")
    roles = args.get("roles", [])  # or derive from agent definition
    self.agent_registry.register(agent_id, agent_type, roles)
```

### Lookup

Every tool call must include `_agent_id`:

```python
agent_id = args.pop("_agent_id", None)
if not agent_id:
    return BlockedResponse("Missing required _agent_id")

agent_info = self.agent_registry.get(agent_id)
if not agent_info:
    return BlockedResponse(f"Unknown agent: {agent_id}")
```

### Uniqueness

Agent IDs must be unique across sessions. Use session context in ID generation to avoid collisions in federated multi-session environment.

## Pattern Matching

| Pattern | Matches |
|---------|---------|
| `Edit` | Tool name exactly |
| `mcp__router__*` | Tool name glob |
| `Bash(mcp-call*)` | Tool name + command arg glob |
| `Edit(tests/**)` | Tool name + file_path arg glob |

```python
def matches(pattern: str, tool: str, args: dict) -> bool:
    if "(" in pattern:
        # Tool with arg pattern: Bash(mcp-call*)
        tool_part, arg_pattern = pattern.rstrip(")").split("(", 1)
        if not fnmatch(tool, tool_part):
            return False
        # Check command arg for Bash, file_path for Edit/Write
        arg_value = args.get("command") or args.get("file_path") or ""
        return fnmatch(arg_value, arg_pattern)
    else:
        # Simple tool name or glob
        return fnmatch(tool, pattern)
```

## Blocked Response Format

When router blocks a call, return actionable feedback:

```json
{
  "blocked": true,
  "reason": "blocked by workflow phase",
  "tool": "Edit",
  "agent_type": "implementer",
  "phase": "iterate/orchestrate",
  "rule_that_blocked": "workflows.iterate.orchestrate.blocked: [Edit]",
  "guidance": "Edit is blocked in orchestrate phase. Delegate editing to an implementer subagent, or transition to implement phase first."
}
```

### Guidance Templates

| Block Type | Guidance |
|------------|----------|
| superblocked | "This action is never permitted. Find an alternative approach." |
| phase blocked | "Tool X blocked in Y phase. Transition to Z phase or delegate to appropriate agent." |
| agent blocked | "Your agent type cannot use X. Delegate to agent type Y." |
| not in allowed | "Tool not in your allowed list. Check if a router-prefixed version exists." |

## Implementation Phases

### Phase 1: Core Infrastructure
- Create `lib/mcp_permissions.py` with PermissionChecker class
- Create `config/permissions.yaml` with initial rules
- Add agent registry to router
- Integrate permission check in route()

### Phase 2: Agent Updates
- Update agent prompts to include `_agent_id` in all tool calls
- Register agents at Task spawn
- Add roles to agent definitions

### Phase 3: Migration
- Migrate workflow phase rules from Python to yaml
- Deprecate `permission_store.py` (can coexist during transition)
- Full audit trail via telemetry

## Out of Scope

- Automatic migration of existing `permission_store.py`
- UI for permission management
- Real-time permission updates (requires router restart)
