 ## Solution: Event-Driven Architecture

  ### 1. Central Event System

  Replace 20+ hooks with a single event bus. Components become publishers and subscribers.

  **Event Types:**

  Lifecycle:  SessionStarted, SessionEnding, ContextCompacting
  Tool:       ToolRequested, ToolExecuted, ToolBlocked
  Workflow:   PhaseEntered, PhaseExited, CheckpointReached
  Agent:      SubagentSpawned, SubagentCompleted, SubagentFailed
  State:      StateChanged, WorkflowStarted, WorkflowStopped

  **Event Structure:**

  ```python
  @dataclass
  class Event:
      type: str           # e.g., "ToolRequested"
      timestamp: float
      payload: dict       # Event-specific data
      source: str         # Who emitted it
      cancellable: bool   # Can handlers prevent it?

  EventBus Interface:

  class EventBus:
      def subscribe(self, event_type: str, handler: Callable, priority: int) -> None
      def unsubscribe(self, event_type: str, handler: Callable) -> None
      def publish(self, event: Event) -> EventResult
      def publish_async(self, event: Event) -> None

  2. Hook-to-Handler Migration

  Claude Code hooks become thin bridges to the event bus:
  ┌──────────────────────┬───────────────────────────────┐
  │      Hook File       │           Publishes           │
  ├──────────────────────┼───────────────────────────────┤
  │ hooks/pretooluse.py  │ ToolRequested                 │
  ├──────────────────────┼───────────────────────────────┤
  │ hooks/posttooluse.py │ ToolExecuted                  │
  ├──────────────────────┼───────────────────────────────┤
  │ hooks/session.py     │ SessionStarted, SessionEnding │
  ├──────────────────────┼───────────────────────────────┤
  │ hooks/compact.py     │ ContextCompacting             │
  └──────────────────────┴───────────────────────────────┘
  Current 20+ hooks consolidate into ~8 handlers:

  ENFORCEMENT (subscribe to ToolRequested)
  ├── IterateEnforcementHandler
  ├── BaseEnforcementHandler
  └── StateProtectionHandler

  TELEMETRY (subscribe to ToolRequested + ToolExecuted)
  └── TelemetryHandler

  TRACKING (subscribe to SubagentCompleted + ToolExecuted)
  └── ProgressTrackingHandler

  STATE (subscribe to StateChanged + PhaseEntered)
  ├── WorkflowStateHandler
  └── PhaseTransitionHandler

  LIFECYCLE (subscribe to SessionStarted + SessionEnding + ContextCompacting)
  └── SessionLifecycleHandler

  OUTPUT (subscribe to ToolExecuted)
  └── OutputSummarizationHandler

  3. Package Structure

  agent-swarm/
  ├── bin/
  │   ├── mcp-router              # → lib.mcp_servers.router.server:main
  │   └── mcp-state               # → lib.mcp_servers.state.server:main
  │
  ├── hooks/                       # Thin bridges (4 files)
  │   ├── pretooluse.py
  │   ├── posttooluse.py
  │   ├── session.py
  │   └── compact.py
  │
  ├── lib/
  │   ├── events/
  │   │   ├── __init__.py
  │   │   ├── bus.py              # EventBus implementation
  │   │   ├── types.py            # Event definitions
  │   │   └── handlers/
  │   │       ├── __init__.py
  │   │       ├── enforcement.py
  │   │       ├── telemetry.py
  │   │       ├── tracking.py
  │   │       ├── lifecycle.py
  │   │       └── summarization.py
  │   │
  │   ├── workflows/
  │   │   ├── __init__.py
  │   │   ├── base.py             # Base workflow class
  │   │   ├── orchestrate/
  │   │   │   ├── __init__.py
  │   │   │   ├── engine.py
  │   │   │   ├── phases.py
  │   │   │   ├── checkpoints.py
  │   │   │   └── config.py
  │   │   └── iterate/
  │   │       ├── __init__.py
  │   │       ├── engine.py
  │   │       ├── test_runner.py
  │   │       ├── coverage.py
  │   │       └── gates.py
  │   │
  │   ├── mcp_servers/
  │   │   ├── __init__.py
  │   │   ├── router/
  │   │   │   ├── __init__.py
  │   │   │   ├── server.py       # Entry point
  │   │   │   ├── router.py       # MCPRouter facade
  │   │   │   └── lib/
  │   │   │       ├── __init__.py
  │   │   │       ├── connections.py
  │   │   │       ├── summarizer.py
  │   │   │       ├── telemetry.py
  │   │   │       └── ipc.py
  │   │   └── state/
  │   │       ├── __init__.py
  │   │       ├── server.py       # Entry point
  │   │       ├── client.py       # Client for callers
  │   │       ├── interface.py    # Abstract StateBackend
  │   │       └── lib/
  │   │           ├── __init__.py
  │   │           ├── mcp_backend.py
  │   │           ├── memory_backend.py
  │   │           ├── storage.py
  │   │           └── queue.py
  │   │
  │   ├── tools/
  │   │   ├── __init__.py
  │   │   ├── native.py           # Native tool wrappers
  │   │   └── bridge.py           # Programmatic MCP access
  │   │
  │   ├── agents/
  │   │   ├── __init__.py
  │   │   ├── pool.py             # Worker pool
  │   │   └── protocol.py         # Agent communication
  │   │
  │   └── utils/
  │       ├── __init__.py
  │       └── batch.py            # Batch operation helpers
  │
  ├── agents/                      # Agent definitions (unchanged)
  ├── skills/                      # Skill definitions (unchanged)
  ├── commands/                    # Commands (unchanged)
  ├── config/
  │   └── workflow.json           # Simplified config
  └── tests/                       # Reorganized to match lib/
      ├── events/
      ├── workflows/
      ├── mcp_servers/
      └── ...

  4. State Management with DIP

  Interface:

  # lib/mcp_servers/state/interface.py
  from abc import ABC, abstractmethod

  class StateBackend(ABC):
      @abstractmethod
      def get_workflow(self, workflow_id: str) -> dict: ...

      @abstractmethod
      def set_workflow(self, workflow_id: str, state: dict) -> None: ...

      @abstractmethod
      def update_workflow(self, workflow_id: str, updates: dict) -> None: ...

      @abstractmethod
      def get_agent(self, agent_id: str) -> dict: ...

      @abstractmethod
      def set_agent(self, agent_id: str, state: dict) -> None: ...

  Implementations:

  - MCPStateBackend - Production (calls MCP server)
  - MemoryStateBackend - Testing (in-memory dict)

  Usage:

  class IterateWorkflow:
      def __init__(self, state: StateBackend):
          self.state = state  # Injected, not imported

  5. Data Flow Example

  ToolRequested flow:

  1. Claude calls a tool
  2. hooks/pretooluse.py receives it
  3. Hook publishes ToolRequested event to EventBus
  4. EventBus calls handlers in priority order:
     - EnforcementHandler (priority 10) → checks if blocked
     - TelemetryHandler (priority 50) → logs the request
  5. If not blocked, hook returns "allow"
  6. Tool executes via mcp_servers/router/
  7. hooks/posttooluse.py publishes ToolExecuted
  8. Handlers react (telemetry, tracking, summarization)

  ---
  SOLID Improvements
  ┌───────────┬────────────────────────────────────────────┬────────────────────────────────────────────────┐
  │ Principle │                   Before                   │                     After                      │
  ├───────────┼────────────────────────────────────────────┼────────────────────────────────────────────────┤
  │ SRP       │ Hooks handle state + logging + enforcement │ Each handler does one thing                    │
  ├───────────┼────────────────────────────────────────────┼────────────────────────────────────────────────┤
  │ OCP       │ Add behavior = new hook file + config      │ Add behavior = new handler + register          │
  ├───────────┼────────────────────────────────────────────┼────────────────────────────────────────────────┤
  │ DIP       │ Direct imports of MCP state                │ StateBackend interface, inject implementations │
  └───────────┴────────────────────────────────────────────┴────────────────────────────────────────────────┘
  ---
  Migration Strategy

  This is a big-bang refactor (not incremental). Tests will be rewritten to match new structure.

  Order of operations:

  1. Create lib/events/ with EventBus and types
  2. Create handler classes (logic extracted from current hooks)
  3. Create thin hook bridges
  4. Restructure lib/ into packages (workflows/, mcp_servers/, tools/, agents/, utils/)
  5. Extract MCPRouter into mcp_servers/router/
  6. Extract state management into mcp_servers/state/ with DIP interface
  7. Update tests to match new structure
  8. Remove old files

  ---
  Files to Delete After Migration

  hooks/telemetry-pretool.py
  hooks/telemetry-posttool.py
  hooks/base-enforcement.py
  hooks/iterate-enforcement.py
  hooks/state-protection.py
  hooks/post-tool-tracking.py
  hooks/subagent-complete.py
  hooks/session-start.py
  hooks/session-end.py
  hooks/pre-compacting.py
  hooks/mcp-summarizer.py
  ... (all other individual hooks)

  lib/mcp_router.py (51KB → split into mcp_servers/router/)
  lib/iterate_workflow.py (53KB → split into workflows/iterate/)
  lib/workflow_server.py → mcp_servers/state/
  lib/workflow_client.py → mcp_servers/state/
  lib/workflow_queue.py → mcp_servers/state/lib/
  ... (all flat lib/ files get reorganized)

