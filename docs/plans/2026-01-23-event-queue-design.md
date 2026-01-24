# Event Queue Design Plan

**Status:** Ready for Implementation
**Date:** 2026-01-23
**Last Updated:** 2026-01-24 (Technical specifications added)

---

## Core Insight: Indirect Execution

The key architectural decision is **indirect execution**:

```
Caller → "I want X done" (Event) → Handler → "I'll do X" (Result)
```

Callers never touch tools directly. They express intent. Handlers decide how (and whether) to fulfill it.

**This gives you:**
- **Interception by default** - handlers can refuse, modify, or mock
- **Uniform observability** - all requests visible before execution
- **Caller-agnostic** - hooks, subagents, CLI, tests all look the same
- **Testable** - inject mock handlers, no real tools needed
- **Buffering** - queue requests during backend downtime, rate limit, prioritize

---

## Context: The Problem

### The Original Design

The agent-swarm plugin was built around a **central router** that:
- Routes all MCP tool calls through one place
- Provides visibility into tool usage (telemetry)
- Enables interception (hooks can block/modify)
- Supports injection (responses can be shaped)

**This is a control plane for tool execution.**

### The Flaw

Subagents (spawned via Task tool) **cannot call MCP tools**. Claude Code's permission system blocks them because there's no interactive terminal to approve tool use.

This breaks the central design: if subagents can't go through the router, they bypass the control plane entirely.

### Rejected Solutions

| Solution | Why Rejected |
|----------|--------------|
| Give subagents Bash access | Too powerful, loses control over what they can do |
| Constrained Bash (regex whitelist) | Fragile, easy to bypass, regex hell |
| Pseudo-tools + hooks | Feels like a hack, throwaway code once proper solution exists |

### The Deeper Problem

Current architecture has logic scattered across **20+ hooks**. Each hook:
- Parses input
- Makes decisions
- Executes actions
- Returns results

This is fragile, hard to test, and hard to modify. Adding "subagent tool access" means adding yet another hook with more logic baked in.

---

## Vision: Event Queue as Control Plane

### Core Idea

**Hooks become thin event emitters.** All logic moves to handlers that consume a queue.

```
┌─────────────┐     ┌─────────────────┐
│  Claude     │────▶│  PreToolUse     │──────┐
│  (direct)   │     │  hook           │      │
└─────────────┘     └─────────────────┘      │
                                             │  queue.publish()
┌─────────────┐     ┌─────────────────┐      │
│  Subagent   │────▶│  queue__publish │──────┤
│             │     │  tool + hook    │      │
└─────────────┘     └─────────────────┘      │
                                             ▼
                                    ┌─────────────────┐
                                    │  Event Queue    │
                                    │  (tool_request) │
                                    └────────┬────────┘
                                             │
                                             ▼
                                    ┌─────────────────┐
                                    │  Handlers       │
                                    │  - enforce      │
                                    │  - call_tool    │
                                    │  - telemetry    │
                                    └────────┬────────┘
                                             │
                                             ▼
                                    ┌─────────────────┐
                                    │  Result         │
                                    │  (correlation)  │
                                    └─────────────────┘
```

**All callers use the same path.** The entry points differ (hook vs tool), but they all publish to the same queue, processed by the same handlers.

### Why This Works

1. **Hooks and subagents use the same queue** - unified code path
2. **Handler doesn't care about source** - just processes requests
3. **Full visibility** - all requests flow through one place
4. **Interception** - handlers can block/modify before execution
5. **Injection** - handlers can shape responses

### What Hooks Become

```python
# Before: 50+ lines of logic per hook
# After: ~15 lines - just publish and wait

def pretooluse_hook():
    input = json.loads(sys.stdin.read())
    correlation_id = generate_id()

    # Publish to queue - same as subagents do
    queue.publish("tool_request", {
        "tool": input["tool_name"],
        "args": input.get("tool_input", {}),
        "source": "claude",  # vs "subagent"
        "correlation_id": correlation_id
    })

    # Wait for handler decision
    result = queue.poll(correlation_id)

    # Return allow/block based on handler result
    if result.get("blocked"):
        print(json.dumps({"decision": "block", "message": result["reason"]}))
    else:
        print(json.dumps({"decision": "allow"}))
```

**Claude and subagents use the same queue.** The only difference is the entry point (hook vs queue__publish tool).

---

## Proposed Architecture

### Components

```
lib/
├── events/
│   ├── __init__.py      # get_queue(), publish(), poll()
│   ├── queue.py         # Simple queue implementation
│   └── handlers/
│       ├── call_tool.py # Executes tools via router socket
│       ├── telemetry.py # Logs to telemetry service
│       └── enforce.py   # Checks blocklists
```

### Queue Interface (Minimal)

```python
class EventQueue:
    def publish(self, topic: str, data: dict) -> str:
        """Publish event, return correlation_id."""

    def poll(self, correlation_id: str, timeout_ms: int = 5000) -> Optional[dict]:
        """Wait for response by correlation_id."""

    def subscribe(self, topic: str, handler: Callable):
        """Register handler for topic."""
```

### Request Flow

```python
# 1. Hook or subagent publishes request
correlation_id = queue.publish("tool_request", {
    "tool": "serena__find_symbol",
    "args": {"name_path_pattern": "MyClass"}
})

# 2. call_tool handler picks it up
@queue.subscribe("tool_request")
def handle_tool_request(event):
    result = call_tool(event["tool"], event["args"])
    queue.respond(event["correlation_id"], result)

# 3. Caller polls for result
result = queue.poll(correlation_id)
```

### Handler Chain

Handlers execute in priority order:

| Priority | Handler | Purpose |
|----------|---------|---------|
| 10 | enforce | Block disallowed tools (can short-circuit) |
| 50 | call_tool | Execute via router socket |
| 90 | telemetry | Log after execution |

---

## Subagent Access

### The Key Insight

Subagents can only use tools that Claude Code provides. They can't directly open sockets or run Python.

**Solution:** Expose queue operations as real tools.

```
queue__publish  → publishes to queue (honest operation)
queue__poll     → polls for result (honest operation)
```

The queue gives the tools legitimacy. They're not "pseudo-tools doing magic" - they're actual queue operations.

### How It Works

```
Subagent calls queue__publish(topic="tool_request", data={tool, args})
    ↓
Hook intercepts (before MCP permission check)
    ↓
Hook calls queue.publish() - the tool does what it says
    ↓
Handler picks up event, executes tool
    ↓
Result stored with correlation_id
    ↓
Subagent calls queue__poll(correlation_id)
    ↓
Hook intercepts, calls queue.poll()
    ↓
Result returned to subagent
```

### Why This Isn't a Hack

**Before (without queue):** pseudo-tools would secretly call `call_tool()` directly - magic backdoor that bypasses the system.

**After (with queue):** tools honestly publish/poll a queue. The queue IS the system. No magic.

The hook is just an implementation detail (runs Python instead of going through MCP permission dance). The tools do exactly what they claim to do.

---

## Migration Strategy

### Phase 1: Build Queue Infrastructure
- Create `lib/events/queue.py`
- Create `call_tool` handler
- Test via Python directly

### Phase 2: Subagent Access
- Expose queue via socket (extend router socket handler)
- Create CLI wrapper for subagents
- Test subagent → queue → handler → result flow

### Phase 3: Hook Migration (Incremental)
- Start with one hook (e.g., PreToolUse for router tools)
- Migrate others gradually
- Keep old hooks working during transition

### Phase 4: Consolidation
- Remove old hook logic
- All hooks are thin event emitters
- All logic in handlers

---

## Infrastructure Fix (Done This Session)

### Problem Found
Multiple router instances were spawning (one per Claude Code session), causing stale port files and connection failures.

### Solution Implemented
Modified `bin/mcp-router` to share socket listener:
- First session starts socket, writes pid/port
- Subsequent sessions health-check existing socket
- If healthy: reuse. If dead: clean up and start fresh.

This provides stable infrastructure for the event queue.

---

## Testing Strategy

Given the distributed/async nature, testing must be first-class.

### Unit Tests

```python
# Test event creation and correlation
def test_event_has_correlation_id():
    event = ToolRequest(tool="serena__find_symbol", args={})
    assert event.correlation_id is not None

# Test handler registration
def test_handler_receives_events():
    received = []
    queue = EventQueue()
    queue.subscribe("tool_request", lambda e: received.append(e))
    queue.publish("tool_request", {"tool": "test"})
    assert len(received) == 1
```

### Integration Tests

```python
# Test full roundtrip: publish → handler → response
def test_tool_request_roundtrip():
    queue = EventQueue()
    queue.subscribe("tool_request", mock_tool_handler)

    cid = queue.publish("tool_request", {"tool": "native__bash", "args": {"command": "echo test"}})
    result = queue.poll(cid, timeout_ms=5000)

    assert result is not None
    assert "test" in str(result)

# Test multiple concurrent requests don't interfere
def test_concurrent_requests_isolated():
    queue = EventQueue()
    queue.subscribe("tool_request", slow_handler)  # Adds 100ms delay

    cid1 = queue.publish("tool_request", {"tool": "tool1", "marker": "AAA"})
    cid2 = queue.publish("tool_request", {"tool": "tool2", "marker": "BBB"})

    result1 = queue.poll(cid1)
    result2 = queue.poll(cid2)

    assert "AAA" in str(result1)
    assert "BBB" in str(result2)  # Not mixed up
```

### Multi-Session Tests

```python
# Test that multiple Claude sessions can use shared queue
def test_multi_session_isolation():
    # Session 1 publishes
    cid1 = call_from_session("session-1", "tool_request", {"marker": "S1"})

    # Session 2 publishes
    cid2 = call_from_session("session-2", "tool_request", {"marker": "S2"})

    # Each gets their own result
    r1 = poll_from_session("session-1", cid1)
    r2 = poll_from_session("session-2", cid2)

    assert "S1" in str(r1)
    assert "S2" in str(r2)
```

### Observability Tests

```python
# Test that all events are logged
def test_events_observable():
    queue = EventQueue(trace=True)
    queue.publish("tool_request", {"tool": "test"})

    history = queue.get_event_history()
    assert len(history) == 1
    assert history[0]["event_type"] == "tool_request"

# Test correlation ID traces full lifecycle
def test_correlation_id_traces_lifecycle():
    queue = EventQueue(trace=True)
    cid = queue.publish("tool_request", {"tool": "test"})
    queue.poll(cid)

    trace = queue.get_trace(cid)
    assert "published" in trace
    assert "handler_received" in trace
    assert "response_sent" in trace
```

### Failure Mode Tests

```python
# Test handler timeout
def test_handler_timeout_returns_error():
    queue = EventQueue(handler_timeout_ms=100)
    queue.subscribe("tool_request", infinite_loop_handler)

    cid = queue.publish("tool_request", {"tool": "test"})
    result = queue.poll(cid, timeout_ms=500)

    assert result["error"] == "handler_timeout"

# Test handler crash doesn't break queue
def test_handler_crash_isolated():
    queue = EventQueue()
    queue.subscribe("tool_request", crashing_handler)

    cid1 = queue.publish("tool_request", {"crash": True})
    cid2 = queue.publish("tool_request", {"crash": False})

    r1 = queue.poll(cid1)
    r2 = queue.poll(cid2)

    assert r1["error"] is not None
    assert r2["error"] is None  # Second request unaffected
```

---

## Technical Specifications

### Concurrency Model

Events dispatched to a **thread pool**. Each event processed independently. Handlers for a single event run **sequentially by priority**.

```python
class EventQueue:
    def __init__(self, max_workers: int = 4):
        self._executor = ThreadPoolExecutor(max_workers=max_workers)

    def _dispatch(self, event: dict) -> None:
        self._executor.submit(self._run_handler_chain, event)
```

**Rationale:** Thread pool matches existing router socket pattern. 4 workers handles typical multi-session workloads without thread explosion.

---

### Correlation ID Format

**Format:** UUID4 hex, 32 characters (e.g., `a1b2c3d4e5f6789012345678abcdef01`)

**Generated by:** `queue.publish()` - caller doesn't provide it.

```python
import uuid

def publish(self, topic: str, data: dict) -> str:
    correlation_id = uuid.uuid4().hex
    # ...
    return correlation_id
```

**Rationale:** No prefix needed - UUID is already unique and identifiable. Simpler.

---

### Result Buffer & Cleanup

**Storage:** In-memory dict mapping correlation_id → (result, expiry_time)

**TTL:** 60 seconds (configurable via `result_ttl_seconds`)

**Cleanup:** Background thread reaps expired entries every 10 seconds.

```python
self._responses: dict[str, tuple[dict, float]] = {}

def _cleanup_expired(self):
    now = time.time()
    expired = [cid for cid, (_, exp) in self._responses.items() if exp < now]
    for cid in expired:
        del self._responses[cid]
```

**Rationale:** 60s is long enough for any reasonable tool call, short enough to prevent unbounded growth. Easy to tune based on real usage.

---

### Queue Persistence

**MVP:** In-memory only. Requests in flight are lost on router restart. Callers handle via timeout.

**Future:** Can add SQLite/DB persistence layer without changing interface. The `respond()` and `poll()` methods abstract storage.

**Rationale:** Router restarts are rare. Simplicity beats durability for MVP. Migration path is clear.

---

### Event Schema

```python
@dataclass
class ToolRequestEvent:
    # Required
    tool: str                    # Tool name (e.g., "serena__find_symbol")
    args: dict                   # Tool arguments
    source: str                  # "claude" | "subagent" | "cli" | "test"

    # Set by queue (caller doesn't provide)
    correlation_id: str          # UUID4 hex
    timestamp: str               # ISO 8601 (e.g., "2026-01-23T15:30:00Z")

    # Optional
    session_id: Optional[str] = None   # For debugging/tracing
    metadata: Optional[dict] = None    # Extensible
```

**Validation:** Queue rejects events missing required fields with immediate error response.

---

### Handler Chain Semantics

Handlers return a `HandlerResult` to control flow:

```python
@dataclass
class HandlerResult:
    continue_chain: bool = True      # False = stop processing, skip remaining handlers
    response: Optional[dict] = None  # If set, becomes the result for this event
```

**Execution order:**
1. Handlers sorted by priority (lower = first)
2. Each handler runs, gets `HandlerResult`
3. If `continue_chain=False`, stop and use that handler's response
4. If `response` is set, it overwrites any previous response
5. After all handlers (or short-circuit), final response stored for polling

**Example:**
- `enforce` (priority 10): Returns `HandlerResult(continue_chain=False, response={"blocked": True})` → chain stops, blocked response returned
- `call_tool` (priority 50): Returns `HandlerResult(response={"result": ...})` → continues to telemetry
- `telemetry` (priority 90): Returns `HandlerResult()` → just logs, no response change

---

### Timeout Handling

**Two separate timeouts:**

| Timeout | Default | What happens |
|---------|---------|--------------|
| Poll timeout | 5000ms | `poll()` returns `{"error": "poll_timeout", "correlation_id": "..."}` |
| Handler timeout | 30000ms | Handler killed, returns `{"error": "handler_timeout", "handler": "call_tool"}` |

**No dead letter queue** for MVP. Errors return to caller; they can retry or handle as needed.

```python
def poll(self, correlation_id: str, timeout_ms: int = 5000) -> dict:
    """Returns result dict or error dict. Never raises."""
```

---

### Error Propagation

Standardized error envelope:

```python
{
    "error": str,           # Error type: "poll_timeout", "handler_timeout", "handler_exception", "blocked", "validation_error"
    "message": str,         # Human-readable description
    "correlation_id": str,  # For tracing
    "handler": Optional[str],  # Which handler failed (if applicable)
    "timestamp": str        # When error occurred
}
```

**Stack traces:** Logged server-side. Not included in response (security). Enable `trace=True` for debugging.

---

### Complete Queue Interface

```python
class EventQueue:
    def __init__(
        self,
        max_workers: int = 4,
        result_ttl_seconds: int = 60,
        handler_timeout_ms: int = 30000
    ): ...

    def publish(self, topic: str, data: dict) -> str:
        """Publish event. Returns correlation_id."""

    def poll(self, correlation_id: str, timeout_ms: int = 5000) -> dict:
        """Wait for result. Returns result dict or error dict."""

    def subscribe(self, topic: str, handler: Callable, priority: int = 50) -> None:
        """Register handler for topic. Lower priority = runs first."""

    def respond(self, correlation_id: str, data: dict) -> None:
        """Store response for correlation_id. Called by handlers."""

    # Observability
    def get_event_history(self, limit: int = 100) -> list[dict]:
        """Recent events (when trace=True)."""

    def get_pending_count(self) -> int:
        """Number of events awaiting handler completion."""
```

---

### Hook → Queue Connection

Hooks connect via **socket** to the router process (same as existing `call_tool()`).

```python
# lib/workflow_client.py additions

def queue_publish(topic: str, data: dict) -> str:
    """Publish to queue via router socket. Returns correlation_id."""
    return _socket_call("queue/publish", {"topic": topic, "data": data})

def queue_poll(correlation_id: str, timeout_ms: int = 5000) -> dict:
    """Poll queue via router socket. Returns result or error."""
    return _socket_call("queue/poll", {"correlation_id": correlation_id, "timeout_ms": timeout_ms})
```

**Rationale:** Queue lives in router process. Hooks are separate processes. Socket is the existing IPC mechanism.

---

### Socket Protocol Extensions

Extend existing JSON-RPC socket with new methods:

```json
// Publish
{"jsonrpc": "2.0", "method": "queue/publish", "params": {"topic": "tool_request", "data": {"tool": "...", "args": {...}, "source": "subagent"}}, "id": 1}
// Response
{"jsonrpc": "2.0", "result": {"correlation_id": "a1b2c3..."}, "id": 1}

// Poll
{"jsonrpc": "2.0", "method": "queue/poll", "params": {"correlation_id": "a1b2c3...", "timeout_ms": 5000}, "id": 2}
// Response (success)
{"jsonrpc": "2.0", "result": {"tool_result": {...}}, "id": 2}
// Response (error)
{"jsonrpc": "2.0", "result": {"error": "poll_timeout", "correlation_id": "a1b2c3..."}, "id": 2}
```

**Mirrors existing:** `tools/call`, `tools/list` patterns.

---

### Multiple Handlers Per Topic

**Allowed:** Yes. Multiple handlers can subscribe to same topic.

**Order:** Sorted by priority (ascending). Priority 10 runs before priority 50.

**Execution:** All handlers run unless one short-circuits via `continue_chain=False`.

```python
queue.subscribe("tool_request", enforce_handler, priority=10)   # Runs first
queue.subscribe("tool_request", call_tool_handler, priority=50)  # Runs second
queue.subscribe("tool_request", telemetry_handler, priority=90)  # Runs last
```

---

## Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| **Migration path** | Build as layer above socket, not replacement. Compatibility shim. Prove value before migrating critical paths. |
| **Debugging complexity** | Correlation IDs everywhere. Structured logging at every boundary. `--trace` mode. Inspectable event history. |
| **Latency overhead** | Fast path when no hooks registered. Synchronous mode for simple calls. Measure from day one. |
| **Complexity creep** | Strict scope (tools only). Minimal event types (`ToolRequest`, `ToolResult`). Single handler per type initially. Delete direct socket path after migration. |

**Key principle:** "The risk isn't that the design is wrong. The risk is that implementation sprawl turns a clean abstraction into a complex mess. Scope discipline is everything."

---

## Success Criteria

1. Subagents can execute tools through the control plane
2. All tool calls visible in telemetry (unchanged)
3. Tools can be blocked/intercepted centrally
4. Adding new behavior = adding a handler (not modifying hooks)
5. Hooks are < 15 lines each

---

## For Adversarial Review

**Thesis:** We need an event queue because:
1. Subagents can't access MCP tools (permission blocker)
2. Hooks are becoming unmanageable (20+ with scattered logic)
3. A queue provides unified control plane for all callers

**Challenge this:**
- Is the event queue overengineered?
- Are there simpler solutions we rejected too quickly?
- What's the minimum viable change to enable subagent tool access?
- Could we solve the subagent problem WITHOUT touching the hook architecture?
- Is consolidating hooks actually worth the migration cost?
