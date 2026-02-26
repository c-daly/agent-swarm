"""Minimal iterate workflow - TDD loop with phase gates.

This is a simplified replacement for the complex workflow.py.
Focus: Clear state, simple phases, reliable persistence.

Flow:
  test_writing -> implement -> test -> review -> [loop or done]
                     ^           |        |
                     |           v        v
                     +--- FAIL --+   issues found
"""

import json
import logging
import os
import re
from pathlib import Path
from typing import Optional
from enum import Enum

# Allow override via environment variable for test isolation
_state_dir_override = os.environ.get("ITERATE_STATE_DIR")
STATE_DIR = Path(_state_dir_override) if _state_dir_override else Path(__file__).resolve().parent.parent / ".state"
LOG_FILE = STATE_DIR / "iterate.log"

# Ensure lib is in path for workflow_server import (needed when run standalone)
import sys  # noqa: E402
lib_dir = Path(__file__).parent
if str(lib_dir) not in sys.path:
    sys.path.insert(0, str(lib_dir))

# CLI script: uses DaemonClient for persistent state
# via the MCP router, same as subagents and hooks
from daemon_client import DaemonClient  # noqa: E402


def _get_state() -> dict:
    """Get current iterate workflow state from router."""
    with DaemonClient() as dc:
        return dc.workflow_get_state("iterate") or {}


def _set_state(state: dict) -> None:
    """Persist iterate workflow state to router."""
    with DaemonClient() as dc:
        for key, value in state.items():
            dc.workflow_set_value("iterate", key, value)
from workflow_base import (  # noqa: E402
    WorkflowPhase, WorkflowDefinition, WorkflowEngine,
    PhaseTransition, KickbackReason
)

# Map MCP tool base names to their native Claude equivalents
# Used by is_tool_allowed() to normalize tool names for PHASE_TOOLS lookup
MCP_TO_NATIVE = {
    # Native router tools
    "read_file": "Read",
    "write_file": "Write",
    "edit_file": "Edit",
    "glob": "Glob",
    "grep": "Grep",
    "bash": "Bash",
    # Serena equivalents
    "list_dir": "Glob",
    "find_file": "Glob",
    "search_for_pattern": "Grep",
    "create_text_file": "Write",
    "replace_content": "Edit",
    "get_symbols_overview": "Read",
    "find_symbol": "Read",
    "read_memory": "Read",
}

# Module-level logger instance
_logger: Optional[logging.Logger] = None


def _get_logger() -> logging.Logger:
    """Get or create iterate workflow logger."""
    global _logger
    if _logger is not None:
        return _logger

    _logger = logging.getLogger("iterate_workflow")
    _logger.propagate = False  # Prevent duplicate output to root logger
    level_name = os.environ.get("ITERATE_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    _logger.setLevel(level)

    # Avoid duplicate handlers
    if not _logger.handlers:
        try:
            STATE_DIR.mkdir(parents=True, exist_ok=True)
            handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
            handler.setFormatter(logging.Formatter(
                "%(asctime)s [%(levelname)s] %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S"
            ))
            _logger.addHandler(handler)
        except (OSError, IOError):
            pass  # Silently fail - logging shouldn't break workflow

    return _logger


def _log(level: str, message: str, **context) -> None:
    """Internal logging helper. Never raises exceptions."""
    try:
        logger = _get_logger()
        if context:
            ctx_str = " ".join(f"{k}={v}" for k, v in context.items())
            message = f"{message} | {ctx_str}"
        getattr(logger, level)(message)
        # Flush handlers to ensure logs are written
        for handler in logger.handlers:
            handler.flush()
    except Exception:
        pass  # Never let logging break the workflow


def _reset_logger() -> None:
    """Reset the logger (for testing). Closes handlers and clears cached logger."""
    global _logger
    if _logger is not None:
        for handler in _logger.handlers[:]:
            handler.close()
            _logger.removeHandler(handler)
        _logger = None


class Phase(Enum):
    """TDD workflow phases.

    Orchestration mode (main agent):
        ORCHESTRATE - Coordinate subagents, never advance

    Optional discovery phases (before TDD loop):
        INTAKE -> DESIGN -> [TDD loop]

    TDD loop:
        TEST_WRITING -> IMPLEMENT -> TEST -> REVIEW -> DONE
    """
    # Orchestration phase (main agent only - never leaves until complete)
    ORCHESTRATE = "orchestrate"    # Coordinate subagents, manage queue
    # Optional discovery phases
    INTAKE = "intake"              # Gather requirements (no editing)
    DESIGN = "design"              # Write spec, decompose into task_queue
    # TDD loop phases
    TEST_WRITING = "test_writing"  # Write tests first (the spec)
    IMPLEMENT = "implement"        # Make tests pass
    TEST = "test"                  # Run pytest, lint, coverage
    REVIEW = "review"              # Address Greptile comments
    DONE = "done"


# Tools allowed in each phase
PHASE_TOOLS = {
    Phase.ORCHESTRATE: {
        # Orchestrate phase: coordinate workers, read queue state, spawn subagents
        # NO editing, native__bash allowed but evaluation commands filtered (see is_tool_allowed)
        "allowed": {"Read", "Task", "TodoWrite", "TaskOutput", "Glob", "Grep", "native__bash"},
        "blocked": {"Edit", "Write", "NotebookEdit", "Bash"},
    },
    Phase.INTAKE: {
        # Intake phase: gather requirements, research, no editing
        # bash allowed with whitelist (iterate_workflow.py only) via mcp router
        "allowed": {"Read", "Glob", "Grep", "WebSearch", "WebFetch", "Task", "bash"},
        "blocked": {"Edit", "Write", "Bash"},
    },
    Phase.DESIGN: {
        # Design phase: write spec, plan document
        "allowed": {"Read", "Glob", "Grep", "Write", "native__bash", "Task"},
        "blocked": {"Bash"},
    },
    Phase.TEST_WRITING: {
        "allowed": {"Read", "Glob", "Grep", "Edit", "Write", "native__bash"},
        "blocked": {"Bash"},
    },
    Phase.IMPLEMENT: {
        "allowed": {"Read", "Glob", "Grep", "Edit", "Write", "native__bash"},
        "blocked": {"Bash"},
    },
    Phase.TEST: {
        # Test phase: run verification only, no editing
        "allowed": {"Read", "Glob", "Grep", "native__bash"},
        "blocked": {"Edit", "Write", "Bash"},
    },
    Phase.REVIEW: {
        # Review phase: fix issues from Greptile comments
        "allowed": {"Read", "Glob", "Grep", "Edit", "Write", "native__bash"},
        "blocked": {"Bash"},
    },
    Phase.DONE: {
        "allowed": {"Read", "Glob", "Grep", "native__bash", "Edit", "Write", "Task"},
        "blocked": {"Bash"},
    },
}

# Per-phase native__bash command whitelist
# Each phase only allows specific commands via native__bash. None means all allowed.
PHASE_BASH_WHITELIST = {
    Phase.INTAKE: {"iterate_workflow.py"},
    Phase.DESIGN: {"iterate_workflow.py"},
    Phase.TEST_WRITING: {"iterate_workflow.py", "pytest"},
    Phase.IMPLEMENT: {"iterate_workflow.py", "pytest", "ruff", "mypy"},
    Phase.TEST: {"iterate_workflow.py", "pytest", "ruff", "mypy", "coverage"},
    Phase.REVIEW: {"iterate_workflow.py", "pytest", "ruff", "mypy", "coverage", "git", "gh"},
    Phase.ORCHESTRATE: {"iterate_workflow.py", "gh"},
    Phase.DONE: None,  # All commands allowed
}

# ============================================================================
# WORKFLOW ENGINE INTEGRATION
# ============================================================================

# Define phases using WorkflowPhase for base class compatibility
ITERATE_PHASES = {
    "orchestrate": WorkflowPhase(
        name="orchestrate",
        allowed_tools=frozenset({"Read", "Task", "TodoWrite", "TaskOutput", "Glob", "Grep", "native__bash"}),
        blocked_tools=frozenset({"Edit", "Write", "NotebookEdit", "Bash"}),
    ),
    "intake": WorkflowPhase(
        name="intake",
        allowed_tools=frozenset({"Read", "Glob", "Grep", "WebSearch", "WebFetch", "Task", "bash"}),
        blocked_tools=frozenset({"Edit", "Write", "Bash"}),
    ),
    "design": WorkflowPhase(
        name="design",
        allowed_tools=frozenset({"Read", "Glob", "Grep", "Write", "native__bash", "Task"}),
        blocked_tools=frozenset({"Bash"}),
    ),
    "test_writing": WorkflowPhase(
        name="test_writing",
        allowed_tools=frozenset({"Read", "Glob", "Grep", "Edit", "Write", "native__bash"}),
        blocked_tools=frozenset({"Bash"}),
    ),
    "implement": WorkflowPhase(
        name="implement",
        allowed_tools=frozenset({"Read", "Glob", "Grep", "Edit", "Write", "native__bash"}),
        blocked_tools=frozenset({"Bash"}),
    ),
    "test": WorkflowPhase(
        name="test",
        allowed_tools=frozenset({"Read", "Glob", "Grep", "native__bash"}),
        blocked_tools=frozenset({"Edit", "Write", "Bash"}),
        requires_verification=True,
    ),
    "review": WorkflowPhase(
        name="review",
        allowed_tools=frozenset({"Read", "Glob", "Grep", "Edit", "Write", "native__bash"}),
        blocked_tools=frozenset({"Bash"}),
    ),
    "done": WorkflowPhase(
        name="done",
        allowed_tools=frozenset({"Read", "Glob", "Grep", "native__bash", "Edit", "Write", "Task"}),
        blocked_tools=frozenset({"Bash"}),
    ),
}

# Define transitions between phases
ITERATE_TRANSITIONS = {
    "intake": PhaseTransition(from_phase="intake", to_phase="design"),
    "design": PhaseTransition(from_phase="design", to_phase="orchestrate"),
    "test_writing": PhaseTransition(from_phase="test_writing", to_phase="implement"),
    "implement": PhaseTransition(from_phase="implement", to_phase="test"),
    "test": PhaseTransition(
        from_phase="test",
        to_phase="review",
        kickback_map={
            KickbackReason.TESTS_FAILED: "implement",
            KickbackReason.LINT_FAILED: "implement",
            KickbackReason.COVERAGE_LOW: "test_writing",
        }
    ),
    "review": PhaseTransition(
        from_phase="review",
        to_phase="done",
        kickback_map={
            KickbackReason.NEW_COMMENTS: "implement",
        }
    ),
}

# Workflow definition for the iterate workflow
ITERATE_DEFINITION = WorkflowDefinition(
    name="iterate",
    phases=ITERATE_PHASES,
    transitions=ITERATE_TRANSITIONS,
    initial_phase="orchestrate",
    max_iterations=5,
)


class IterateWorkflow(WorkflowEngine):
    """TDD-focused workflow engine with bash command whitelist support.

    Extends WorkflowEngine with:
    - Per-phase bash command whitelisting
    - MCP tool name normalization
    - Backward-compatible function signatures
    """

    def __init__(self):
        super().__init__(ITERATE_DEFINITION, workflow_id="iterate")

    def is_tool_allowed(
        self,
        tool_name: str,
        command: Optional[str] = None,
        file_path: Optional[str] = None
    ) -> tuple[bool, str]:
        """Check if tool is allowed in current phase with bash whitelist support.

        Extends base class with:
        - MCP tool name normalization
        - Per-phase bash command whitelist
        - Git commit/push coverage requirements
        """
        # Normalize MCP router prefix
        if tool_name.startswith("mcp__router__"):
            tool_name = tool_name[len("mcp__router__"):]

        phase = self.get_phase()
        if phase is None:
            # No active workflow - block editing tools
            if tool_name in EDITING_TOOLS:
                return False, f"[BLOCKED] No active workflow. Start /iterate to use {tool_name}."
            return True, "No active workflow"

        # Get Phase enum for whitelist lookup
        try:
            phase_enum = Phase(phase)
        except ValueError:
            phase_enum = Phase.DONE

        phase_def = self.definition.get_phase(phase)
        if not phase_def:
            return True, f"Unknown phase: {phase}"

        # Check blocked list first
        if tool_name in phase_def.blocked_tools:
            return False, f"[BLOCKED] {tool_name} not allowed in {phase} phase. Complete current phase before using this tool."

        # Check native__bash commands against per-phase whitelist
        if tool_name == "native__bash" and command:
            cmd_lower = command.strip().lower()
            whitelist = PHASE_BASH_WHITELIST.get(phase_enum)

            # If whitelist is None (DONE phase), all commands allowed
            if whitelist is not None:
                # Split on shell operators to check each part
                parts = re.split(r'\s*(?:;|&&|\|\||&|\|)\s*', cmd_lower)

                for part in parts:
                    part = part.strip()
                    if not part:
                        continue

                    # Get base command
                    part_words = part.split()
                    base_cmd = part_words[0] if part_words else ""

                    # Check if allowed
                    part_allowed = False
                    for pattern in whitelist:
                        if pattern == "iterate_workflow.py":
                            if "iterate_workflow.py" in part:
                                part_allowed = True
                                break
                        else:
                            if base_cmd == pattern:
                                part_allowed = True
                                break

                    if not part_allowed:
                        return False, f"[BLOCKED] Command '{base_cmd}' not allowed in {phase} phase. Allowed: {', '.join(sorted(whitelist))}"

            # Git commit/push coverage check for REVIEW phase
            is_git_cmd = cmd_lower.startswith("git ") or cmd_lower == "git"
            if is_git_cmd and phase_enum == Phase.REVIEW:
                cmd_parts = cmd_lower.split()
                is_commit_or_push = any(p in ["commit", "push"] for p in cmd_parts)
                if is_commit_or_push:
                    state = self.get_state() or {}
                    coverage_ok = state.get("coverage_ok")
                    if coverage_ok is None:
                        return False, "[BLOCKED] Run tests and record coverage before commit/push"
                    if not coverage_ok:
                        return False, "[BLOCKED] Coverage threshold not met - cannot commit/push"

        # Check if tool is allowed
        base_tool = tool_name.split("__")[-1] if "__" in tool_name else tool_name
        normalized_tool = MCP_TO_NATIVE.get(base_tool, base_tool)

        if normalized_tool in phase_def.allowed_tools:
            return True, ""
        if base_tool in phase_def.allowed_tools:
            return True, ""
        if tool_name in phase_def.allowed_tools:
            return True, ""

        # Not in allowed tools
        allowed_list = ", ".join(sorted(phase_def.allowed_tools))
        return False, f"[BLOCKED] {tool_name} not in allowed tools for {phase} phase. Allowed: {allowed_list}"


# Module-level workflow instance
_workflow: Optional[IterateWorkflow] = None


def _get_workflow() -> IterateWorkflow:
    """Get or create the module-level workflow instance."""
    global _workflow
    if _workflow is None:
        _workflow = IterateWorkflow()
    return _workflow







def _is_spec(text: str) -> bool:
    """Check if text looks like a structured spec.

    A spec has structure: headings, task lists, sections, file references.
    A vague request is short and lacks structure.

    Returns:
        True if text appears to be a spec, False if vague request.
    """
    import re

    # Short text is likely vague
    if len(text.split()) < 10:
        return False

    # Check for spec-like structure
    structure_patterns = [
        r'^#+\s',              # Markdown headings
        r'^\s*[-*]\s*\[[ x]\]', # Task lists
        r'^##\s+\w+',          # Section headers
        r'\b[\w/]+\.(py|js|ts|go|rs|java|cpp|h|json|yaml|md)\b',  # File paths
        r'```',                # Code blocks
    ]

    for pattern in structure_patterns:
        if re.search(pattern, text, re.MULTILINE | re.IGNORECASE):
            return True

    return False


def _resolve_input(value: str, file_ext: str) -> tuple[str, bool]:
    """Resolve input to content and whether it was a file.

    Args:
        value: File path or inline content
        file_ext: Expected extension (.queue or .spec)

    Returns:
        (content, is_file) tuple
    """
    if value.endswith(file_ext):
        path = Path(value)
        if path.exists():
            return path.read_text(), True
        raise FileNotFoundError(f"File not found: {value}")
    return value, False


def start(
    task: str,
    spec: Optional[str] = None,
    queue: Optional[str] = None,
    max_iterations: int = 5,
    agent_id: Optional[str] = None,
) -> dict:
    """Start a new iterate workflow.

    Args:
        task: Description of what to implement
        spec: Spec file path (.spec) or inline spec content
        queue: Queue file path (.queue) or inline JSON content
        max_iterations: Max loops before requiring user checkpoint
        agent_id: Agent identifier. None or "orchestrator" for persisted state,
                  any other value for in-memory subagent state.

    Returns:
        Current state

    Phase selection:
        - queue provided → load queue → ORCHESTRATE
        - spec provided → decompose to queue → ORCHESTRATE
        - task looks like spec → treat as inline spec → ORCHESTRATE
        - otherwise → ORCHESTRATE (orchestrator creates queue if needed)
    """
    # Use orchestrator for state management if no agent_id specified
    effective_agent_id = agent_id or "orchestrator"

    if queue:
        content, _ = _resolve_input(queue, ".queue")
        _load_queue_content(content)
    # Determine starting phase based on input type
    if queue:
        # Structured input: ready for orchestration
        starting_phase = Phase.ORCHESTRATE.value
        needs_intake = False
    else:
        # Main agent starts in ORCHESTRATE - ready to spawn subagents
        # Can kick back to INTAKE if needs context (then: INTAKE → DESIGN → ORCHESTRATE)
        # Main agent NEVER enters IMPLEMENT - only subagents do
        starting_phase = Phase.ORCHESTRATE.value
        needs_intake = False

    state = {
        "active": True,
        "task": task,
        "project_root": os.getcwd(),
        "phase": starting_phase,
        "needs_intake": needs_intake,
        "iteration": 0,
        "max_iterations": max_iterations,
        "mode": "iterate-tdd",
        "workflow_invoked": True,
        # Orchestration tracking (survives compaction)
        "task_queue": [],           # Tasks to be done
        "active_agents": {},        # agent_id -> {description, type, spawned_at}
        "completed_tasks": [],      # Finished task descriptions
        # Test/review results
        "tests_passed": None,
        "lint_passed": None,
        "coverage_ok": None,
        "review_status": None,
        "pr_number": None,
    }
    _set_state(state)
    _log("info", "Workflow started", task=task[:50], phase=Phase.ORCHESTRATE.value,
         agent_id=effective_agent_id)
    print_status_banner()
    return state


def _load_queue_content(content: str) -> list:
    """Load task queue from JSON content into memory.

    Returns:
        List of task dicts from the queue.
    """
    queue_data = json.loads(content)
    tasks = queue_data.get("tasks", [])
    _log("info", "Queue loaded", task_count=len(tasks))
    return tasks


def get_phase() -> Optional[Phase]:
    """Get current phase, or None if not active."""
    state = _get_state()
    if not state.get("active"):
        return None
    phase_str = state.get("phase")
    if phase_str:
        try:
            return Phase(phase_str)
        except ValueError:
            return None
    return None


def is_active() -> bool:
    """Check if iterate workflow is active."""
    state = _get_state()
    return state.get("active", False)


def verify_active(expected_phase: Optional[Phase] = None) -> None:
    """Verify workflow is still active and optionally in expected phase.

    Call this before critical operations to detect premature termination.

    Args:
        expected_phase: If provided, also verify we're in this phase.

    Raises:
        RuntimeError: If workflow is not active or not in expected phase.
    """
    state = _get_state()
    if not state:
        raise RuntimeError(
            "[WORKFLOW TERMINATED] No state found. "
            "Workflow must be restarted."
        )

    if not state.get("active"):
        raise RuntimeError(
            "[WORKFLOW TERMINATED] Workflow is no longer active. "
            f"Exit reason: {state.get('exit_reason', 'unknown')}. "
            "State may have been corrupted or workflow stopped externally."
        )

    if expected_phase is not None:
        current = Phase(state["phase"]) if state.get("phase") else None
        if current != expected_phase:
            raise RuntimeError(
                f"[WORKFLOW PHASE MISMATCH] Expected {expected_phase.value}, "
                f"got {current.value if current else 'None'}. "
                "Phase may have changed unexpectedly."
            )


def set_phase(phase: Phase) -> None:
    """Manually set phase (for kick-back scenarios).

    Validates transitions to prevent skipping phases:
    - From ORCHESTRATE: INTAKE or DONE for orchestrator; subagents can be assigned any phase
    - From IMPLEMENT: only TEST allowed (can't skip to DONE/REVIEW)
    - From TEST: REVIEW, IMPLEMENT, or TEST_WRITING allowed (not DONE directly)
    - From TEST_WRITING: only IMPLEMENT allowed
    - From REVIEW: DONE or IMPLEMENT allowed
    - From INTAKE/DESIGN: flexible (discovery phases)
    """
    state = _get_state()
    current_phase = state.get("phase")

    # Define valid transitions for TDD loop phases
    # ORCHESTRATE can assign any starting phase (for subagents)
    # Discovery phases (INTAKE, DESIGN) are flexible
    valid_transitions = {
        # TDD loop has strict transitions
        Phase.ORCHESTRATE.value: {Phase.INTAKE, Phase.DONE},
        Phase.IMPLEMENT.value: {Phase.TEST},
        Phase.TEST.value: {Phase.REVIEW, Phase.IMPLEMENT, Phase.TEST_WRITING},
        Phase.TEST_WRITING.value: {Phase.IMPLEMENT},
        Phase.REVIEW.value: {Phase.DONE, Phase.IMPLEMENT},
        # DONE is terminal
        Phase.DONE.value: {Phase.DONE},
    }

    # Validate transition only for TDD loop phases (strict enforcement)
    if current_phase and current_phase in valid_transitions:
        allowed = valid_transitions[current_phase]
        if phase not in allowed:
            allowed_names = ", ".join(p.value for p in allowed)
            raise RuntimeError(
                f"Cannot transition from {current_phase.upper()} to {phase.value}. "
                f"Valid transitions: {allowed_names}"
            )

    state["phase"] = phase.value
    _set_state(state)
    _print_phase_transition(current_phase or "none", phase.value)


def advance_phase() -> Optional[Phase]:
    """Advance to next phase based on current state.

    Phase transitions:
    - intake -> design
    - design -> orchestrate
    - orchestrate -> test_writing
    - test_writing -> implement
    - implement -> test
    - test -> review (if all pass) OR kick-back:
        - coverage_ok=False -> test_writing (need more tests)
        - tests_passed=False OR lint_passed=False -> implement (fix code)
    - review -> done (if clean) OR implement (if issues)

    Returns new phase or None if workflow ended.
    """
    state = _get_state()
    if not state.get("active"):
        exit_reason = state.get("exit_reason", "unknown")
        raise RuntimeError(
            f"[NO ACTIVE WORKFLOW] Cannot advance phase. "
            f"Exit reason: {exit_reason}. Start a new workflow with 'start' command."
        )

    current = Phase(state["phase"])

    # Enforce verification before advancing from certain phases
    if current == Phase.TEST:
        test_results = state.get("tests_passed")
        lint_results = state.get("lint_passed")
        coverage_results = state.get("coverage_ok")
        if test_results is None or lint_results is None or coverage_results is None:
            raise RuntimeError(
                "Cannot advance from TEST: must record test results first. "
                "Call set_test_results() before advancing."
            )
    elif current == Phase.REVIEW:
        if not state.get("review_status"):
            raise RuntimeError(
                "Cannot advance from REVIEW: must record review status first. "
                "Call set_review_status() before advancing."
            )

    # Print phase completion summary (OUTPUT.2)
    _print_phase_summary(current.value, state)

    if current == Phase.INTAKE:
        # Intake complete, go to design to create spec/queue
        state["phase"] = Phase.DESIGN.value

    elif current == Phase.DESIGN:
        # Design complete, move to orchestrate for subagent spawning
        state["phase"] = Phase.ORCHESTRATE.value

    elif current == Phase.ORCHESTRATE:
        # Orchestrator should NEVER advance - it stays here and spawns subagents
        # Subagents report phase completion, orchestrator coordinates
        raise RuntimeError(
            "Cannot advance from ORCHESTRATE. The orchestrator stays in this phase "
            "and spawns subagents (implementer) for TEST_WRITING, IMPLEMENT, etc. "
            "Use Task tool to spawn 'agent-swarm:implementer' subagent instead."
        )

    elif current == Phase.TEST_WRITING:
        # Tests written, now implement
        state["phase"] = Phase.IMPLEMENT.value

    elif current == Phase.IMPLEMENT:
        # Implementation done, now run tests
        state["phase"] = Phase.TEST.value

    elif current == Phase.TEST:
        # Check all test phase results
        tests_ok = state.get("tests_passed", False)
        lint_ok = state.get("lint_passed", False)
        coverage_ok = state.get("coverage_ok", False)

        if tests_ok and lint_ok and coverage_ok:
            # Everything passes, move to review
            state["phase"] = Phase.REVIEW.value
            # Save state first, then auto-fetch PR comments
            _set_state(state)
            pr = state.get("pr_number")
            if pr:
                _log("info", "Auto-fetching PR review comments", pr=pr)
                # Import here to avoid circular dependency issues
                refresh_review_status(pr)
        else:
            # Something failed, determine kick-back target
            state["iteration"] = state.get("iteration", 0) + 1

            if state["iteration"] >= state.get("max_iterations", 5):
                state["phase"] = Phase.DONE.value
                state["active"] = False
                state["exit_reason"] = "max_iterations"
            elif not coverage_ok:
                # Coverage too low -> need more tests
                state["phase"] = Phase.TEST_WRITING.value
            else:
                # Tests or lint failed -> fix code
                state["phase"] = Phase.IMPLEMENT.value

        # Reset test results for next round
        state["tests_passed"] = None
        state["lint_passed"] = None
        state["coverage_ok"] = None

    elif current == Phase.REVIEW:
        # Check review status AND that all PR comments are addressed
        review_clean = state.get("review_status") == "clean"
        comments_addressed = not is_review_blocked()

        if review_clean and comments_addressed:
            # No issues and all comments addressed, we're done!
            state["phase"] = Phase.DONE.value
            state["active"] = False
            state["exit_reason"] = "review_approved"
        else:
            # Issues to fix or comments unaddressed, back to implement
            state["iteration"] = state.get("iteration", 0) + 1
            if state["iteration"] >= state.get("max_iterations", 5):
                state["phase"] = Phase.DONE.value
                state["active"] = False
                state["exit_reason"] = "max_iterations"
            else:
                state["phase"] = Phase.IMPLEMENT.value
        # Reset review status for next round
        state["review_status"] = None

    _set_state(state)
    
    # Determine kickback reason for OUTPUT.5
    new_phase = state["phase"]
    kickback_reason = ""
    if new_phase == Phase.TEST_WRITING.value and current == Phase.TEST:
        kickback_reason = "Coverage below threshold - need more tests"
    elif new_phase == Phase.IMPLEMENT.value and current == Phase.TEST:
        if not state.get("tests_passed", True):
            kickback_reason = "Tests failed - fix implementation"
        elif not state.get("lint_passed", True):
            kickback_reason = "Lint errors - fix code style"
    elif new_phase == Phase.IMPLEMENT.value and current == Phase.REVIEW:
        kickback_reason = "Review issues found - address feedback"
    elif new_phase == Phase.DONE.value and state.get("exit_reason") == "max_iterations":
        kickback_reason = f"Max iterations ({state.get('max_iterations', 5)}) reached"
    
    # Print phase transition banner (OUTPUT.1, OUTPUT.5)
    _print_phase_transition(current.value, new_phase, kickback_reason)
    
    _log("info", "Phase transition", from_phase=current.value, to_phase=state["phase"],
         iteration=state.get("iteration", 0))

    # Notify loudly if workflow just ended
    if not state.get("active"):
        _notify_workflow_end(state.get("exit_reason", "unknown"), state.get("task", ""))

    return Phase(state["phase"]) if state.get("active") else None


def set_test_results(tests_passed: bool, lint_passed: bool, coverage_ok: bool) -> None:
    """Record all test phase results at once.

    Args:
        tests_passed: Did pytest pass?
        lint_passed: Did lint/type checks pass?
        coverage_ok: Is coverage above threshold?

    Raises:
        RuntimeError: If no active workflow.
    """
    if not is_active():
        raise RuntimeError("No active workflow - cannot record test results")

    # Warn loudly if lint failed
    if not lint_passed:
        _log("warning", "LINT FAILED: Agents must run and pass lint (ruff check .) before reporting success",
             tests=tests_passed, lint=lint_passed, coverage=coverage_ok)

    state = _get_state()
    state["tests_passed"] = tests_passed
    state["lint_passed"] = lint_passed
    state["coverage_ok"] = coverage_ok
    _set_state(state)
    _log("info", "Test results recorded", tests=tests_passed, lint=lint_passed, coverage=coverage_ok)


def set_review_status(clean: bool) -> None:
    """Record review status (no issues = clean).

    Raises:
        RuntimeError: If no active workflow.
    """
    if not is_active():
        raise RuntimeError("No active workflow - cannot record review status")
    state = _get_state()
    state["review_status"] = "clean" if clean else "issues"
    _set_state(state)
    _log("info", "Review status recorded", clean=clean)


def _cleanup_stale_outputs() -> None:
    """Clean up stale agent output files when workflow ends.

    Removes:
    - Agent output symlinks in /tmp/claude/*/tasks/
    """
    from pathlib import Path

    tmp_claude = Path("/tmp/claude")
    if not tmp_claude.exists():
        return

    cleaned = 0
    for project_dir in tmp_claude.iterdir():
        if not project_dir.is_dir():
            continue
        tasks_dir = project_dir / "tasks"
        if not tasks_dir.exists():
            continue
        try:
            for output_file in tasks_dir.glob("*.output"):
                try:
                    output_file.unlink()
                    cleaned += 1
                except Exception:
                    pass
        except Exception:
            pass

    if cleaned > 0:
        _log("info", "Cleaned stale agent outputs", count=cleaned)


def _notify_workflow_end(reason: str, task: str = "") -> None:
    """Output loud notification when workflow ends - impossible to miss."""

    # Clean up stale agent outputs
    _cleanup_stale_outputs()

    banner = f"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  ⚠️  WORKFLOW TERMINATED: {reason:<50} ║
║  Task: {task[:66]:<66} ║
║                                                                              ║
║  You are NO LONGER in /iterate mode. To continue:                            ║
║    python3 ~/.claude/plugins/agent-swarm/lib/iterate_workflow.py start "<task>" [max_iterations]           ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""
    print(banner)


def _print_phase_transition(from_phase: str, to_phase: str, reason: str = "") -> None:
    """Print phase transition banner with optional reason (OUTPUT.1, OUTPUT.5).
    
    Shows:
    - Clear from→to transition
    - Kickback reason when phase reverts
    - Queue status for context
    """
    
    # Determine if this is a kickback (revert to earlier phase)
    phase_order = ["intake", "design", "orchestrate", "test_writing", "implement", "test", "review", "done"]
    from_idx = phase_order.index(from_phase) if from_phase in phase_order else -1
    to_idx = phase_order.index(to_phase) if to_phase in phase_order else -1
    is_kickback = to_idx < from_idx and to_idx >= 0
    
    # Build banner
    arrow = "⟲" if is_kickback else "→"
    header = "KICKBACK" if is_kickback else "PHASE"
    
    lines = [
        f"┌─[{header}]─────────────────────────────────────────────────────────────┐",
        f"│  {from_phase.upper()} {arrow} {to_phase.upper():<54}│",
    ]
    
    if reason:
        lines.append(f"│  Reason: {reason:<58}│")
    
    # Add queue status if available
    queue_status = _format_queue_status()
    if queue_status:
        lines.append("│" + "─" * 70 + "│")
        for line in queue_status.split("\n")[:3]:  # First 3 lines of queue
            lines.append(f"│  {line:<66}│")
    
    lines.append("└" + "─" * 70 + "┘")
    
    print("\n".join(lines))


def _print_phase_summary(phase: str, state: dict) -> None:
    """Print summary of what was accomplished in a phase (OUTPUT.2).
    
    Called before transitioning to show phase completion status.
    """
    
    summaries = {
        "test_writing": "Tests written and ready for implementation",
        "implement": "Implementation complete, ready for testing",
        "test": _get_test_phase_summary(state),
        "review": _get_review_phase_summary(state),
        "intake": "Requirements gathered, ready for design",
        "design": "Design complete, ready for orchestration",
    }
    
    summary = summaries.get(phase, f"Phase {phase} complete")
    if callable(summary):
        summary = summary()
    
    print(f"[{phase.upper()}] ✓ {summary}")


def _get_test_phase_summary(state: dict) -> str:
    """Generate summary for TEST phase completion."""
    tests_ok = state.get("tests_passed", False)
    lint_ok = state.get("lint_passed", False)
    coverage_ok = state.get("coverage_ok", False)
    
    results = []
    results.append("✓ tests" if tests_ok else "✗ tests")
    results.append("✓ lint" if lint_ok else "✗ lint")
    results.append("✓ coverage" if coverage_ok else "✗ coverage")
    
    return f"Test results: {' | '.join(results)}"


def _get_review_phase_summary(state: dict) -> str:
    """Generate summary for REVIEW phase completion."""
    review_clean = state.get("review_status") == "clean"
    return "Review passed - no issues" if review_clean else "Review complete - issues found"


def stop(reason: str = "user_stopped") -> None:
    """Stop the iterate workflow.

    Enforces exit conditions:
    - Task queue must be empty (all tasks complete)
    - No active workers/subagents running

    Raises:
        RuntimeError: If exit conditions not met.
    """
    state = _get_state()
    task = state.get("task", "unknown")

    # Check exit conditions
    blockers = []

    # 1. Check task queue
    try:
        wq = _get_workflow_queue()
        if not wq.all_done():
            pending = [t for t in wq.queue.tasks.values()
                      if t.status.value in ("pending", "running")]
            blockers.append(f"Task queue not empty: {len(pending)} tasks pending/running")
    except Exception:
        pass  # No queue = no blocker

    # 2. Check active workers
    try:
        from worker_pool import get_active_workers
        active = get_active_workers()
        if active:
            blockers.append(f"Workers still active: {len(active)} agents running")
    except ImportError:
        pass  # worker_pool not available
    except Exception:
        pass

    if blockers:
        raise RuntimeError(
            "Cannot stop workflow - exit conditions not met:\n"
            + "\n".join(f"  - {b}" for b in blockers)
        )

    state["active"] = False
    state["exit_reason"] = reason
    _set_state(state)
    _log("info", "Workflow stopped", reason=reason)
    _notify_workflow_end(reason, task)


# Tools that require an active workflow to use
EDITING_TOOLS = {"Edit", "Write", "NotebookEdit"}


def is_tool_allowed(tool_name: str, command: str | None = None) -> tuple[bool, str]:
    """Check if a tool is allowed in current phase.

    Delegates to IterateWorkflow.is_tool_allowed() to avoid logic duplication.

    Args:
        tool_name: Name of the tool being invoked.
        command: For Bash tool, the command string (used for git/gh blocking).

    Returns:
        (allowed: bool, reason: str)
    """
    workflow = _get_workflow()
    return workflow.is_tool_allowed(tool_name, command=command)


def _format_queue_status() -> Optional[str]:
    """Format task queue status for display (OUTPUT.3, OUTPUT.4).

    Returns queue status string with progress indicators if queue has items.
    """
    try:
        from iterate_state import load_queue
        queue = load_queue()
        if not queue or not queue.tasks:
            return None

        pending = sum(1 for t in queue.tasks if t.status.value == "pending")
        active = sum(1 for t in queue.tasks if t.status.value == "active")
        done = sum(1 for t in queue.tasks if t.status.value == "done")
        total = len(queue.tasks)

        # Progress bar (OUTPUT.4)
        progress_pct = int((done / total) * 100) if total > 0 else 0
        progress_filled = progress_pct // 5  # 20 chars total
        progress_bar = "█" * progress_filled + "░" * (20 - progress_filled)

        lines = [
            f"Queue Progress: [{progress_bar}] {done}/{total} ({progress_pct}%)",
            f"  ⏳ {pending} pending | ▶ {active} active | ✓ {done} done"
        ]

        # Show up to 5 tasks with status indicators
        for task in list(queue.tasks)[:5]:
            if task.status.value == "active":
                icon = "▶"
                suffix = f" ({task.worker_id})" if hasattr(task, 'worker_id') and task.worker_id else ""
            elif task.status.value == "done":
                icon = "✓"
                suffix = ""
            else:
                icon = "○"
                deps = getattr(task, 'depends_on', None)
                suffix = f" (blocked by: {', '.join(deps)})" if deps else ""

            lines.append(f"  [{icon}] {task.id}: {task.description[:40]}{suffix}")

        if len(queue.tasks) > 5:
            lines.append(f"  ... and {len(queue.tasks) - 5} more")

        return "\n".join(lines)
    except Exception:
        return None


def print_status_banner(force: bool = True) -> None:
    """Print decorated status banner (OUTPUT.1, OUTPUT.3, OUTPUT.4).

    Shows current phase, iteration progress, task, and queue status.
    """
    state = _get_state()

    if not state.get("active") and not force:
        return

    phase = state.get("phase", "unknown")
    iteration = state.get("iteration", 0)
    max_iter = state.get("max_iterations", 5)
    task_desc = state.get("task", "No task")[:60]
    mode = state.get("mode", "")

    # Progress bar for iterations (OUTPUT.4)
    progress_pct = min(100, int((iteration / max_iter) * 100)) if max_iter > 0 else 0
    progress_filled = progress_pct // 5  # 20 chars total
    progress_bar = "\u2588" * progress_filled + "\u2591" * (20 - progress_filled)

    lines = [
        "\u250c\u2500[ITERATE]\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2510",
        f"\u2502  Phase: {phase.upper():<12} Iteration: {iteration}/{max_iter} [{progress_bar}] {progress_pct}%\u2502",
        f"\u2502  Task: {task_desc:<62}\u2502",
    ]

    if mode:
        lines.append(f"\u2502  Mode: {mode:<62}\u2502")

    # Queue status (OUTPUT.3)
    queue_status = _format_queue_status()
    if queue_status:
        lines.append("\u2502" + "\u2500" * 70 + "\u2502")
        for line in queue_status.split("\n"):
            lines.append(f"\u2502  {line:<66}\u2502")

    lines.append("\u2514" + "\u2500" * 70 + "\u2518")
    print("\n".join(lines))


def status() -> str:
    """Get human-readable status."""
    state = _get_state()
    if not state.get("active"):
        if state.get("exit_reason"):
            return f"[ITERATE] Completed: {state['exit_reason']}"
        return "[ITERATE] Not active"

    phase = state.get("phase", "unknown")
    iteration = state.get("iteration", 0) + 1
    max_iter = state.get("max_iterations", 5)
    task_desc = state.get("task", "No task")[:50]
    mode = state.get("mode", "")

    lines = [
        "[ITERATE] Active",
        f"  Task: {task_desc}",
        f"  Phase: {phase}",
        f"  Iteration: {iteration}/{max_iter}",
    ]

    if mode:
        lines.append(f"  Mode: {mode}")

    # Include queue status only in iterate-tdd mode
    if mode == "iterate-tdd":
        queue_status = _format_queue_status()
        if queue_status:
            lines.append("")
            for line in queue_status.split("\n"):
                lines.append(f"  {line}")

    return "\n".join(lines)


# ============================================================================
# INTAKE PHASE AUTOMATION
# ============================================================================


def add_requirement(requirement: str) -> None:
    """Add a requirement discovered during intake phase.

    Args:
        requirement: A requirement string to store.

    Raises:
        ValueError: If not in intake phase.
    """
    phase = get_phase()
    if phase != Phase.INTAKE:
        raise ValueError("add_requirement only allowed in intake phase")

    state = _get_state()
    if "requirements" not in state:
        state["requirements"] = []
    state["requirements"].append(requirement)
    _set_state(state)
    _log("info", "Requirement added", requirement=requirement[:50])


def get_requirements() -> list[str]:
    """Get all requirements gathered during intake.

    Returns:
        List of requirement strings.
    """
    state = _get_state()
    return state.get("requirements", [])


# ============================================================================
# DESIGN PHASE AUTOMATION
# ============================================================================


def set_spec_file(path: str) -> None:
    """Set the spec file path for design phase decomposition.

    Args:
        path: Absolute or relative path to the spec markdown file.
    """
    state = _get_state()
    state["spec_file"] = path
    _set_state(state)
    _log("info", "Spec file set", path=path)


# ============================================================================
# REVIEW PHASE AUTOMATION
# ============================================================================


def _get_workflow_queue():
    """Get or create WorkflowQueue instance."""
    from workflow_queue import WorkflowQueue
    state = _get_state()
    pr_id = state.get("pr_id", "current")
    return WorkflowQueue(pr_id=pr_id)


def add_review_comment(comment: dict) -> dict:
    """Add a PR comment as a review task.

    Args:
        comment: Dict with 'id', 'body', and optionally 'severity', 'path'.

    Returns:
        The created task dictionary.

    Raises:
        ValueError: If not in review phase.
    """
    phase = get_phase()
    if phase != Phase.REVIEW:
        raise ValueError("add_review_comment only allowed in review phase")

    wq = _get_workflow_queue()
    task = wq.add_pr_comment(comment)

    _log("info", "Review comment added", comment_id=comment.get("id"))
    return {
        "id": task.id,
        "description": task.description,
        "status": task.status.value,
    }


def get_pending_review_tasks() -> list[dict]:
    """Get all unaddressed PR comment tasks.

    Returns:
        List of task dictionaries that are still pending.
    """
    wq = _get_workflow_queue()
    tasks = wq.get_unaddressed_comments()
    return [
        {"id": t.id, "description": t.description, "status": t.status.value}
        for t in tasks
    ]


def mark_review_task_done(task_id: str, result: Optional[dict] = None) -> None:
    """Mark a review task as completed.

    Args:
        task_id: ID of the task to complete.
        result: Optional result metadata.
    """
    wq = _get_workflow_queue()
    wq.mark_done(task_id, result)
    _log("info", "Review task completed", task_id=task_id)


def is_review_blocked() -> bool:
    """Check if review phase advancement is blocked.

    Returns:
        True if there are unaddressed PR comments.
    """
    wq = _get_workflow_queue()
    return not wq.can_commit()


def set_pr_number(pr_number: int) -> None:
    """Set the PR number for review status polling.

    Args:
        pr_number: The GitHub PR number to track.
    """
    if not is_active():
        raise RuntimeError("Cannot set PR number: no active workflow")

    state = _get_state()
    state["pr_number"] = pr_number
    _set_state(state)
    _log("info", "PR number set", pr_number=pr_number)


def get_pr_number() -> Optional[int]:
    """Get the stored PR number for review polling.

    Returns:
        The PR number if set, None otherwise.
    """
    state = _get_state()
    return state.get("pr_number")


def fetch_pr_review_status(pr_number: int) -> list[dict]:
    """Fetch unresolved PR review comments from GitHub.

    Uses `gh` CLI to fetch review comments for the given PR.
    Filters out resolved comments.

    Args:
        pr_number: The GitHub PR number to check.

    Returns:
        List of unresolved comment dictionaries with 'id', 'body', etc.
    """
    import subprocess

    try:
        # Fetch PR review comments using gh CLI
        result = subprocess.run(
            ["gh", "pr", "view", str(pr_number), "--json", "reviews,comments",
             "--jq", '.reviews[].comments[]? // .comments[] | select(.isResolved != true) | {id: .id, body: .body, path: .path, isResolved: .isResolved}'],
            capture_output=True, text=True, timeout=30
        )

        if result.returncode != 0:
            _log("warning", "gh pr view failed", pr=pr_number, stderr=result.stderr)
            return []

        # Parse JSON output - handle both JSON array and line-by-line format
        stdout = result.stdout.strip()
        if not stdout:
            return []

        comments = []
        try:
            # First try parsing as JSON array
            parsed = json.loads(stdout)
            if isinstance(parsed, list):
                for comment in parsed:
                    if isinstance(comment, dict) and not comment.get("isResolved", False):
                        comments.append(comment)
            elif isinstance(parsed, dict):
                # Single object
                if not parsed.get("isResolved", False):
                    comments.append(parsed)
        except json.JSONDecodeError:
            # Fall back to line-by-line parsing (jq output format)
            for line in stdout.split('\n'):
                if line:
                    try:
                        comment = json.loads(line)
                        if isinstance(comment, dict) and not comment.get("isResolved", False):
                            comments.append(comment)
                    except json.JSONDecodeError:
                        continue

        _log("info", "Fetched PR comments", pr=pr_number, count=len(comments))
        return comments

    except subprocess.TimeoutExpired:
        _log("error", "gh pr view timed out", pr=pr_number)
        return []
    except FileNotFoundError:
        _log("error", "gh CLI not found")
        return []


def refresh_review_status(pr_number: Optional[int] = None) -> int:
    """Refresh review queue by fetching latest PR comments.

    Fetches unresolved comments from GitHub and adds any new ones
    to the review task queue.

    Args:
        pr_number: PR number to fetch, or None to use stored number.

    Returns:
        Number of new comments added to queue.
    """
    if pr_number is None:
        pr_number = get_pr_number()

    if pr_number is None:
        _log("warning", "No PR number available for refresh")
        return 0

    phase = get_phase()
    if phase != Phase.REVIEW:
        _log("warning", "refresh_review_status called outside review phase")
        return 0

    comments = fetch_pr_review_status(pr_number)

    # Add new comments to queue
    added = 0
    for comment in comments:
        try:
            add_review_comment(comment)
            added += 1
        except Exception as e:
            # Comment might already exist in queue
            _log("debug", "Could not add comment", comment_id=comment.get("id"), error=str(e))

    _log("info", "Review status refreshed", pr=pr_number, added=added)
    return added


def is_orchestration_complete() -> bool:
    """Check if orchestration is complete.

    Returns True when:
    1. Workflow is active AND in ORCHESTRATE phase, AND
    2. Task queue has no pending tasks, AND
    3. No active workers

    This is the exit condition for ORCHESTRATE phase.

    Returns:
        True if orchestration is complete, False otherwise.
    """
    if not is_active():
        return False

    phase = get_phase()
    if phase != Phase.ORCHESTRATE:
        return False

    # Check worker pool status
    try:
        from worker_pool import is_complete as worker_pool_is_complete

        # Load queue to check if empty
        wq = _get_workflow_queue()
        queue_empty = wq.all_done()

        return worker_pool_is_complete(queue_empty=queue_empty)
    except ImportError:
        # worker_pool not available - check queue only
        wq = _get_workflow_queue()
        return wq.all_done()
    except Exception:
        # Graceful degradation - return False if any error
        return False


# CLI interface
if __name__ == "__main__":
    import sys

    def usage():
        print("Usage: python iterate_workflow.py <command> [args]")
        print()
        print("Commands:")
        print("  start <task> [options]   Start new workflow")
        print("    Options:")
        print("      --spec=<path>        Spec file (.spec) or inline content")
        print("      --queue=<path>       Queue file (.queue) or inline JSON")
        print("      --max-iter=N         Max iterations (default: 5)")
        print("      --agent-id=<id>      Agent ID (default: orchestrator)")
        print("  status                   Show current status")
        print("  phase                    Show current phase")
        print("  advance                  Advance to next phase")
        print("  test <t> <l> <c>         Record test results (1=pass, 0=fail)")
        print("                           t=tests, l=lint, c=coverage")
        print("  review <clean>           Record review status (1=clean, 0=issues)")
        print("  set-phase <phase>        Manually set phase (intake, design, orchestrate,")
        print("                           test_writing, implement, test, review, done)")
        print("  is-spec <text>           Check if text looks like a spec")
        print("  stop                     Stop workflow")

    COMMANDS = {"start", "status", "phase", "advance", "test", "review", "stop", "set-phase", "is-spec", "help"}

    if len(sys.argv) < 2:
        # No args - auto-start if not active, otherwise show status
        if not is_active():
            start("Unspecified task")
        print(status())
        sys.exit(0)

    cmd = sys.argv[1]

    # Auto-start if first arg isn't a known command (treat as task description)
    if cmd not in COMMANDS:
        task = " ".join(sys.argv[1:])
        start(task)
        print(status())
        sys.exit(0)

    if cmd == "start":
        # Parse options
        task_parts = []
        spec = None
        queue = None
        max_iter = 5
        agent_id = None

        for arg in sys.argv[2:]:
            if arg.startswith("--spec="):
                spec = arg.split("=", 1)[1]
            elif arg.startswith("--queue="):
                queue = arg.split("=", 1)[1]
            elif arg.startswith("--max-iter="):
                max_iter = int(arg.split("=")[1])
            elif arg.startswith("--agent-id="):
                agent_id = arg.split("=", 1)[1]
            else:
                task_parts.append(arg)

        task = " ".join(task_parts) if task_parts else "Unspecified task"
        start(task, spec=spec, queue=queue, max_iterations=max_iter, agent_id=agent_id)
        print(status())
    elif cmd == "status":
        print_status_banner()
    elif cmd == "phase":
        phase = get_phase()
        print(phase.value if phase else "none")
    elif cmd == "advance":
        new_phase = advance_phase()
        if new_phase:
            print(f"Advanced to: {new_phase.value}")
        else:
            state = _get_state()
            print(f"Workflow ended: {state.get('exit_reason', 'done')}")
    elif cmd == "test":
        if len(sys.argv) < 5:
            print("Usage: test <tests_passed> <lint_passed> <coverage_ok>")
            print("       Use 1 for pass, 0 for fail")
            sys.exit(1)
        tests = sys.argv[2] == "1"
        lint = sys.argv[3] == "1"
        coverage = sys.argv[4] == "1"
        set_test_results(tests, lint, coverage)
        print(f"Recorded: tests={tests}, lint={lint}, coverage={coverage}")
    elif cmd == "review":
        if len(sys.argv) < 3:
            print("Usage: review <clean>  (1=clean, 0=issues)")
            sys.exit(1)
        clean = sys.argv[2] == "1"
        set_review_status(clean)
        print(f"Recorded: review {'clean' if clean else 'has issues'}")
    elif cmd == "stop":
        stop()
        print("Stopped")
    elif cmd == "set-phase":
        if len(sys.argv) < 3:
            print("Usage: set-phase <phase>")
            print("       Phases: intake, design, orchestrate, test_writing, implement, test, review, done")
            sys.exit(1)
        phase_name = sys.argv[2].lower()
        try:
            phase = Phase(phase_name)
            set_phase(phase)
            print(f"Phase set to: {phase.value}")
        except ValueError:
            print(f"Invalid phase: {phase_name}")
            print("Valid phases: intake, design, orchestrate, test_writing, implement, test, review, done")
            sys.exit(1)
    elif cmd == "is-spec":
        if len(sys.argv) < 3:
            print("Usage: is-spec <text>")
            sys.exit(1)
        text = " ".join(sys.argv[2:])
        print(f"Is spec: {_is_spec(text)}")
    elif cmd == "help":
        usage()
    else:
        print(f"Unknown command: {cmd}")
        usage()
        sys.exit(1)
