# Task Queue Orchestrator Design

**Date:** 2026-01-23
**Status:** Design (Updated)
**Related:** iterate workflow, adversary agent, LOGOS monorepo

---

## Overview

Build a general-purpose orchestrator that accepts various input types (JSON queues, lists, specs), manages tasks through the iterate TDD workflow, and uses adversarial verification to ensure quality.

**Core principle:** Autonomous execution with adversarial review gates.

---

## 1. Problem Statement

The LOGOS ecosystem has 5 repos (apollo, sophia, hermes, talos, logos) with task queues defined in JSON files. These tasks have:
- Dependencies (`blockedBy`/`blocks`) - can cross repos
- Groupings for PR batching (`group` = repo)
- Priority levels (critical, high, medium, low)
- Detailed prompts for implementation

**Goal:** Automatically execute these tasks through the iterate TDD workflow with quality gates.

---

## 2. Architecture

### Components

| Component | Purpose | Location |
|-----------|---------|----------|
| Input Adapters | Accept JSON/list/spec/intake inputs | `lib/input_adapters.py` (new) |
| Queue Loader | Merge inputs into unified TaskQueue | `lib/task_queue_loader.py` (new) |
| Orchestrator | Pick runnable tasks, spawn subagents | iterate ORCHESTRATE phase |
| Implementer | TDD cycle with phase-specific context | `agents/implementer.md` + `hooks/subagent-enforcement.py` |
| Adversary | Deep verification at PR group level | `agents/adversary.md` + `lib/adversary_gate.py` |
| Gated Push | Defer push until group complete + adversary pass | `scripts/iterate_state.py` |
| Output Manager | Verbosity-controlled progress output | `lib/output_manager.py` (new) |

### Data Flow

```
┌─────────────────────────────────────────────────────────────────────┐
│                         INPUT LAYER                                  │
│  JSON files ─┐                                                      │
│  List files ─┼─→ InputAdapter → Unified TaskQueue                   │
│  Spec files ─┤                                                      │
│  Intake ─────┘                                                      │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                         ORCHESTRATOR                                 │
│  1. Validate dependencies (flag orphans, warn, continue)            │
│  2. Find runnable (blockedBy satisfied, status=pending)             │
│  3. Grab up to max_agents runnable tasks                            │
│  4. Spawn implementers with prompt + repo cwd instruction           │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    IMPLEMENTER (TDD cycle)                           │
│  cd /home/fearsidhe/projects/LOGOS/{repo}                           │
│  TEST_WRITING → IMPLEMENT → TEST → REVIEW                           │
│  (phase-specific context injected at each transition)               │
│  On REVIEW:                                                         │
│    branch → commit → if last in group: adversary → gated push       │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    ADVERSARY (PR group verification)                 │
│  Spawned by implementer when last task in group completes           │
│  Deep analysis:                                                     │
│    - Test quality (meaningful assertions, not just coverage)        │
│    - Code quality (patterns, maintainability)                       │
│    - Tests actually testing what they claim                         │
│    - Non-obvious issues (race conditions, edge cases)               │
│  Verdict: WEAK → kickback specific tasks | SOLID → approve push     │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    COMPLETION                                        │
│  - Mark task done in queue                                          │
│  - Unblock dependents (including cross-repo)                        │
│  - On failure: retry_or_escalate (max 3 attempts)                   │
│  - Loop to next runnable task                                       │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 3. Input Adapters

### Purpose
Accept various input types and normalize to unified TaskQueue.

### Interface

```python
# lib/input_adapters.py

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

@dataclass
class InputSource:
    """Describes where input comes from."""
    type: str  # "json", "spec", "list", "intake"
    path: Optional[str] = None
    content: Optional[list[str]] = None
    options: dict = None

class InputAdapter(ABC):
    @abstractmethod
    def can_handle(self, source: InputSource) -> bool:
        pass

    @abstractmethod
    def load(self, source: InputSource) -> TaskQueue:
        pass

class JsonQueueAdapter(InputAdapter):
    """Load from JSON task queue files."""
    pass

class ListAdapter(InputAdapter):
    """Convert simple list to tasks.

    - Each list file → its own group (matching target repo)
    - Inline tasks → single default group
    - Sort by priority if present, else insertion order
    """
    pass

class SpecAdapter(InputAdapter):
    """Derive tasks from spec/design doc."""
    pass

class IntakeAdapter(InputAdapter):
    """Run intake phase to generate tasks."""
    pass

ADAPTERS = [JsonQueueAdapter(), ListAdapter(), SpecAdapter(), IntakeAdapter()]

def load_input(source: InputSource) -> TaskQueue:
    for adapter in ADAPTERS:
        if adapter.can_handle(source):
            return adapter.load(source)
    raise ValueError(f"No adapter for: {source.type}")
```

### CLI Integration

```bash
# From JSON queue files
python3 orchestrate.py --json /path/to/queue.json

# From list file
python3 orchestrate.py --list tasks.txt

# Inline tasks
python3 orchestrate.py --tasks "Add auth" "Fix login" "Write tests"

# From spec
python3 orchestrate.py --spec design.md

# Run intake first
python3 orchestrate.py --intake
```

---

## 4. Task Queue Schema

Each task in the JSON files:

```json
{
  "id": "logos-340",
  "repo": "logos",
  "issue_number": 340,
  "title": "Add OpenTelemetry SDK Integration",
  "priority": "critical",
  "type": "feature",
  "group": "logos",
  "blockedBy": ["sophia-123"],
  "blocks": ["apollo-456"],
  "status": "pending",
  "pr": null,
  "prompt": "Implement OpenTelemetry SDK integration..."
}
```

**Key fields:**
- `group` → repo name, determines PR (one PR per repo)
- `blockedBy` → task IDs that must complete first (can cross repos)
- `prompt` → detailed implementation instructions for subagent
- `repo` → determines working directory

**Cross-repo dependencies:** Tasks in different repos can have dependencies (e.g., sophia API before apollo UI). Group determines PR, not dependency scope.

---

## 5. Dependency Validation

### On Load

```python
def validate_dependencies(queue: TaskQueue) -> list[str]:
    """Validate dependencies, flag issues.

    Returns list of warnings. Does not fail - flags and continues.
    """
    warnings = []
    flagged_tasks = set()

    for task in queue.tasks.values():
        for blocker_id in task.blocked_by:
            if not queue.get_task(blocker_id):
                # Orphan reference
                warnings.append(f"Task {task.id} references non-existent blocker {blocker_id}")
                flagged_tasks.add(task.id)
                task.metadata["flagged"] = True
                task.metadata["flag_reason"] = f"Orphan blocker: {blocker_id}"

    # Flag dependents of flagged tasks
    for task in queue.tasks.values():
        for blocker_id in task.blocked_by:
            if blocker_id in flagged_tasks:
                flagged_tasks.add(task.id)
                task.metadata["flagged"] = True
                task.metadata["flag_reason"] = f"Depends on flagged task: {blocker_id}"

    return warnings
```

**Behavior:**
- Orphan references → flag task + dependents, warn, continue with valid tasks
- Cycles → trust input (prevent at document creation time)
- If flagged tasks prevent meaningful progress → stop and report

---

## 6. Retry Logic (Implemented)

### Location
`scripts/iterate_state.py` - `TaskQueue.retry_or_escalate()`

### Behavior

```python
def retry_or_escalate(self, task_id: str, error: str, max_retries: int = 3) -> bool:
    """Retry a failed task or escalate if max retries exceeded.

    - Tracks retry count in metadata["retry_count"]
    - Logs all errors in metadata["errors"] array
    - Under max retries → reset to PENDING (new agent picks it up)
    - At max retries → mark FAILED, print escalation message

    Returns True if will retry, False if escalated.
    """
```

**Flow:**
1. Agent fails/killed → agent_recovery detects
2. Orchestrator calls `retry_or_escalate(task_id, error)`
3. Task resets to PENDING → new agent picks it up
4. Agents detect already-completed phases (stateless/resumable)
5. After 3 failures → escalate, stop for reevaluation

---

## 7. Progress Output

### Verbosity Levels

| Level | Shows |
|-------|-------|
| **Normal** | Phase transitions, task completions, errors, queue summary |
| **Verbose** | + Agent spawns, tool usage, state changes, timing, full queue |

### Implementation

```python
# lib/output_manager.py

import os
import sys

VERBOSE = os.environ.get("ORCHESTRATE_VERBOSE", "0") == "1"

def output(msg: str, level: str = "normal", category: str = "general"):
    """Unified output with verbosity control.

    level: "normal" | "verbose"
    category: "phase" | "queue" | "agent" | "error"
    """
    if level == "verbose" and not VERBOSE:
        return

    prefix = {
        "phase": "[PHASE]",
        "queue": "[QUEUE]",
        "agent": "[AGENT]",
        "error": "[ERROR]",
        "general": "[INFO]",
    }.get(category, "[INFO]")

    print(f"{prefix} {msg}", file=sys.stderr)
```

### Control

```bash
# Normal output
python3 orchestrate.py --json queue.json

# Verbose output
ORCHESTRATE_VERBOSE=1 python3 orchestrate.py --json queue.json

# Or CLI flag
python3 orchestrate.py --json queue.json --verbose
```

---

## 8. Adversarial Verification

### When
Part of REVIEW phase. Implementer spawns adversary when it's the last task in the group.

### Flow

```
REVIEW phase (implementer):
1. Branch, commit
2. Check if last task in group
3. If yes:
   └── Spawn adversary agent
   └── Wait for result (TaskOutput)
   └── Pass → gated push
   └── Fail → report "needs rework"
4. If not last:
   └── Commit only, no push yet
```

### Adversary Deep Analysis

The adversary agent does more than coverage metrics:

- **Test quality** - Meaningful assertions, not just line coverage
- **Code quality** - Patterns, readability, maintainability
- **Test validity** - Tests actually testing what they claim
- **Non-obvious issues** - Race conditions, edge cases, security
- **Specificity** - Would tests catch only this bug or unrelated issues?

### Verdict

| Verdict | Confidence | Action |
|---------|------------|--------|
| SOLID | ≥70% | Approve, trigger gated push |
| STRENGTHENED | 60-70% | Approve with note |
| WEAK | <60% | Kickback specific tasks, identify issues |

On kickback, adversary identifies which tasks need rework. Those tasks go through `retry_or_escalate()`.

---

## 9. Parallel Task Selection

### Approach
Simple: grab all runnable tasks up to max_agents.

```python
def get_runnable_tasks(queue: TaskQueue, limit: int = 5) -> list[Task]:
    """Get tasks ready to run (pending + all blockers completed)."""
    runnable = []
    for task in queue.get_pending():
        if task.metadata.get("flagged"):
            continue  # Skip flagged tasks

        blockers_done = all(
            queue.get_task(b).status == TaskStatus.COMPLETED
            for b in task.blocked_by
            if queue.get_task(b)
        )
        if blockers_done:
            runnable.append(task)

    # Sort by priority
    priority_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    runnable.sort(key=lambda t: priority_order.get(t.priority, 99))

    return runnable[:limit]
```

Cross-repo dependencies are naturally respected - a task is only runnable when ALL its blockers (regardless of repo) are complete.

---

## 10. Git Workflow (REVIEW Phase)

### Injected Context

When implementer enters REVIEW phase:

```markdown
## REVIEW PHASE

**Group:** {group}
**Branch:** feature/{group}

### 1. Check/create branch
```bash
git branch --list "feature/{group}" || git checkout -b "feature/{group}"
```

### 2. Create PR if first task in group
```bash
gh pr list --head "feature/{group}" --json number --jq '.[0].number'
# If no PR:
gh pr create --title "{group}" --body "Implementation tasks" --draft
```

### 3. Commit changes
```bash
git add -A
git commit -m "{task_desc}"
```

### 4. Check if last task in group
If yes → spawn adversary, wait for verdict

### 5. On adversary pass → Gated push
```bash
python3 scripts/iterate_state.py push --pr={group}
```

### 6. Record and advance
```bash
python3 lib/iterate_workflow.py review 1
python3 lib/iterate_workflow.py advance
```
```

---

## 11. State Management

### Workflow State (in-memory via MCP router)

```python
workflow_set_state("iterate", {
    "phase": "orchestrate",
    "mode": "iterate-tdd",
    "current_group": "logos",
    ...
})

workflow_set_state("queue", {
    "tasks": {...},
    "prs": {...},
    "completed": [...],
    "failed": [...],
    "flagged": [...]
})
```

### Persistence

- Queue state persisted via workflow_client MCP calls
- Resumable on restart by re-reading queue state
- Orchestrator survives compaction

---

## 12. Implementation Plan

### Phase 1: Input Adapters
- [ ] Create `lib/input_adapters.py`
- [ ] Implement JsonQueueAdapter
- [ ] Implement ListAdapter
- [ ] Add CLI flags to orchestrate.py
- [ ] Add tests

### Phase 2: Queue Loader + Validation
- [ ] Create `lib/task_queue_loader.py`
- [ ] Implement dependency validation (flag orphans)
- [ ] Implement cross-repo dependency support
- [ ] Add tests

### Phase 3: Output Manager
- [ ] Create `lib/output_manager.py`
- [ ] Wire into orchestrate.py and iterate_workflow.py
- [ ] Add ORCHESTRATE_VERBOSE env var support
- [ ] Add --verbose CLI flag

### Phase 4: Adversary Integration
- [ ] Update REVIEW phase context to include adversary spawn logic
- [ ] Add "last task in group" detection
- [ ] Wire adversary verdict handling
- [ ] Add kickback logic for WEAK verdict

### Phase 5: Testing
- [ ] Run on 3-5 test tasks across repos
- [ ] Monitor full flow: load → implement → adversary → push
- [ ] Verify cross-repo dependencies work
- [ ] Verify retry logic on failures

### Phase 6: Scale
- [ ] Enrich prompts for remaining tasks
- [ ] Run full 75-task queue
- [ ] Monitor and iterate

---

## 13. Success Criteria

1. **Multiple input types accepted** — JSON, list, spec all work
2. **Queue loads correctly** — All tasks merged, orphans flagged
3. **Cross-repo deps work** — sophia blocks apollo correctly
4. **Subagents execute in correct repo** — cwd instruction followed
5. **Phase context injected** — Agents receive phase-specific instructions
6. **Adversary catches issues** — Deep analysis at PR group level
7. **Gated push works** — PRs only pushed when group complete + adversary pass
8. **Retry logic works** — Failed tasks retry, escalate after 3
9. **Output is usable** — Normal mode informative, verbose mode detailed

---

## 14. Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| Agent ignores cwd instruction | Add hook to verify cwd before file ops |
| Adversary too strict | Tune threshold, add override, improve prompts |
| Cross-repo deps cause deadlock | Validate at load time, flag issues |
| Context explosion in orchestrator | Use non-blocking TaskOutput polling |
| Infinite kickback loops | Max 3 retries via retry_or_escalate() |
| Output too noisy | Verbosity levels, centralized output function |

---

## Appendix: Existing Infrastructure

| Component | Location | Purpose |
|-----------|----------|---------|
| TaskQueue | `scripts/iterate_state.py` | Queue data structure with PR grouping |
| retry_or_escalate | `scripts/iterate_state.py` | Retry logic with escalation (added) |
| cmd_gated_push | `scripts/iterate_state.py` | Batched push when group complete |
| AdversaryGate | `lib/adversary_gate.py` | Confidence scoring and thresholds |
| adversary.md | `agents/adversary.md` | Adversary agent definition |
| agent_recovery.py | `lib/agent_recovery.py` | Detect/handle failed agents |
| subagent-enforcement.py | `hooks/subagent-enforcement.py` | Phase context injection |
| workflow_client | `lib/workflow_client.py` | MCP state management |
| prompt_templates.py | `lib/prompt_templates.py` | Exploration/implementer prompts |
| orchestrate.py | `lib/orchestrate.py` | Orchestration loop with review polling |
