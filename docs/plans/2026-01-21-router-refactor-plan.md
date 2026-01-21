# Router Refactor Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Break the monolithic mcp_router.py into independent services with single responsibilities, remove dead/redundant code, and eliminate file-based persistence.

**Architecture:** Thin MCPController orchestrates independent services: RoutingService (backend calls), SummarizationService (truncation + content_id), WorkflowStateService (operational data), and existing TelemetryService (DuckDB). Services don't import each other.

**Tech Stack:** Python 3.11+, DuckDB, existing MCP protocol

---

## Phase 1: Remove Dead Code

### Task 1.1: Delete mcp-summarizer.py

**Files:**
- Delete: `hooks/mcp-summarizer.py`

**Step 1: Verify file is not imported anywhere**

Run: `grep -r "mcp-summarizer\|mcp_summarizer" --include="*.py" --include="*.json" .`
Expected: No results (or only the file itself)

**Step 2: Delete the file**

```bash
rm hooks/mcp-summarizer.py
```

**Step 3: Commit**

```bash
git add -A
git commit -m "chore: delete dead mcp-summarizer.py hook"
```

---

### Task 1.2: Remove last_summary.json references

**Files:**
- Search all: `*.py`, `*.json`

**Step 1: Find all references**

Run: `grep -rn "last_summary" --include="*.py" --include="*.json" .`
Expected: List of files referencing last_summary.json

**Step 2: Remove each reference**

For each file found, remove the code that reads/writes last_summary.json.

**Step 3: Delete the file if it exists**

```bash
rm -f .state/last_summary.json
```

**Step 4: Commit**

```bash
git add -A
git commit -m "chore: remove last_summary.json file-based storage"
```

---

## Phase 2: Router Uses TelemetryService

### Task 2.1: Replace TelemetryCollector with TelemetryService

**Files:**
- Modify: `lib/mcp_router.py` (lines 51, 115-167, TelemetryCollector class)
- Reference: `lib/telemetry_service.py`

**Step 1: Read TelemetryService interface**

Understand the existing interface:
- `insert_event(event: dict)` - writes to DuckDB
- `get_summary()` - reads aggregated data
- `get_tool_breakdown()` - reads per-tool stats

**Step 2: Write adapter test**

Create: `tests/test_telemetry_integration.py`

```python
"""Test that router telemetry flows to TelemetryService."""
import pytest
from lib.telemetry_service import TelemetryService


def test_insert_event_accepts_router_format():
    """TelemetryService.insert_event accepts the event format router produces."""
    service = TelemetryService()
    event = {
        "tool": "serena__read_file",
        "server": "serena",
        "timestamp": "2026-01-21T12:00:00",
        "input_tokens": 100,
        "output_tokens": 500,
        "duration_ms": 150,
        "session_id": "test-session",
    }
    # Should not raise
    service.insert_event(event)
```

**Step 3: Run test to verify it passes (or adjust interface)**

Run: `pytest tests/test_telemetry_integration.py -v`

**Step 4: Update MCPRouter to use TelemetryService**

In `lib/mcp_router.py`:

1. Remove import of `save_telemetry_v2` (line 51)
2. Add import: `from lib.telemetry_service import TelemetryService`
3. In MCPRouter.__init__, replace TelemetryCollector with TelemetryService
4. Replace `self._telemetry.track_*` calls with `self._telemetry_service.insert_event()`

**Step 5: Run all tests**

Run: `pytest tests/ -v`
Expected: All pass

**Step 6: Commit**

```bash
git add -A
git commit -m "refactor: router uses TelemetryService instead of file-based telemetry"
```

---

### Task 2.2: Remove TelemetryCollector class

**Files:**
- Modify: `lib/mcp_router.py` (delete TelemetryCollector class, ~lines 110-200)

**Step 1: Verify TelemetryCollector is no longer used**

Run: `grep -n "TelemetryCollector" lib/mcp_router.py`
Expected: Only class definition, no instantiation

**Step 2: Delete the class**

Remove the entire TelemetryCollector class from mcp_router.py.

**Step 3: Run tests**

Run: `pytest tests/ -v`
Expected: All pass

**Step 4: Commit**

```bash
git add -A
git commit -m "refactor: remove unused TelemetryCollector class"
```

---

## Phase 3: Simplify Telemetry Hooks

### Task 3.1: Audit telemetry hooks

**Files:**
- Read: `hooks/telemetry-posttool.py`
- Read: `hooks/telemetry-pretool.py`
- Read: `hooks/telemetry-sessionstart.py`

**Step 1: Identify what each hook does**

For each hook, document:
- What data it captures
- Where it writes (file? DuckDB? workflow state?)
- Is this duplicated by router?

**Step 2: Determine which hooks are redundant**

If router now handles all telemetry via TelemetryService, hooks that write telemetry are redundant.

**Step 3: Document findings**

Add findings as comments in this plan or create a separate analysis doc.

---

### Task 3.2: Remove redundant telemetry hooks

**Files:**
- Potentially delete: `hooks/telemetry-posttool.py`
- Potentially delete: `hooks/telemetry-pretool.py`
- Modify: `hooks.json` or settings to unregister

**Step 1: Backup current behavior**

```bash
cp hooks/telemetry-posttool.py hooks/telemetry-posttool.py.bak
```

**Step 2: Remove hook registration**

Edit the hooks configuration to unregister the redundant hooks.

**Step 3: Test that telemetry still works**

Run a few tool calls and verify telemetry appears in DuckDB via dashboard.

**Step 4: Delete the hook files**

```bash
rm hooks/telemetry-posttool.py
rm hooks/telemetry-posttool.py.bak
```

**Step 5: Commit**

```bash
git add -A
git commit -m "chore: remove redundant telemetry hooks (router handles telemetry)"
```

---

## Phase 4: Content ID via Workflow State

### Task 4.1: Create WorkflowStateService

**Files:**
- Create: `lib/workflow_state_service.py`
- Test: `tests/test_workflow_state_service.py`

**Step 1: Write failing test**

Create: `tests/test_workflow_state_service.py`

```python
"""Tests for WorkflowStateService."""
import pytest
from lib.workflow_state_service import WorkflowStateService


def test_store_and_retrieve_content():
    """Can store content by ID and retrieve it."""
    service = WorkflowStateService()
    content_id = "test-123"
    content = {"data": "full response content here"}
    
    service.store_content(content_id, content)
    retrieved = service.get_content(content_id)
    
    assert retrieved == content


def test_get_content_removes_it():
    """Retrieving content removes it from storage."""
    service = WorkflowStateService()
    content_id = "test-456"
    content = {"data": "one-time content"}
    
    service.store_content(content_id, content)
    service.get_content(content_id)
    
    # Second retrieval should return None
    assert service.get_content(content_id) is None
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_workflow_state_service.py -v`
Expected: FAIL with "cannot import"

**Step 3: Implement WorkflowStateService**

Create: `lib/workflow_state_service.py`

```python
"""Service for managing workflow state and content_id storage.

Uses the workflow MCP contract for persistence.
"""
from typing import Any


class WorkflowStateService:
    """Manages operational data for hooks and agents.
    
    Responsibilities:
    - Store/retrieve content_id -> full content mapping
    - Manage operational data accessible via workflow MCP contract
    """
    
    def __init__(self):
        self._content_store: dict[str, Any] = {}
    
    def store_content(self, content_id: str, content: Any) -> None:
        """Store full content for later retrieval."""
        self._content_store[content_id] = content
    
    def get_content(self, content_id: str) -> Any | None:
        """Retrieve and remove content by ID.
        
        Returns None if content_id not found.
        Content is removed after retrieval (one-time access).
        """
        return self._content_store.pop(content_id, None)
    
    def has_content(self, content_id: str) -> bool:
        """Check if content exists for given ID."""
        return content_id in self._content_store
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_workflow_state_service.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add lib/workflow_state_service.py tests/test_workflow_state_service.py
git commit -m "feat: add WorkflowStateService for content_id storage"
```

---

### Task 4.2: Wire SummarizationService to WorkflowStateService

**Files:**
- Create: `lib/summarization_service.py`
- Test: `tests/test_summarization_service.py`

**Step 1: Write failing test**

Create: `tests/test_summarization_service.py`

```python
"""Tests for SummarizationService."""
import pytest
from lib.summarization_service import SummarizationService
from lib.workflow_state_service import WorkflowStateService


def test_large_content_is_summarized():
    """Content over threshold returns summary with content_id."""
    workflow_state = WorkflowStateService()
    service = SummarizationService(workflow_state, threshold=100)
    
    large_content = "x" * 500  # Over threshold
    result = service.process(large_content)
    
    assert "summary" in result
    assert "content_id" in result
    assert result["full_available"] is True
    assert len(result["summary"]) < len(large_content)


def test_small_content_passes_through():
    """Content under threshold passes through unchanged."""
    workflow_state = WorkflowStateService()
    service = SummarizationService(workflow_state, threshold=100)
    
    small_content = "small response"
    result = service.process(small_content)
    
    assert result == small_content


def test_content_retrievable_via_workflow_state():
    """Full content stored in workflow state is retrievable."""
    workflow_state = WorkflowStateService()
    service = SummarizationService(workflow_state, threshold=100)
    
    large_content = "x" * 500
    result = service.process(large_content)
    
    content_id = result["content_id"]
    retrieved = workflow_state.get_content(content_id)
    
    assert retrieved == large_content
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_summarization_service.py -v`
Expected: FAIL with "cannot import"

**Step 3: Implement SummarizationService**

Create: `lib/summarization_service.py`

```python
"""Service for summarizing large responses.

Stores full content in WorkflowStateService for later retrieval.
"""
import uuid
from typing import Any

from lib.workflow_state_service import WorkflowStateService


class SummarizationService:
    """Handles response summarization and content storage.
    
    Responsibilities:
    - Determine if response needs summarization
    - Generate summaries for large responses
    - Store full content via WorkflowStateService
    """
    
    def __init__(self, workflow_state: WorkflowStateService, threshold: int = 2000):
        self._workflow_state = workflow_state
        self._threshold = threshold
    
    def process(self, content: Any) -> Any:
        """Process content, summarizing if over threshold.
        
        Returns:
            Original content if under threshold, or
            {summary, content_id, full_available} if over threshold
        """
        content_str = str(content) if not isinstance(content, str) else content
        
        if len(content_str) <= self._threshold:
            return content
        
        content_id = self._generate_content_id()
        self._workflow_state.store_content(content_id, content)
        
        summary = self._generate_summary(content_str)
        
        return {
            "summary": summary,
            "content_id": content_id,
            "full_available": True,
        }
    
    def _generate_content_id(self) -> str:
        """Generate unique content ID."""
        return f"c{uuid.uuid4().hex[:12]}"
    
    def _generate_summary(self, content: str) -> str:
        """Generate summary of content.
        
        TODO: Use LLM summarization. For now, truncate.
        """
        return content[:self._threshold] + "..."
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_summarization_service.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add lib/summarization_service.py tests/test_summarization_service.py
git commit -m "feat: add SummarizationService with WorkflowStateService integration"
```

---

## Phase 5: Extract RoutingService

### Task 5.1: Create RoutingService

**Files:**
- Create: `lib/routing_service.py`
- Test: `tests/test_routing_service.py`

**Step 1: Identify routing code in MCPRouter**

Key methods to extract:
- `_get_backend_lock`
- `_get_connection`
- `_forward_to_server`
- `register_server`
- `unregister_server`
- `list_servers`

**Step 2: Write failing test**

Create: `tests/test_routing_service.py`

```python
"""Tests for RoutingService."""
import pytest
from lib.routing_service import RoutingService


def test_register_server():
    """Can register a server."""
    service = RoutingService()
    service.register_server("test", {"command": "echo"})
    
    assert "test" in service.list_servers()


def test_unregister_server():
    """Can unregister a server."""
    service = RoutingService()
    service.register_server("test", {"command": "echo"})
    service.unregister_server("test")
    
    assert "test" not in service.list_servers()
```

**Step 3: Extract RoutingService from MCPRouter**

Create: `lib/routing_service.py`

Extract the routing-specific methods from MCPRouter into this new class.

**Step 4: Run tests**

Run: `pytest tests/test_routing_service.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add lib/routing_service.py tests/test_routing_service.py
git commit -m "feat: extract RoutingService from MCPRouter"
```

---

## Phase 6: Create MCPController

### Task 6.1: Create thin MCPController

**Files:**
- Create: `lib/mcp_controller.py`
- Test: `tests/test_mcp_controller.py`

**Step 1: Write integration test**

Create: `tests/test_mcp_controller.py`

```python
"""Tests for MCPController orchestration."""
import pytest
from lib.mcp_controller import MCPController


def test_controller_wires_services():
    """Controller orchestrates route -> summarize -> telemetry -> return."""
    controller = MCPController()
    
    # Mock a simple tool call
    result = controller.handle_call("test__echo", {"message": "hello"})
    
    # Should return a result (details depend on implementation)
    assert result is not None
```

**Step 2: Implement MCPController**

Create: `lib/mcp_controller.py`

```python
"""Thin controller that orchestrates MCP tool calls.

Wires together:
- RoutingService: routes calls to backend servers
- SummarizationService: summarizes large responses
- TelemetryService: records events
- WorkflowStateService: manages content_id storage
"""
from lib.routing_service import RoutingService
from lib.summarization_service import SummarizationService
from lib.telemetry_service import TelemetryService
from lib.workflow_state_service import WorkflowStateService


class MCPController:
    """Thin orchestration layer for MCP tool calls.
    
    No business logic - just wiring services together.
    """
    
    def __init__(self):
        self._workflow_state = WorkflowStateService()
        self._routing = RoutingService()
        self._summarization = SummarizationService(self._workflow_state)
        self._telemetry = TelemetryService()
    
    def handle_call(self, tool: str, args: dict) -> dict:
        """Handle an MCP tool call.
        
        Flow: route -> summarize -> record -> return
        """
        # Check for content_id retrieval (two-step)
        if "content_id" in args:
            return self._retrieve_full_content(args["content_id"])
        
        # Route to backend
        result = self._routing.route(tool, args)
        
        # Summarize if needed
        processed = self._summarization.process(result)
        
        # Record telemetry
        self._telemetry.insert_event({
            "tool": tool,
            "args": args,
            "result_size": len(str(result)),
        })
        
        return processed
    
    def _retrieve_full_content(self, content_id: str) -> dict:
        """Retrieve full content for two-step retrieval."""
        content = self._workflow_state.get_content(content_id)
        if content is None:
            return {"error": f"Content not found: {content_id}"}
        return {"content": content}
```

**Step 3: Run tests**

Run: `pytest tests/test_mcp_controller.py -v`

**Step 4: Commit**

```bash
git add lib/mcp_controller.py tests/test_mcp_controller.py
git commit -m "feat: add MCPController as thin orchestration layer"
```

---

## Phase 7: Deprecate mcp_router.py

### Task 7.1: Update entry points to use MCPController

**Files:**
- Modify: Entry point scripts that import MCPRouter
- Modify: `lib/__init__.py` if applicable

**Step 1: Find all MCPRouter imports**

Run: `grep -rn "from.*mcp_router import\|import.*mcp_router" --include="*.py" .`

**Step 2: Update each import to use MCPController**

Replace MCPRouter with MCPController at each location.

**Step 3: Run all tests**

Run: `pytest tests/ -v`
Expected: All pass

**Step 4: Commit**

```bash
git add -A
git commit -m "refactor: update entry points to use MCPController"
```

---

### Task 7.2: Remove mcp_router.py

**Files:**
- Delete: `lib/mcp_router.py`

**Step 1: Verify no remaining imports**

Run: `grep -rn "mcp_router" --include="*.py" .`
Expected: No results

**Step 2: Delete the file**

```bash
rm lib/mcp_router.py
```

**Step 3: Run all tests**

Run: `pytest tests/ -v`
Expected: All pass

**Step 4: Commit**

```bash
git add -A
git commit -m "refactor: remove deprecated mcp_router.py"
```

---

## Verification Checklist

After completing all phases:

- [ ] `mcp-summarizer.py` deleted
- [ ] `last_summary.json` references removed
- [ ] Router uses TelemetryService (no file-based telemetry)
- [ ] TelemetryCollector class removed
- [ ] Redundant telemetry hooks removed
- [ ] WorkflowStateService created and tested
- [ ] SummarizationService created and tested
- [ ] RoutingService extracted and tested
- [ ] MCPController created as thin orchestration
- [ ] mcp_router.py deprecated and removed
- [ ] All tests pass
- [ ] Dashboard still shows telemetry data
