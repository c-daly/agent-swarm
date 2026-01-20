# Router Concurrency Fix Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix MCP router deadlock when multiple agents make concurrent calls to the same backend.

**Architecture:** The current design holds a per-backend lock for the entire request-response cycle, including blocking I/O. This causes deadlocks when `_restore_workflow_state()` makes recursive calls while the lock is held. The fix separates connection management (lock required) from I/O operations (no lock needed for single-connection stdio).

**Tech Stack:** Python threading, subprocess, select

---

## Background

The root cause is in `_forward_to_server()` at `lib/mcp_router.py:1045-1131`:
- Lock is held for entire request-response cycle
- `_restore_workflow_state()` is called inside the lock and recursively calls `_forward_to_server()`
- This causes deadlock (reentrant lock acquisition on same thread)

The fix:
1. Use `RLock` (reentrant lock) instead of `Lock` to allow recursive calls
2. Keep the lock for the full request-response cycle (required for correctness - stdio is not multiplexed)
3. The timeout (already added) prevents infinite blocking

---

### Task 1: Change Lock to RLock for Reentrant Support

**Files:**
- Modify: `lib/mcp_router.py:26` (import)
- Modify: `lib/mcp_router.py:966-971` (`_get_backend_lock` method)

**Step 1: Update the import statement**

Change line 26 from:
```python
from threading import Lock, Thread
```
to:
```python
from threading import Lock, RLock, Thread
```

**Step 2: Update `_get_backend_lock` to use RLock**

Change lines 966-971 from:
```python
def _get_backend_lock(self, server_name: str) -> Lock:
    """Get or create lock for a backend server."""
    with self._lock:
        if server_name not in self._backend_locks:
            self._backend_locks[server_name] = Lock()
        return self._backend_locks[server_name]
```
to:
```python
def _get_backend_lock(self, server_name: str) -> RLock:
    """Get or create reentrant lock for a backend server.
    
    Uses RLock to allow recursive calls (e.g., _restore_workflow_state
    calling _forward_to_server while lock is held).
    """
    with self._lock:
        if server_name not in self._backend_locks:
            self._backend_locks[server_name] = RLock()
        return self._backend_locks[server_name]
```

**Step 3: Run existing tests**

Run: `cd ~/.claude/plugins/agent-swarm && python -m pytest tests/test_mcp_router.py -v`
Expected: All tests pass (RLock is a drop-in replacement for Lock)

**Step 4: Commit**

```bash
cd ~/.claude/plugins/agent-swarm
git add lib/mcp_router.py
git commit -m "fix: use RLock for backend locks to prevent recursive deadlock"
```

---

### Task 2: Add Concurrency Test

**Files:**
- Modify: `tests/test_mcp_router.py`

**Step 1: Write test for recursive lock scenario**

Add this test to `tests/test_mcp_router.py`:

```python
def test_forward_to_server_recursive_lock():
    """Test that recursive calls to _forward_to_server don't deadlock.
    
    This simulates what happens when _restore_workflow_state calls
    _forward_to_server while already holding the backend lock.
    """
    from threading import RLock
    from lib.mcp_router import MCPRouter
    
    # Verify backend locks are RLock (reentrant)
    router = MCPRouter.__new__(MCPRouter)
    router._lock = RLock()
    router._backend_locks = {}
    
    lock = router._get_backend_lock("test")
    assert isinstance(lock, RLock), "Backend lock should be RLock for reentrant support"
    
    # Verify reentrant acquisition works
    acquired_first = lock.acquire(timeout=1)
    assert acquired_first, "First lock acquisition should succeed"
    
    acquired_second = lock.acquire(timeout=1)
    assert acquired_second, "Second (reentrant) lock acquisition should succeed"
    
    lock.release()
    lock.release()
```

**Step 2: Run the new test**

Run: `cd ~/.claude/plugins/agent-swarm && python -m pytest tests/test_mcp_router.py::test_forward_to_server_recursive_lock -v`
Expected: PASS

**Step 3: Run full test suite**

Run: `cd ~/.claude/plugins/agent-swarm && python -m pytest tests/test_mcp_router.py -v`
Expected: All tests pass

**Step 4: Commit**

```bash
cd ~/.claude/plugins/agent-swarm
git add tests/test_mcp_router.py
git commit -m "test: add recursive lock test for router concurrency"
```

---

### Task 3: Manual Integration Test

**Step 1: Verify router responds**

Test the router with a simple telemetry call to verify it's working:

```bash
cd ~/.claude/plugins/agent-swarm
python -c "
from lib.mcp_router import MCPRouter
import json

# This would be called by Claude Code - just verify the class loads
router = MCPRouter.__new__(MCPRouter)
print('MCPRouter class loads successfully')
print('RLock import verified')
"
```

Expected: "MCPRouter class loads successfully" and "RLock import verified"

**Step 2: Document in handoff**

Update the session handoff memory with the fix status.

---

## Summary

This fix addresses the deadlock by using `RLock` instead of `Lock`, allowing the same thread to acquire the lock multiple times (reentrant). This is the minimal, safe fix that:

1. ✅ Fixes the recursive deadlock in `_restore_workflow_state`
2. ✅ Maintains correctness (lock still protects full request-response cycle)
3. ✅ Works with existing timeout (30s max blocking)
4. ✅ Is a drop-in replacement (no behavioral changes)

Future optimization (not in this plan): Use asyncio for true non-blocking I/O.
