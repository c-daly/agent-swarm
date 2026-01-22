# Workflow Abstraction Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Create a reusable workflow framework that debug, PR comment, and iterate workflows all inherit from, with adversarial gates and test confidence scoring.

**Architecture:** Extract common workflow patterns (phases, tool restrictions, kick-backs, adversary gates) into a base library. Each workflow defines its phases declaratively; the framework handles state management, enforcement, and transitions. Adversary runs in parallel where possible.

**Tech Stack:** Python 3.10+, dataclasses, enums, workflow_client.py for state, hooks for enforcement

---

## Workflow Contract

All workflows must adhere to a general contract for state manager compatibility. This is a minimal contract that enables:
- Unified state querying across workflow types
- Generic enforcement hooks
- Cross-workflow tooling (e.g., status dashboards)

### Required State Fields

```python
@dataclass
class WorkflowStateContract:
    """Minimal contract all workflows must implement."""

    # Identity
    workflow_type: str          # "debug", "pr_comment", "iterate"
    workflow_id: str            # Unique instance ID

    # Lifecycle
    active: bool                # Is workflow currently running?
    phase: str                  # Current phase name

    # Tracking
    task: str                   # What is being worked on
    iteration: int              # Kick-back count
    max_iterations: int         # Limit before escalation

    # Exit
    exit_reason: Optional[str]  # Why workflow ended (if inactive)
```

### Contract Enforcement

The `WorkflowEngine.start()` method ensures all required fields are present:

```python
def start(self, task: str, **kwargs) -> dict:
    state = {
        "workflow_type": self.definition.name,  # REQUIRED
        "workflow_id": self.workflow_id,         # REQUIRED
        "active": True,                          # REQUIRED
        "phase": self.definition.initial_phase,  # REQUIRED
        "task": task,                            # REQUIRED
        "iteration": 0,                          # REQUIRED
        "max_iterations": self.definition.max_iterations,  # REQUIRED
        **kwargs,  # Workflow-specific fields
    }
    workflow_client.workflow_set_state(self.workflow_id, state)
    return state
```

### Workflow-Specific Extensions

Each workflow adds its own fields beyond the contract:

| Workflow | Additional Fields |
|----------|-------------------|
| debug | `severity`, `hypothesis`, `prediction`, `proof` |
| pr_comment | `pr_number`, `articulation`, `comment` |
| iterate | `queue`, `workers`, `test_results`, `coverage` |

---

## Phase 1: Workflow Base Library

### Task 1.1: Create workflow_base.py - Phase and Transition Model

**Files:**
- Create: `lib/workflow_base.py`
- Test: `tests/lib/test_workflow_base.py`

**Step 1: Write the failing test**

```python
# tests/lib/test_workflow_base.py
import pytest
from lib.workflow_base import (
    WorkflowPhase, PhaseTransition, WorkflowDefinition,
    TransitionResult, KickbackReason
)

def test_phase_definition():
    """Phase should define allowed/blocked tools."""
    phase = WorkflowPhase(
        name="investigate",
        allowed_tools=frozenset({"Read", "Glob", "Grep"}),
        blocked_tools=frozenset({"Edit", "Write"}),
        required_outputs=["hypothesis", "prediction"],
        adversary_gate=True,
    )
    assert phase.name == "investigate"
    assert "Read" in phase.allowed_tools
    assert "Edit" in phase.blocked_tools
    assert phase.adversary_gate is True


def test_workflow_definition():
    """Workflow should define phases and transitions."""
    phases = {
        "start": WorkflowPhase(name="start", allowed_tools=frozenset({"Read"})),
        "end": WorkflowPhase(name="end", allowed_tools=frozenset({"Read"})),
    }
    transitions = {
        "start": PhaseTransition(
            from_phase="start",
            to_phase="end",
            condition=lambda state: state.get("ready", False),
        ),
    }
    workflow = WorkflowDefinition(
        name="test_workflow",
        phases=phases,
        transitions=transitions,
        initial_phase="start",
    )
    assert workflow.name == "test_workflow"
    assert workflow.initial_phase == "start"


def test_transition_with_kickback():
    """Transitions should support kickback logic."""
    def check_result(state):
        if not state.get("tests_pass"):
            return TransitionResult(
                success=False,
                kickback_to="fix",
                reason=KickbackReason.TESTS_FAILED
            )
        return TransitionResult(success=True, next_phase="done")
    
    state = {"tests_pass": False}
    result = check_result(state)
    assert result.success is False
    assert result.kickback_to == "fix"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/lib/test_workflow_base.py -v`
Expected: FAIL with "No module named 'lib.workflow_base'"

**Step 3: Write minimal implementation**

```python
# lib/workflow_base.py
"""Base classes for workflow state machines.

All workflows (debug, PR comment, iterate) inherit from this base.
Provides:
- Phase definitions with tool restrictions
- Transition logic with kickback support
- State management via workflow_client
- Adversary gate integration points
"""

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Callable, FrozenSet, Optional, Any
import workflow_client


class KickbackReason(Enum):
    """Standard reasons for phase kickback."""
    TESTS_FAILED = auto()
    LINT_FAILED = auto()
    COVERAGE_LOW = auto()
    ADVERSARY_REJECTED = auto()
    VERIFICATION_FAILED = auto()
    NEW_COMMENTS = auto()
    CI_FAILED = auto()
    CANNOT_REPRODUCE = auto()
    PREDICTION_NOT_CONFIRMED = auto()
    MAX_ITERATIONS = auto()


@dataclass(frozen=True)
class WorkflowPhase:
    """Definition of a workflow phase."""
    name: str
    allowed_tools: FrozenSet[str] = field(default_factory=frozenset)
    blocked_tools: FrozenSet[str] = field(default_factory=frozenset)
    allowed_file_patterns: FrozenSet[str] = field(default_factory=frozenset)
    required_outputs: list[str] = field(default_factory=list)
    adversary_gate: bool = False
    requires_verification: bool = False


@dataclass
class TransitionResult:
    """Result of attempting a phase transition."""
    success: bool
    next_phase: Optional[str] = None
    kickback_to: Optional[str] = None
    reason: Optional[KickbackReason] = None
    message: str = ""


@dataclass
class PhaseTransition:
    """Definition of a transition between phases."""
    from_phase: str
    to_phase: str
    condition: Optional[Callable[[dict], TransitionResult]] = None
    kickback_map: dict[KickbackReason, str] = field(default_factory=dict)


@dataclass
class WorkflowDefinition:
    """Complete definition of a workflow."""
    name: str
    phases: dict[str, WorkflowPhase]
    transitions: dict[str, PhaseTransition]
    initial_phase: str
    max_iterations: int = 5
    
    def get_phase(self, name: str) -> Optional[WorkflowPhase]:
        """Get phase by name."""
        return self.phases.get(name)
    
    def get_transition(self, from_phase: str) -> Optional[PhaseTransition]:
        """Get transition from a phase."""
        return self.transitions.get(from_phase)
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/lib/test_workflow_base.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add lib/workflow_base.py tests/lib/test_workflow_base.py
git commit -m "feat: add workflow base classes for phase and transition model"
```

---

### Task 1.2: Add WorkflowEngine - State Machine Executor

**Files:**
- Modify: `lib/workflow_base.py`
- Test: `tests/lib/test_workflow_base.py`

**Step 1: Write the failing test**

```python
# Add to tests/lib/test_workflow_base.py

def test_workflow_engine_start():
    """Engine should start workflow in initial phase."""
    from lib.workflow_base import WorkflowEngine, WorkflowDefinition, WorkflowPhase
    
    phases = {
        "triage": WorkflowPhase(name="triage", allowed_tools=frozenset({"Read"})),
        "done": WorkflowPhase(name="done", allowed_tools=frozenset()),
    }
    definition = WorkflowDefinition(
        name="test",
        phases=phases,
        transitions={},
        initial_phase="triage",
    )
    
    engine = WorkflowEngine(definition)
    state = engine.start(task="Fix the bug")
    
    assert state["active"] is True
    assert state["phase"] == "triage"
    assert state["task"] == "Fix the bug"
    assert state["iteration"] == 0


def test_workflow_engine_is_tool_allowed():
    """Engine should enforce tool restrictions."""
    from lib.workflow_base import WorkflowEngine, WorkflowDefinition, WorkflowPhase
    
    phases = {
        "investigate": WorkflowPhase(
            name="investigate",
            allowed_tools=frozenset({"Read", "Glob"}),
            blocked_tools=frozenset({"Edit", "Write"}),
        ),
    }
    definition = WorkflowDefinition(
        name="test",
        phases=phases,
        transitions={},
        initial_phase="investigate",
    )
    
    engine = WorkflowEngine(definition)
    engine.start(task="Test")
    
    allowed, reason = engine.is_tool_allowed("Read")
    assert allowed is True
    
    allowed, reason = engine.is_tool_allowed("Edit")
    assert allowed is False
    assert "blocked" in reason.lower()


def test_workflow_engine_advance_phase():
    """Engine should advance through phases."""
    from lib.workflow_base import (
        WorkflowEngine, WorkflowDefinition, WorkflowPhase,
        PhaseTransition, TransitionResult
    )
    
    phases = {
        "start": WorkflowPhase(name="start"),
        "middle": WorkflowPhase(name="middle"),
        "end": WorkflowPhase(name="end"),
    }
    transitions = {
        "start": PhaseTransition(
            from_phase="start",
            to_phase="middle",
            condition=lambda s: TransitionResult(success=True, next_phase="middle"),
        ),
        "middle": PhaseTransition(
            from_phase="middle",
            to_phase="end",
            condition=lambda s: TransitionResult(success=True, next_phase="end"),
        ),
    }
    definition = WorkflowDefinition(
        name="test",
        phases=phases,
        transitions=transitions,
        initial_phase="start",
    )
    
    engine = WorkflowEngine(definition)
    engine.start(task="Test")
    
    result = engine.advance()
    assert result.success is True
    assert engine.get_phase() == "middle"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/lib/test_workflow_base.py::test_workflow_engine_start -v`
Expected: FAIL with "cannot import name 'WorkflowEngine'"

**Step 3: Write minimal implementation**

```python
# Add to lib/workflow_base.py

class WorkflowEngine:
    """Executes a workflow definition as a state machine.
    
    Handles:
    - State persistence via workflow_client
    - Phase transitions with kickback logic
    - Tool restriction enforcement
    - Iteration counting
    """
    
    def __init__(self, definition: WorkflowDefinition, workflow_id: Optional[str] = None):
        self.definition = definition
        self.workflow_id = workflow_id or definition.name
    
    def start(self, task: str, **initial_state) -> dict:
        """Start the workflow."""
        state = {
            "active": True,
            "task": task,
            "phase": self.definition.initial_phase,
            "iteration": 0,
            "max_iterations": self.definition.max_iterations,
            "workflow_type": self.definition.name,
            **initial_state,
        }
        workflow_client.workflow_set_state(self.workflow_id, state)
        return state
    
    def get_state(self) -> Optional[dict]:
        """Get current workflow state."""
        return workflow_client.workflow_get_state(self.workflow_id)
    
    def get_phase(self) -> Optional[str]:
        """Get current phase name."""
        state = self.get_state()
        return state.get("phase") if state else None
    
    def is_active(self) -> bool:
        """Check if workflow is active."""
        state = self.get_state()
        return state.get("active", False) if state else False
    
    def is_tool_allowed(self, tool_name: str, command: Optional[str] = None) -> tuple[bool, str]:
        """Check if tool is allowed in current phase."""
        state = self.get_state()
        if not state or not state.get("active"):
            return True, "No active workflow"
        
        phase_name = state.get("phase")
        phase = self.definition.get_phase(phase_name)
        if not phase:
            return True, f"Unknown phase: {phase_name}"
        
        # Check blocked list first
        if tool_name in phase.blocked_tools:
            return False, f"[BLOCKED] {tool_name} not allowed in {phase_name} phase"
        
        # If allowed_tools is non-empty, tool must be in it
        if phase.allowed_tools and tool_name not in phase.allowed_tools:
            return False, f"[BLOCKED] {tool_name} not in allowed tools for {phase_name}"
        
        return True, ""
    
    def advance(self) -> TransitionResult:
        """Attempt to advance to next phase."""
        state = self.get_state()
        if not state or not state.get("active"):
            return TransitionResult(success=False, message="Workflow not active")
        
        current_phase = state.get("phase")
        transition = self.definition.get_transition(current_phase)
        
        if not transition:
            return TransitionResult(success=False, message=f"No transition from {current_phase}")
        
        # Evaluate transition condition
        if transition.condition:
            result = transition.condition(state)
        else:
            result = TransitionResult(success=True, next_phase=transition.to_phase)
        
        if result.success and result.next_phase:
            state["phase"] = result.next_phase
            workflow_client.workflow_set_state(self.workflow_id, state)
        elif result.kickback_to:
            state["phase"] = result.kickback_to
            state["iteration"] = state.get("iteration", 0) + 1
            if state["iteration"] >= state.get("max_iterations", 5):
                state["active"] = False
                state["exit_reason"] = "max_iterations"
                result = TransitionResult(
                    success=False,
                    reason=KickbackReason.MAX_ITERATIONS,
                    message="Max iterations reached"
                )
            workflow_client.workflow_set_state(self.workflow_id, state)
        
        return result
    
    def stop(self, reason: str = "user_stopped") -> None:
        """Stop the workflow."""
        state = self.get_state() or {}
        state["active"] = False
        state["exit_reason"] = reason
        workflow_client.workflow_set_state(self.workflow_id, state)
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/lib/test_workflow_base.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add lib/workflow_base.py tests/lib/test_workflow_base.py
git commit -m "feat: add WorkflowEngine for state machine execution"
```

---

### Task 1.3: Add File Pattern Restrictions

**Files:**
- Modify: `lib/workflow_base.py`
- Test: `tests/lib/test_workflow_base.py`

**Step 1: Write the failing test**

```python
# Add to tests/lib/test_workflow_base.py

def test_file_pattern_restriction():
    """Engine should restrict edits to allowed file patterns."""
    from lib.workflow_base import WorkflowEngine, WorkflowDefinition, WorkflowPhase
    
    phases = {
        "reproduce": WorkflowPhase(
            name="reproduce",
            allowed_tools=frozenset({"Edit", "Write"}),
            allowed_file_patterns=frozenset({
                "tests/**",
                "*_test.py",
                "test_*.py",
                "conftest.py",
            }),
        ),
    }
    definition = WorkflowDefinition(
        name="test",
        phases=phases,
        transitions={},
        initial_phase="reproduce",
    )
    
    engine = WorkflowEngine(definition)
    engine.start(task="Test")
    
    # Test files should be allowed
    allowed, reason = engine.is_tool_allowed("Edit", file_path="tests/test_foo.py")
    assert allowed is True
    
    allowed, reason = engine.is_tool_allowed("Edit", file_path="test_bar.py")
    assert allowed is True
    
    # Non-test files should be blocked
    allowed, reason = engine.is_tool_allowed("Edit", file_path="src/main.py")
    assert allowed is False
    assert "pattern" in reason.lower()
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/lib/test_workflow_base.py::test_file_pattern_restriction -v`
Expected: FAIL

**Step 3: Write minimal implementation**

```python
# Modify is_tool_allowed in WorkflowEngine class in lib/workflow_base.py

import fnmatch
from pathlib import Path

def is_tool_allowed(
    self, 
    tool_name: str, 
    command: Optional[str] = None,
    file_path: Optional[str] = None
) -> tuple[bool, str]:
    """Check if tool is allowed in current phase.
    
    Args:
        tool_name: Name of the tool
        command: For Bash, the command string
        file_path: For Edit/Write, the target file path
    """
    state = self.get_state()
    if not state or not state.get("active"):
        return True, "No active workflow"
    
    phase_name = state.get("phase")
    phase = self.definition.get_phase(phase_name)
    if not phase:
        return True, f"Unknown phase: {phase_name}"
    
    # Check blocked list first
    if tool_name in phase.blocked_tools:
        return False, f"[BLOCKED] {tool_name} not allowed in {phase_name} phase"
    
    # If allowed_tools is non-empty, tool must be in it
    if phase.allowed_tools and tool_name not in phase.allowed_tools:
        return False, f"[BLOCKED] {tool_name} not in allowed tools for {phase_name}"
    
    # Check file pattern restrictions for Edit/Write
    if file_path and tool_name in ("Edit", "Write") and phase.allowed_file_patterns:
        path = Path(file_path)
        allowed = any(
            fnmatch.fnmatch(str(path), pattern) or
            fnmatch.fnmatch(path.name, pattern)
            for pattern in phase.allowed_file_patterns
        )
        if not allowed:
            return False, f"[BLOCKED] {file_path} does not match allowed patterns for {phase_name}"
    
    return True, ""
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/lib/test_workflow_base.py::test_file_pattern_restriction -v`
Expected: PASS

**Step 5: Commit**

```bash
git add lib/workflow_base.py tests/lib/test_workflow_base.py
git commit -m "feat: add file pattern restrictions to workflow phases"
```

---

## Phase 2: Adversary Gate Integration

### Task 2.1: Create adversary_gate.py - Confidence Scoring

**Files:**
- Create: `lib/adversary_gate.py`
- Test: `tests/lib/test_adversary_gate.py`

**Step 1: Write the failing test**

```python
# tests/lib/test_adversary_gate.py
import pytest
from lib.adversary_gate import (
    AdversaryObjection, ConfidenceLevel, ConfidenceScore,
    AdversaryGate, ObjectionResult
)


def test_confidence_score_calculation():
    """Confidence score should aggregate dimensions."""
    score = ConfidenceScore(
        attack_survival=(8, 10),      # 80%
        mutation_survival=(6, 10),    # 60%
        dimension_coverage=(4, 5),    # 80%
        specificity="medium",
        mock_fidelity=(2, 3),         # 2 verified, 1 assumed
        redundant_tests=[],           # No redundant tests flagged
    )
    
    # Overall should be weighted average
    assert 70 <= score.overall <= 75


def test_redundancy_analysis():
    """Adversary should flag redundant tests."""
    score = ConfidenceScore(
        attack_survival=(8, 10),
        mutation_survival=(6, 10),
        dimension_coverage=(4, 5),
        specificity="medium",
        mock_fidelity=(2, 3),
        redundant_tests=[
            {"test": "test_login_valid", "overlaps_with": "test_login_success", "reason": "same assertions"},
            {"test": "test_returns_token", "overlaps_with": "test_login_success", "reason": "covered by existing"},
        ],
    )
    
    assert len(score.redundant_tests) == 2
    assert score.has_redundancy is True


def test_adversary_objection_requires_evidence():
    """Objections must cite specific evidence."""
    # Valid objection with evidence
    objection = AdversaryObjection(
        confidence=ConfidenceLevel.HIGH,
        concern="Missing edge case",
        evidence="Function foo() at line 42 doesn't handle None input",
        suggestion="Add test for None input",
    )
    assert objection.is_valid() is True
    
    # Invalid objection without evidence
    objection = AdversaryObjection(
        confidence=ConfidenceLevel.HIGH,
        concern="I'm not convinced",
        evidence="",
        suggestion="",
    )
    assert objection.is_valid() is False


def test_adversary_gate_override_rules():
    """Override rules should vary by confidence level."""
    gate = AdversaryGate()
    
    # Low confidence can be overridden with brief rationale
    result = gate.evaluate_objection(
        AdversaryObjection(
            confidence=ConfidenceLevel.LOW,
            concern="Minor style issue",
            evidence="Line 10 uses single quotes",
        ),
        override_rationale="Project uses single quotes consistently"
    )
    assert result.can_proceed is True
    
    # High confidence requires user appeal
    result = gate.evaluate_objection(
        AdversaryObjection(
            confidence=ConfidenceLevel.HIGH,
            concern="Security vulnerability",
            evidence="SQL injection at line 25",
        ),
        override_rationale="I think it's fine"
    )
    assert result.can_proceed is False
    assert result.requires_user_appeal is True
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/lib/test_adversary_gate.py -v`
Expected: FAIL with "No module named 'lib.adversary_gate'"

**Step 3: Write minimal implementation**

```python
# lib/adversary_gate.py
"""Adversary gate for workflow phase transitions.

Provides:
- Confidence scoring for test quality
- Objection handling with evidence requirements
- Override rules based on confidence levels
"""

from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional, Tuple


class ConfidenceLevel(Enum):
    """Confidence level for adversary objections."""
    LOW = auto()      # Can override with brief rationale
    MEDIUM = auto()   # Should address, can appeal with justification
    HIGH = auto()     # Must address or appeal to user


@dataclass
class ConfidenceScore:
    """Aggregated test confidence score."""
    attack_survival: Tuple[int, int]      # (passed, total)
    mutation_survival: Tuple[int, int]    # (caught, total)
    dimension_coverage: Tuple[int, int]   # (covered, total)
    specificity: str                      # "high", "medium", "low"
    mock_fidelity: Tuple[int, int]        # (verified, total)
    redundant_tests: list = field(default_factory=list)  # Tests flagged as redundant
    
    @property
    def has_redundancy(self) -> bool:
        """Check if any tests were flagged as redundant."""
        return len(self.redundant_tests) > 0
    
    @property
    def overall(self) -> float:
        """Calculate overall confidence percentage."""
        weights = {
            "attack": 0.30,
            "mutation": 0.25,
            "dimension": 0.25,
            "specificity": 0.10,
            "mock": 0.10,
        }
        
        attack_pct = (self.attack_survival[0] / self.attack_survival[1] * 100
                      if self.attack_survival[1] > 0 else 0)
        mutation_pct = (self.mutation_survival[0] / self.mutation_survival[1] * 100
                        if self.mutation_survival[1] > 0 else 0)
        dimension_pct = (self.dimension_coverage[0] / self.dimension_coverage[1] * 100
                         if self.dimension_coverage[1] > 0 else 0)
        specificity_pct = {"high": 100, "medium": 70, "low": 40}.get(self.specificity, 50)
        mock_pct = (self.mock_fidelity[0] / self.mock_fidelity[1] * 100
                    if self.mock_fidelity[1] > 0 else 100)
        
        return (
            attack_pct * weights["attack"] +
            mutation_pct * weights["mutation"] +
            dimension_pct * weights["dimension"] +
            specificity_pct * weights["specificity"] +
            mock_pct * weights["mock"]
        )
    
    def format_report(self) -> str:
        """Format confidence score as readable report."""
        attack_pct = (self.attack_survival[0] / self.attack_survival[1] * 100
                      if self.attack_survival[1] > 0 else 0)
        mutation_pct = (self.mutation_survival[0] / self.mutation_survival[1] * 100
                        if self.mutation_survival[1] > 0 else 0)
        dimension_pct = (self.dimension_coverage[0] / self.dimension_coverage[1] * 100
                         if self.dimension_coverage[1] > 0 else 0)
        
        redundancy_line = f"\n└── Redundancy:          {len(self.redundant_tests)} flagged" if self.redundant_tests else ""
        mock_prefix = "├──" if self.redundant_tests else "└──"
        
        report = f"""Test Confidence: {self.overall:.0f}%
├── Attack survival:     {self.attack_survival[0]}/{self.attack_survival[1]} ({attack_pct:.0f}%)
├── Mutation survival:   {self.mutation_survival[0]}/{self.mutation_survival[1]} ({mutation_pct:.0f}%)
├── Dimension coverage:  {self.dimension_coverage[0]}/{self.dimension_coverage[1]} ({dimension_pct:.0f}%)
├── Specificity:         {self.specificity}
{mock_prefix} Mock fidelity:       {self.mock_fidelity[0]} verified, {self.mock_fidelity[1] - self.mock_fidelity[0]} assumed{redundancy_line}"""
        
        # Add redundancy details if present
        if self.redundant_tests:
            report += "\n\nRedundant Tests (recommend removal):"
            for rt in self.redundant_tests:
                report += f"\n  - {rt['test']}: overlaps with {rt['overlaps_with']}"
        
        return report


@dataclass
class AdversaryObjection:
    """An objection raised by the adversary."""
    confidence: ConfidenceLevel
    concern: str
    evidence: str = ""
    suggestion: str = ""
    
    def is_valid(self) -> bool:
        """Check if objection has sufficient evidence."""
        # Must have specific evidence, not just vague concern
        return bool(self.evidence and len(self.evidence) > 10)


@dataclass
class ObjectionResult:
    """Result of evaluating an objection."""
    can_proceed: bool
    requires_user_appeal: bool = False
    message: str = ""


class AdversaryGate:
    """Gate that evaluates adversary objections before phase transitions."""
    
    def __init__(self, confidence_threshold: float = 70.0):
        self.confidence_threshold = confidence_threshold
        self.user_overrides = 0
    
    def evaluate_objection(
        self,
        objection: AdversaryObjection,
        override_rationale: Optional[str] = None,
        user_approved: bool = False
    ) -> ObjectionResult:
        """Evaluate whether an objection blocks progress.
        
        Args:
            objection: The adversary's objection
            override_rationale: Agent's counter-argument
            user_approved: Whether user explicitly approved override
        """
        # Invalid objections (no evidence) don't block
        if not objection.is_valid():
            return ObjectionResult(can_proceed=True, message="Objection lacks evidence")
        
        # User approval always wins
        if user_approved:
            self.user_overrides += 1
            return ObjectionResult(can_proceed=True, message="User approved override")
        
        # Low confidence: can override with rationale
        if objection.confidence == ConfidenceLevel.LOW:
            if override_rationale:
                return ObjectionResult(can_proceed=True, message="Low confidence overridden")
            return ObjectionResult(
                can_proceed=False,
                message="Provide brief rationale to override low-confidence objection"
            )
        
        # Medium confidence: need good justification
        if objection.confidence == ConfidenceLevel.MEDIUM:
            if override_rationale and len(override_rationale) > 20:
                return ObjectionResult(can_proceed=True, message="Medium confidence overridden with justification")
            return ObjectionResult(
                can_proceed=False,
                requires_user_appeal=True,
                message="Address objection or provide detailed justification"
            )
        
        # High confidence: must address or user appeal
        return ObjectionResult(
            can_proceed=False,
            requires_user_appeal=True,
            message="High-confidence objection requires addressing or user appeal"
        )
    
    def check_confidence_threshold(self, score: ConfidenceScore) -> ObjectionResult:
        """Check if confidence score meets threshold."""
        if score.overall >= self.confidence_threshold:
            return ObjectionResult(can_proceed=True, message=f"Confidence {score.overall:.0f}% meets threshold")
        return ObjectionResult(
            can_proceed=False,
            message=f"Confidence {score.overall:.0f}% below threshold {self.confidence_threshold:.0f}%"
        )
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/lib/test_adversary_gate.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add lib/adversary_gate.py tests/lib/test_adversary_gate.py
git commit -m "feat: add adversary gate with confidence scoring"
```

---

### Task 2.2: Integrate AdversaryGate with WorkflowEngine

**Files:**
- Modify: `lib/workflow_base.py`
- Test: `tests/lib/test_workflow_base.py`

**Step 1: Write the failing test**

```python
# Add to tests/lib/test_workflow_base.py

def test_adversary_gate_blocks_transition():
    """Phase with adversary_gate=True should require adversary approval."""
    from lib.workflow_base import (
        WorkflowEngine, WorkflowDefinition, WorkflowPhase,
        PhaseTransition, TransitionResult
    )
    from lib.adversary_gate import AdversaryObjection, ConfidenceLevel
    
    phases = {
        "hypothesize": WorkflowPhase(
            name="hypothesize",
            adversary_gate=True,  # Requires adversary approval
        ),
        "prove": WorkflowPhase(name="prove"),
    }
    transitions = {
        "hypothesize": PhaseTransition(
            from_phase="hypothesize",
            to_phase="prove",
        ),
    }
    definition = WorkflowDefinition(
        name="test",
        phases=phases,
        transitions=transitions,
        initial_phase="hypothesize",
    )
    
    engine = WorkflowEngine(definition)
    engine.start(task="Test")
    
    # Add high-confidence objection
    engine.add_adversary_objection(AdversaryObjection(
        confidence=ConfidenceLevel.HIGH,
        concern="Weak hypothesis",
        evidence="Hypothesis doesn't explain the timing issue on line 42",
    ))
    
    # Should be blocked
    result = engine.advance()
    assert result.success is False
    assert "adversary" in result.message.lower()
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/lib/test_workflow_base.py::test_adversary_gate_blocks_transition -v`
Expected: FAIL with "has no attribute 'add_adversary_objection'"

**Step 3: Write minimal implementation**

```python
# Add to WorkflowEngine class in lib/workflow_base.py

from adversary_gate import AdversaryGate, AdversaryObjection, ObjectionResult

class WorkflowEngine:
    def __init__(self, definition: WorkflowDefinition, workflow_id: Optional[str] = None):
        self.definition = definition
        self.workflow_id = workflow_id or definition.name
        self.adversary_gate = AdversaryGate()
        self._pending_objections: list[AdversaryObjection] = []
    
    def add_adversary_objection(self, objection: AdversaryObjection) -> None:
        """Add an adversary objection for current phase."""
        self._pending_objections.append(objection)
    
    def clear_objections(self) -> None:
        """Clear pending objections (after addressing them)."""
        self._pending_objections.clear()
    
    def advance(self, override_rationale: Optional[str] = None, user_approved: bool = False) -> TransitionResult:
        """Attempt to advance to next phase."""
        state = self.get_state()
        if not state or not state.get("active"):
            return TransitionResult(success=False, message="Workflow not active")
        
        current_phase_name = state.get("phase")
        current_phase = self.definition.get_phase(current_phase_name)
        
        # Check adversary gate if enabled for this phase
        if current_phase and current_phase.adversary_gate and self._pending_objections:
            for objection in self._pending_objections:
                result = self.adversary_gate.evaluate_objection(
                    objection,
                    override_rationale=override_rationale,
                    user_approved=user_approved
                )
                if not result.can_proceed:
                    return TransitionResult(
                        success=False,
                        reason=KickbackReason.ADVERSARY_REJECTED,
                        message=f"Adversary objection: {result.message}"
                    )
        
        # Clear objections after passing gate
        self.clear_objections()
        
        # Continue with normal transition logic...
        transition = self.definition.get_transition(current_phase_name)
        
        if not transition:
            return TransitionResult(success=False, message=f"No transition from {current_phase_name}")
        
        if transition.condition:
            result = transition.condition(state)
        else:
            result = TransitionResult(success=True, next_phase=transition.to_phase)
        
        if result.success and result.next_phase:
            state["phase"] = result.next_phase
            workflow_client.workflow_set_state(self.workflow_id, state)
        elif result.kickback_to:
            state["phase"] = result.kickback_to
            state["iteration"] = state.get("iteration", 0) + 1
            if state["iteration"] >= state.get("max_iterations", 5):
                state["active"] = False
                state["exit_reason"] = "max_iterations"
            workflow_client.workflow_set_state(self.workflow_id, state)
        
        return result
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/lib/test_workflow_base.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add lib/workflow_base.py tests/lib/test_workflow_base.py
git commit -m "feat: integrate adversary gate with workflow engine"
```

---

## Phase 3: Check Status Integration

### Task 3.1: Create check_status.py - Post-Push Verification

**Files:**
- Create: `lib/check_status.py`
- Test: `tests/lib/test_check_status.py`

**Step 1: Write the failing test**

```python
# tests/lib/test_check_status.py
import pytest
from lib.check_status import (
    CheckStatusResult, CIStatus, ReviewStatus,
    check_ci_status, check_review_comments, CheckStatusGate
)


def test_ci_status_check():
    """Should detect CI failures."""
    # Mock successful CI
    result = check_ci_status(pr_number=123, mock_status=CIStatus.PASSING)
    assert result.passed is True
    
    # Mock failed CI
    result = check_ci_status(pr_number=123, mock_status=CIStatus.FAILED)
    assert result.passed is False
    assert "ci" in result.reason.lower()


def test_review_comments_check():
    """Should detect new review comments."""
    # No new comments
    result = check_review_comments(
        pr_number=123,
        since_push=True,
        mock_comments=[]
    )
    assert result.has_new_comments is False
    
    # New comments found
    result = check_review_comments(
        pr_number=123,
        since_push=True,
        mock_comments=[{"id": 1, "body": "Please fix this"}]
    )
    assert result.has_new_comments is True


def test_check_status_gate():
    """Gate should combine CI and review checks."""
    gate = CheckStatusGate(pr_number=123)
    
    # All clear
    result = gate.check(mock_ci=CIStatus.PASSING, mock_comments=[])
    assert result.can_proceed is True
    
    # CI failed
    result = gate.check(mock_ci=CIStatus.FAILED, mock_comments=[])
    assert result.can_proceed is False
    assert result.kickback_reason is not None
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/lib/test_check_status.py -v`
Expected: FAIL

**Step 3: Write minimal implementation**

```python
# lib/check_status.py
"""Post-push verification for workflows.

Checks CI status and review comments after pushing changes.
Used by debug, PR comment, and iterate workflows.
"""

import subprocess
import json
from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional


class CIStatus(Enum):
    """CI pipeline status."""
    PASSING = auto()
    FAILED = auto()
    PENDING = auto()
    UNKNOWN = auto()


@dataclass
class CICheckResult:
    """Result of CI status check."""
    passed: bool
    status: CIStatus
    reason: str = ""
    details: dict = None


@dataclass
class ReviewCheckResult:
    """Result of review comments check."""
    has_new_comments: bool
    comments: list = None
    reason: str = ""


@dataclass
class CheckStatusResult:
    """Combined status check result."""
    can_proceed: bool
    ci_result: Optional[CICheckResult] = None
    review_result: Optional[ReviewCheckResult] = None
    kickback_reason: Optional[str] = None


def check_ci_status(
    pr_number: int,
    mock_status: Optional[CIStatus] = None
) -> CICheckResult:
    """Check CI status for a PR.
    
    Args:
        pr_number: GitHub PR number
        mock_status: For testing, override actual check
    """
    if mock_status is not None:
        return CICheckResult(
            passed=mock_status == CIStatus.PASSING,
            status=mock_status,
            reason="" if mock_status == CIStatus.PASSING else "CI checks failed"
        )
    
    try:
        result = subprocess.run(
            ["gh", "pr", "checks", str(pr_number), "--json", "state,name"],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if result.returncode != 0:
            return CICheckResult(
                passed=False,
                status=CIStatus.UNKNOWN,
                reason=f"Failed to get CI status: {result.stderr}"
            )
        
        checks = json.loads(result.stdout)
        failed = [c for c in checks if c.get("state") == "FAILURE"]
        pending = [c for c in checks if c.get("state") == "PENDING"]
        
        if failed:
            return CICheckResult(
                passed=False,
                status=CIStatus.FAILED,
                reason=f"CI failed: {', '.join(c['name'] for c in failed)}",
                details={"failed_checks": failed}
            )
        
        if pending:
            return CICheckResult(
                passed=False,
                status=CIStatus.PENDING,
                reason=f"CI pending: {', '.join(c['name'] for c in pending)}"
            )
        
        return CICheckResult(passed=True, status=CIStatus.PASSING)
        
    except Exception as e:
        return CICheckResult(
            passed=False,
            status=CIStatus.UNKNOWN,
            reason=f"Error checking CI: {e}"
        )


def check_review_comments(
    pr_number: int,
    since_push: bool = True,
    mock_comments: Optional[list] = None
) -> ReviewCheckResult:
    """Check for new review comments on a PR.
    
    Args:
        pr_number: GitHub PR number
        since_push: Only check comments since last push
        mock_comments: For testing, override actual check
    """
    if mock_comments is not None:
        return ReviewCheckResult(
            has_new_comments=len(mock_comments) > 0,
            comments=mock_comments,
            reason="" if not mock_comments else f"{len(mock_comments)} new comment(s)"
        )
    
    try:
        result = subprocess.run(
            ["gh", "pr", "view", str(pr_number), "--json", "reviews,comments"],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if result.returncode != 0:
            return ReviewCheckResult(
                has_new_comments=False,
                reason=f"Failed to get comments: {result.stderr}"
            )
        
        data = json.loads(result.stdout)
        # Extract unresolved comments
        comments = []
        for review in data.get("reviews", []):
            for comment in review.get("comments", []):
                if not comment.get("isResolved", False):
                    comments.append(comment)
        
        return ReviewCheckResult(
            has_new_comments=len(comments) > 0,
            comments=comments,
            reason=f"{len(comments)} unresolved comment(s)" if comments else ""
        )
        
    except Exception as e:
        return ReviewCheckResult(
            has_new_comments=False,
            reason=f"Error checking comments: {e}"
        )


class CheckStatusGate:
    """Gate that checks CI and review status before proceeding."""
    
    def __init__(self, pr_number: int):
        self.pr_number = pr_number
    
    def check(
        self,
        mock_ci: Optional[CIStatus] = None,
        mock_comments: Optional[list] = None
    ) -> CheckStatusResult:
        """Run all status checks.
        
        Returns CheckStatusResult with can_proceed=True only if
        CI passes AND no new review comments.
        """
        ci_result = check_ci_status(self.pr_number, mock_status=mock_ci)
        review_result = check_review_comments(self.pr_number, mock_comments=mock_comments)
        
        can_proceed = ci_result.passed and not review_result.has_new_comments
        kickback_reason = None
        
        if not ci_result.passed:
            kickback_reason = f"CI: {ci_result.reason}"
        elif review_result.has_new_comments:
            kickback_reason = f"Reviews: {review_result.reason}"
        
        return CheckStatusResult(
            can_proceed=can_proceed,
            ci_result=ci_result,
            review_result=review_result,
            kickback_reason=kickback_reason
        )
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/lib/test_check_status.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add lib/check_status.py tests/lib/test_check_status.py
git commit -m "feat: add check_status module for post-push verification"
```

---

## Phase 4: Debug Workflow Implementation

### Task 4.1: Create debug_workflow.py Using Base Classes

**Files:**
- Create: `lib/debug_workflow.py`
- Test: `tests/lib/test_debug_workflow.py`

**Step 1: Write the failing test**

```python
# tests/lib/test_debug_workflow.py
import pytest
from lib.debug_workflow import DebugWorkflow, DebugPhase


def test_debug_workflow_phases():
    """Debug workflow should have all required phases."""
    wf = DebugWorkflow()
    
    expected_phases = [
        "triage", "reproduce", "hypothesize", "prove",
        "fix", "verify", "push", "check_status", "done"
    ]
    
    for phase in expected_phases:
        assert wf.engine.definition.get_phase(phase) is not None


def test_debug_workflow_triage_restrictions():
    """TRIAGE phase should block editing."""
    wf = DebugWorkflow()
    wf.start(bug_report="Test failure in auth module")
    
    assert wf.get_phase() == "triage"
    
    allowed, reason = wf.is_tool_allowed("Read")
    assert allowed is True
    
    allowed, reason = wf.is_tool_allowed("Edit")
    assert allowed is False


def test_debug_workflow_reproduce_test_only():
    """REPRODUCE should only allow editing test files."""
    wf = DebugWorkflow()
    wf.start(bug_report="Test")
    wf.set_phase("reproduce")
    
    # Test file allowed
    allowed, _ = wf.is_tool_allowed("Edit", file_path="tests/test_auth.py")
    assert allowed is True
    
    # Non-test file blocked
    allowed, _ = wf.is_tool_allowed("Edit", file_path="src/auth.py")
    assert allowed is False


def test_debug_workflow_hypothesize_gate():
    """HYPOTHESIZE should have adversary gate."""
    wf = DebugWorkflow()
    wf.start(bug_report="Test")
    wf.set_phase("hypothesize")
    
    phase = wf.engine.definition.get_phase("hypothesize")
    assert phase.adversary_gate is True
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/lib/test_debug_workflow.py -v`
Expected: FAIL

**Step 3: Write minimal implementation**

```python
# lib/debug_workflow.py
"""Debug workflow - root cause verification before fixing.

Phases:
  TRIAGE → REPRODUCE → HYPOTHESIZE → PROVE → FIX → VERIFY → PUSH → CHECK_STATUS → DONE
"""

from enum import Enum
from typing import Optional
from workflow_base import (
    WorkflowEngine, WorkflowDefinition, WorkflowPhase,
    PhaseTransition, TransitionResult, KickbackReason
)


class DebugPhase(str, Enum):
    """Debug workflow phases."""
    TRIAGE = "triage"
    REPRODUCE = "reproduce"
    HYPOTHESIZE = "hypothesize"
    PROVE = "prove"
    FIX = "fix"
    VERIFY = "verify"
    PUSH = "push"
    CHECK_STATUS = "check_status"
    DONE = "done"


# Phase definitions with tool restrictions
DEBUG_PHASES = {
    DebugPhase.TRIAGE.value: WorkflowPhase(
        name="triage",
        allowed_tools=frozenset({"Read", "Glob", "Grep", "WebSearch", "WebFetch"}),
        blocked_tools=frozenset({"Edit", "Write"}),
        required_outputs=["severity", "affected_components", "error_artifacts"],
    ),
    DebugPhase.REPRODUCE.value: WorkflowPhase(
        name="reproduce",
        allowed_tools=frozenset({"Read", "Glob", "Grep", "Edit", "Write", "Bash"}),
        allowed_file_patterns=frozenset({
            "tests/**", "*_test.py", "test_*.py",
            "conftest.py", "fixtures/**", "mocks/**"
        }),
        required_outputs=["failing_test"],
    ),
    DebugPhase.HYPOTHESIZE.value: WorkflowPhase(
        name="hypothesize",
        allowed_tools=frozenset({"Read", "Glob", "Grep"}),
        blocked_tools=frozenset({"Edit", "Write"}),
        required_outputs=["hypothesis", "prediction"],
        adversary_gate=True,  # Adversary challenges hypothesis
    ),
    DebugPhase.PROVE.value: WorkflowPhase(
        name="prove",
        allowed_tools=frozenset({"Read", "Glob", "Grep", "Bash"}),
        blocked_tools=frozenset({"Edit", "Write"}),
        required_outputs=["prediction_confirmed", "mechanism_traced", "alternative_ruled_out"],
        adversary_gate=True,  # Adversary verifies proof
    ),
    DebugPhase.FIX.value: WorkflowPhase(
        name="fix",
        allowed_tools=frozenset({"Read", "Glob", "Grep", "Edit", "Write", "Bash"}),
        adversary_gate=True,  # Adversary checks fix matches proof
    ),
    DebugPhase.VERIFY.value: WorkflowPhase(
        name="verify",
        allowed_tools=frozenset({"Read", "Glob", "Grep", "Bash"}),
        blocked_tools=frozenset({"Edit", "Write"}),
        requires_verification=True,
    ),
    DebugPhase.PUSH.value: WorkflowPhase(
        name="push",
        allowed_tools=frozenset({"Bash"}),
    ),
    DebugPhase.CHECK_STATUS.value: WorkflowPhase(
        name="check_status",
        allowed_tools=frozenset({"Read", "Bash"}),
        blocked_tools=frozenset({"Edit", "Write"}),
    ),
    DebugPhase.DONE.value: WorkflowPhase(
        name="done",
        allowed_tools=frozenset(),
    ),
}


def _make_transitions() -> dict[str, PhaseTransition]:
    """Create transition definitions with kickback logic."""
    
    def triage_to_reproduce(state: dict) -> TransitionResult:
        required = ["severity", "affected_components", "error_artifacts"]
        missing = [r for r in required if not state.get(r)]
        if missing:
            return TransitionResult(
                success=False,
                message=f"Missing triage outputs: {missing}"
            )
        return TransitionResult(success=True, next_phase="reproduce")
    
    def reproduce_to_hypothesize(state: dict) -> TransitionResult:
        if not state.get("failing_test"):
            return TransitionResult(
                success=False,
                kickback_to="triage",
                reason=KickbackReason.CANNOT_REPRODUCE,
                message="Cannot reproduce - need more context"
            )
        return TransitionResult(success=True, next_phase="hypothesize")
    
    def hypothesize_to_prove(state: dict) -> TransitionResult:
        if not state.get("hypothesis") or not state.get("prediction"):
            return TransitionResult(
                success=False,
                message="Hypothesis and prediction required"
            )
        return TransitionResult(success=True, next_phase="prove")
    
    def prove_to_fix(state: dict) -> TransitionResult:
        if not state.get("prediction_confirmed"):
            return TransitionResult(
                success=False,
                kickback_to="hypothesize",
                reason=KickbackReason.PREDICTION_NOT_CONFIRMED,
                message="Prediction not confirmed - revise hypothesis"
            )
        return TransitionResult(success=True, next_phase="fix")
    
    def fix_to_verify(state: dict) -> TransitionResult:
        return TransitionResult(success=True, next_phase="verify")
    
    def verify_to_push(state: dict) -> TransitionResult:
        tests_pass = state.get("tests_pass", False)
        lint_pass = state.get("lint_pass", False)
        
        if not tests_pass or not lint_pass:
            return TransitionResult(
                success=False,
                kickback_to="prove",
                reason=KickbackReason.VERIFICATION_FAILED,
                message="Verification failed - re-examine root cause"
            )
        return TransitionResult(success=True, next_phase="push")
    
    def push_to_check(state: dict) -> TransitionResult:
        return TransitionResult(success=True, next_phase="check_status")
    
    def check_to_done(state: dict) -> TransitionResult:
        ci_pass = state.get("ci_pass", False)
        no_new_comments = not state.get("new_review_comments", False)
        
        if not ci_pass or not no_new_comments:
            return TransitionResult(
                success=False,
                kickback_to="prove",
                reason=KickbackReason.CI_FAILED if not ci_pass else KickbackReason.NEW_COMMENTS,
                message="Check status failed - revisit understanding"
            )
        return TransitionResult(success=True, next_phase="done")
    
    return {
        "triage": PhaseTransition("triage", "reproduce", condition=triage_to_reproduce),
        "reproduce": PhaseTransition("reproduce", "hypothesize", condition=reproduce_to_hypothesize),
        "hypothesize": PhaseTransition("hypothesize", "prove", condition=hypothesize_to_prove),
        "prove": PhaseTransition("prove", "fix", condition=prove_to_fix),
        "fix": PhaseTransition("fix", "verify", condition=fix_to_verify),
        "verify": PhaseTransition("verify", "push", condition=verify_to_push),
        "push": PhaseTransition("push", "check_status", condition=push_to_check),
        "check_status": PhaseTransition("check_status", "done", condition=check_to_done),
    }


DEBUG_DEFINITION = WorkflowDefinition(
    name="debug",
    phases=DEBUG_PHASES,
    transitions=_make_transitions(),
    initial_phase="triage",
    max_iterations=5,
)


class DebugWorkflow:
    """Debug workflow - enforces root cause verification."""
    
    def __init__(self):
        self.engine = WorkflowEngine(DEBUG_DEFINITION, workflow_id="debug")
    
    def start(self, bug_report: str, **kwargs) -> dict:
        """Start debug workflow."""
        return self.engine.start(task=bug_report, bug_report=bug_report, **kwargs)
    
    def get_phase(self) -> Optional[str]:
        """Get current phase."""
        return self.engine.get_phase()
    
    def set_phase(self, phase: str) -> None:
        """Manually set phase (for testing/recovery)."""
        state = self.engine.get_state() or {}
        state["phase"] = phase
        import workflow_client
        workflow_client.workflow_set_state("debug", state)
    
    def is_tool_allowed(self, tool_name: str, file_path: Optional[str] = None) -> tuple[bool, str]:
        """Check tool restriction."""
        return self.engine.is_tool_allowed(tool_name, file_path=file_path)
    
    def advance(self, **kwargs) -> TransitionResult:
        """Advance to next phase."""
        return self.engine.advance(**kwargs)
    
    def record_triage(self, severity: str, components: list, artifacts: list) -> None:
        """Record triage outputs."""
        state = self.engine.get_state() or {}
        state["severity"] = severity
        state["affected_components"] = components
        state["error_artifacts"] = artifacts
        import workflow_client
        workflow_client.workflow_set_state("debug", state)
    
    def record_hypothesis(self, hypothesis: str, prediction: str) -> None:
        """Record hypothesis and prediction."""
        state = self.engine.get_state() or {}
        state["hypothesis"] = hypothesis
        state["prediction"] = prediction
        import workflow_client
        workflow_client.workflow_set_state("debug", state)
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/lib/test_debug_workflow.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add lib/debug_workflow.py tests/lib/test_debug_workflow.py
git commit -m "feat: add debug workflow using base classes"
```

---

## Phase 5: PR Comment Workflow Implementation

### Task 5.1: Create pr_comment_workflow.py

**Files:**
- Create: `lib/pr_comment_workflow.py`
- Test: `tests/lib/test_pr_comment_workflow.py`

**Step 1: Write the failing test**

```python
# tests/lib/test_pr_comment_workflow.py
import pytest
from lib.pr_comment_workflow import PRCommentWorkflow


def test_pr_comment_workflow_phases():
    """PR comment workflow should have required phases."""
    wf = PRCommentWorkflow()
    
    expected = ["understand", "fix", "verify", "push", "check_reviews", "done"]
    for phase in expected:
        assert wf.engine.definition.get_phase(phase) is not None


def test_understand_blocks_editing():
    """UNDERSTAND phase should block all editing."""
    wf = PRCommentWorkflow()
    wf.start(comment="Please rename this variable", pr_number=123)
    
    assert wf.get_phase() == "understand"
    
    allowed, _ = wf.is_tool_allowed("Read")
    assert allowed is True
    
    allowed, _ = wf.is_tool_allowed("Edit")
    assert allowed is False


def test_understand_has_adversary_gate():
    """UNDERSTAND should have adversary gate."""
    wf = PRCommentWorkflow()
    wf.start(comment="Test", pr_number=123)
    
    phase = wf.engine.definition.get_phase("understand")
    assert phase.adversary_gate is True
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/lib/test_pr_comment_workflow.py -v`
Expected: FAIL

**Step 3: Write minimal implementation**

```python
# lib/pr_comment_workflow.py
"""PR Comment workflow - understanding before fixing.

Phases:
  UNDERSTAND → FIX → VERIFY → PUSH → CHECK_REVIEWS → DONE
"""

from enum import Enum
from typing import Optional
from workflow_base import (
    WorkflowEngine, WorkflowDefinition, WorkflowPhase,
    PhaseTransition, TransitionResult, KickbackReason
)


class PRCommentPhase(str, Enum):
    """PR comment workflow phases."""
    UNDERSTAND = "understand"
    FIX = "fix"
    VERIFY = "verify"
    PUSH = "push"
    CHECK_REVIEWS = "check_reviews"
    DONE = "done"


PR_COMMENT_PHASES = {
    PRCommentPhase.UNDERSTAND.value: WorkflowPhase(
        name="understand",
        allowed_tools=frozenset({"Read", "Glob", "Grep"}),
        blocked_tools=frozenset({"Edit", "Write", "Bash"}),
        required_outputs=["articulation", "current_code_problem"],
        adversary_gate=True,  # Adversary validates understanding
    ),
    PRCommentPhase.FIX.value: WorkflowPhase(
        name="fix",
        allowed_tools=frozenset({"Read", "Glob", "Grep", "Edit", "Write", "Bash"}),
        adversary_gate=True,  # Adversary checks fix matches understanding
    ),
    PRCommentPhase.VERIFY.value: WorkflowPhase(
        name="verify",
        allowed_tools=frozenset({"Read", "Glob", "Grep", "Bash"}),
        blocked_tools=frozenset({"Edit", "Write"}),
        requires_verification=True,
    ),
    PRCommentPhase.PUSH.value: WorkflowPhase(
        name="push",
        allowed_tools=frozenset({"Bash"}),
    ),
    PRCommentPhase.CHECK_REVIEWS.value: WorkflowPhase(
        name="check_reviews",
        allowed_tools=frozenset({"Read", "Bash"}),
        blocked_tools=frozenset({"Edit", "Write"}),
    ),
    PRCommentPhase.DONE.value: WorkflowPhase(
        name="done",
        allowed_tools=frozenset(),
    ),
}


def _make_transitions() -> dict[str, PhaseTransition]:
    """Create transitions with kickback logic."""
    
    def understand_to_fix(state: dict) -> TransitionResult:
        if not state.get("articulation"):
            return TransitionResult(
                success=False,
                message="Must articulate reviewer's concern"
            )
        return TransitionResult(success=True, next_phase="fix")
    
    def fix_to_verify(state: dict) -> TransitionResult:
        return TransitionResult(success=True, next_phase="verify")
    
    def verify_to_push(state: dict) -> TransitionResult:
        if not state.get("tests_pass") or not state.get("lint_pass"):
            return TransitionResult(
                success=False,
                kickback_to="fix",
                reason=KickbackReason.VERIFICATION_FAILED,
            )
        return TransitionResult(success=True, next_phase="push")
    
    def push_to_check(state: dict) -> TransitionResult:
        return TransitionResult(success=True, next_phase="check_reviews")
    
    def check_to_done(state: dict) -> TransitionResult:
        if state.get("new_comments"):
            return TransitionResult(
                success=False,
                kickback_to="understand",
                reason=KickbackReason.NEW_COMMENTS,
                message="New review comments - re-understand"
            )
        return TransitionResult(success=True, next_phase="done")
    
    return {
        "understand": PhaseTransition("understand", "fix", condition=understand_to_fix),
        "fix": PhaseTransition("fix", "verify", condition=fix_to_verify),
        "verify": PhaseTransition("verify", "push", condition=verify_to_push),
        "push": PhaseTransition("push", "check_reviews", condition=push_to_check),
        "check_reviews": PhaseTransition("check_reviews", "done", condition=check_to_done),
    }


PR_COMMENT_DEFINITION = WorkflowDefinition(
    name="pr_comment",
    phases=PR_COMMENT_PHASES,
    transitions=_make_transitions(),
    initial_phase="understand",
    max_iterations=3,  # Fewer iterations - escalate faster
)


class PRCommentWorkflow:
    """PR Comment workflow - understanding before fixing."""
    
    def __init__(self):
        self.engine = WorkflowEngine(PR_COMMENT_DEFINITION, workflow_id="pr_comment")
    
    def start(self, comment: str, pr_number: int, **kwargs) -> dict:
        """Start workflow for a PR comment."""
        return self.engine.start(
            task=f"Address PR comment: {comment[:50]}...",
            comment=comment,
            pr_number=pr_number,
            **kwargs
        )
    
    def get_phase(self) -> Optional[str]:
        return self.engine.get_phase()
    
    def is_tool_allowed(self, tool_name: str, **kwargs) -> tuple[bool, str]:
        return self.engine.is_tool_allowed(tool_name, **kwargs)
    
    def record_understanding(self, articulation: str, problem: str) -> None:
        """Record understanding of reviewer's concern."""
        state = self.engine.get_state() or {}
        state["articulation"] = articulation
        state["current_code_problem"] = problem
        import workflow_client
        workflow_client.workflow_set_state("pr_comment", state)
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/lib/test_pr_comment_workflow.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add lib/pr_comment_workflow.py tests/lib/test_pr_comment_workflow.py
git commit -m "feat: add PR comment workflow using base classes"
```

---

## Phase 6: Generic Enforcement Hook

### Task 6.1: Create workflow-enforcement.py

**Files:**
- Create: `hooks/workflow-enforcement.py`
- Test: Manual testing via hook

**Step 1: Write the implementation**

```python
#!/usr/bin/env python3
"""Generic workflow enforcement hook.

Dispatches to active workflow's tool restrictions.
Supports: debug, pr_comment, iterate workflows.
"""

import sys
import json
from pathlib import Path

lib_dir = Path(__file__).parent.parent / "lib"
sys.path.insert(0, str(lib_dir))

try:
    from workflow_client import workflow_get_state
    from debug_workflow import DebugWorkflow
    from pr_comment_workflow import PRCommentWorkflow
    from iterate_workflow import is_tool_allowed as iterate_is_tool_allowed, is_active as iterate_is_active
except ImportError as e:
    # Fail open if modules not available
    def workflow_get_state(wf_id):
        return None
    def iterate_is_active():
        return False
    def iterate_is_tool_allowed(tool, command=None):
        return True, ""


WORKFLOWS = {
    "debug": DebugWorkflow,
    "pr_comment": PRCommentWorkflow,
}


def allow(reason: str = "") -> dict:
    result = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow"
        }
    }
    if reason:
        result["hookSpecificOutput"]["permissionDecisionReason"] = reason
    return result


def block(reason: str) -> dict:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason
        }
    }


def main():
    try:
        input_data = json.loads(sys.stdin.read())
    except json.JSONDecodeError:
        print(json.dumps(allow()))
        return

    tool_name = input_data.get("tool_name", "")
    tool_input = input_data.get("tool_input", {})
    
    # Normalize MCP prefix
    if tool_name.startswith("mcp__router__"):
        tool_name = tool_name[len("mcp__router__"):]
    
    # Check each workflow type
    for wf_id, wf_class in WORKFLOWS.items():
        state = workflow_get_state(wf_id)
        if state and state.get("active"):
            wf = wf_class()
            wf.engine._state = state  # Load existing state
            
            file_path = tool_input.get("file_path") or tool_input.get("path")
            allowed, reason = wf.is_tool_allowed(tool_name, file_path=file_path)
            
            if not allowed:
                phase = state.get("phase", "unknown")
                print(json.dumps(block(f"[{wf_id.upper()}:{phase}] {reason}")))
                return
    
    # Check iterate workflow (uses its own logic)
    if iterate_is_active():
        command = tool_input.get("command") if tool_name in ("Bash", "native__bash") else None
        allowed, reason = iterate_is_tool_allowed(tool_name, command=command)
        if not allowed:
            print(json.dumps(block(reason)))
            return
    
    print(json.dumps(allow()))


if __name__ == "__main__":
    main()
```

**Step 2: Make executable and test**

```bash
chmod +x hooks/workflow-enforcement.py
echo '{"tool_name": "Edit", "tool_input": {"file_path": "src/main.py"}}' | python3 hooks/workflow-enforcement.py
```

**Step 3: Commit**

```bash
git add hooks/workflow-enforcement.py
git commit -m "feat: add generic workflow enforcement hook"
```

---

## Phase 7: Parallel Adversary Execution

### Task 7.1: Add Parallel Adversary Support to WorkflowEngine

**Files:**
- Modify: `lib/workflow_base.py`
- Test: `tests/lib/test_workflow_base.py`

**Step 1: Write the failing test**

```python
# Add to tests/lib/test_workflow_base.py

def test_parallel_adversary_check():
    """Adversary checks should support parallel execution."""
    from lib.workflow_base import WorkflowEngine, WorkflowDefinition, WorkflowPhase
    
    phases = {
        "implement": WorkflowPhase(
            name="implement",
            adversary_gate=True,
            adversary_parallel=True,  # Run adversary in parallel
        ),
    }
    definition = WorkflowDefinition(
        name="test",
        phases=phases,
        transitions={},
        initial_phase="implement",
    )
    
    engine = WorkflowEngine(definition)
    engine.start(task="Test")
    
    # Should return adversary check task ID for parallel execution
    task_id = engine.start_adversary_check()
    assert task_id is not None
    
    # Can poll for result
    result = engine.get_adversary_result(task_id, block=False)
    # Result may be None if still running
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/lib/test_workflow_base.py::test_parallel_adversary_check -v`
Expected: FAIL

**Step 3: Write minimal implementation**

```python
# Add to WorkflowPhase dataclass
@dataclass(frozen=True)
class WorkflowPhase:
    name: str
    allowed_tools: FrozenSet[str] = field(default_factory=frozenset)
    blocked_tools: FrozenSet[str] = field(default_factory=frozenset)
    allowed_file_patterns: FrozenSet[str] = field(default_factory=frozenset)
    required_outputs: list[str] = field(default_factory=list)
    adversary_gate: bool = False
    adversary_parallel: bool = False  # NEW: run adversary in parallel
    requires_verification: bool = False


# Add to WorkflowEngine class
def start_adversary_check(self) -> Optional[str]:
    """Start adversary check in background (for parallel execution).
    
    Returns task_id for polling, or None if no adversary gate.
    """
    state = self.get_state()
    if not state:
        return None
    
    phase = self.definition.get_phase(state.get("phase"))
    if not phase or not phase.adversary_gate:
        return None
    
    # Store task ID in state for later retrieval
    import uuid
    task_id = f"adversary-{uuid.uuid4().hex[:8]}"
    state["_adversary_task_id"] = task_id
    state["_adversary_started"] = True
    workflow_client.workflow_set_state(self.workflow_id, state)
    
    return task_id


def get_adversary_result(self, task_id: str, block: bool = False) -> Optional[dict]:
    """Get result of parallel adversary check.
    
    Args:
        task_id: Task ID from start_adversary_check
        block: If True, wait for result
        
    Returns:
        Result dict or None if not ready
    """
    state = self.get_state()
    if not state or state.get("_adversary_task_id") != task_id:
        return None
    
    # Check if result is available
    result = state.get("_adversary_result")
    if result:
        return result
    
    if not block:
        return None
    
    # In real implementation, would poll TaskOutput
    # For now, return placeholder
    return {"status": "pending"}
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/lib/test_workflow_base.py::test_parallel_adversary_check -v`
Expected: PASS

**Step 5: Commit**

```bash
git add lib/workflow_base.py tests/lib/test_workflow_base.py
git commit -m "feat: add parallel adversary check support"
```

---

## Phase 8: Iterate Workflow Refactoring

### Task 8.1: Refactor iterate_workflow.py to Use Base Classes

**Files:**
- Modify: `lib/iterate_workflow.py`
- Test: Existing tests should still pass

**Note:** This is a larger refactoring task. The approach is:
1. Create `IterateWorkflowV2` using base classes alongside existing code
2. Gradually migrate functionality
3. Switch over once tests pass
4. Remove old code

**Step 1: Add V2 implementation**

```python
# Add to lib/iterate_workflow.py (at end of file)

# V2 Implementation using base classes
from workflow_base import (
    WorkflowEngine, WorkflowDefinition, WorkflowPhase,
    PhaseTransition, TransitionResult, KickbackReason
)

ITERATE_V2_PHASES = {
    "orchestrate": WorkflowPhase(
        name="orchestrate",
        allowed_tools=frozenset({"Read", "Task", "TodoWrite", "TaskOutput", "Glob", "Grep"}),
        blocked_tools=frozenset({"Edit", "Write", "NotebookEdit", "Bash"}),
        adversary_gate=True,  # NEW: adversary at design decisions
    ),
    "test_writing": WorkflowPhase(
        name="test_writing",
        allowed_tools=frozenset({"Read", "Glob", "Grep", "Edit", "Write", "Bash"}),
        adversary_gate=True,  # NEW: adversary challenges test quality
        adversary_parallel=True,  # Run in parallel for efficiency
    ),
    # ... (continue for all phases)
}

class IterateWorkflowV2:
    """V2 iterate workflow using base classes.
    
    Adds:
    - Adversary gates at design and test phases
    - Test confidence scoring
    - CHECK_STATUS after push
    """
    pass  # Implementation follows same pattern as debug_workflow.py
```

**Step 2: Run existing tests**

Run: `pytest tests/lib/test_iterate_workflow.py -v`
Expected: PASS (existing code unchanged)

**Step 3: Commit**

```bash
git add lib/iterate_workflow.py
git commit -m "feat: add iterate workflow V2 skeleton using base classes"
```

---

## Summary: Execution Order

| Phase | Tasks | Parallelizable |
|-------|-------|----------------|
| 1. Base Library | 1.1, 1.2, 1.3 | No (sequential) |
| 2. Adversary Gate | 2.1, 2.2 | No (sequential) |
| 3. Check Status | 3.1 | Yes (independent) |
| 4. Debug Workflow | 4.1 | After Phase 1-2 |
| 5. PR Comment Workflow | 5.1 | After Phase 1-2, parallel with 4 |
| 6. Enforcement Hook | 6.1 | After 4, 5 |
| 7. Parallel Adversary | 7.1 | After Phase 2 |
| 8. Iterate Refactor | 8.1 | After all above |

**Estimated tasks:** 12 discrete tasks
**Parallel opportunities:** Phases 4 & 5 can run in parallel; Phase 3 can run parallel with Phase 2

---

## Post-Implementation Checklist

- [ ] All tests pass: `pytest tests/lib/test_workflow_*.py -v`
- [ ] Lint passes: `ruff check lib/workflow_base.py lib/adversary_gate.py lib/check_status.py`
- [ ] Type check: `mypy lib/workflow_base.py --ignore-missing-imports`
- [ ] Hook works: Manual test with each workflow type
- [ ] Existing iterate tests still pass
- [ ] Documentation updated if needed

---

Plan complete and saved to `docs/plans/2026-01-22-workflow-abstraction-implementation.md`.

**Two execution options:**

1. **Subagent-Driven (this session)** - I dispatch fresh subagent per task, review between tasks, fast iteration

2. **Parallel Session (separate)** - Open new session with executing-plans, batch execution with checkpoints

**Which approach?**