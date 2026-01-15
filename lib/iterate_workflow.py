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
from pathlib import Path
from typing import Optional
from enum import Enum

# Allow override via environment variable for test isolation
_state_dir_override = os.environ.get("ITERATE_STATE_DIR")
STATE_DIR = Path(_state_dir_override) if _state_dir_override else Path.home() / ".claude/plugins/agent-swarm/.state"
LOG_FILE = STATE_DIR / "iterate.log"

# Import state manager for centralized state handling
import state_manager

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
        # NO editing, Bash allowed but evaluation commands filtered (see is_tool_allowed)
        "allowed": {"Read", "Task", "TodoWrite", "TaskOutput", "Glob", "Grep", "Bash"},
        "blocked": {"Edit", "Write", "NotebookEdit"},
    },
    Phase.INTAKE: {
        # Intake phase: gather requirements, research, no editing
        "allowed": {"Read", "Glob", "Grep", "WebSearch", "WebFetch", "Task"},
        "blocked": {"Edit", "Write"},
    },
    Phase.DESIGN: {
        # Design phase: write spec, run decomposer
        "allowed": {"Read", "Glob", "Grep", "Write", "Bash", "Task"},
        "blocked": set(),
    },
    Phase.TEST_WRITING: {
        "allowed": {"Read", "Glob", "Grep", "Edit", "Write", "Bash"},
        "blocked": set(),
    },
    Phase.IMPLEMENT: {
        "allowed": {"Read", "Glob", "Grep", "Edit", "Write", "Bash"},
        "blocked": set(),
    },
    Phase.TEST: {
        # Test phase: run verification only, no editing
        "allowed": {"Read", "Glob", "Grep", "Bash"},
        "blocked": {"Edit", "Write"},
    },
    Phase.REVIEW: {
        # Review phase: fix issues from Greptile comments
        "allowed": {"Read", "Glob", "Grep", "Edit", "Write", "Bash"},
        "blocked": set(),
    },
    Phase.DONE: {
        "allowed": {"Read", "Glob", "Grep", "Bash", "Edit", "Write", "Task"},
        "blocked": set(),
    },
}




def _load_config() -> dict:
    """Load workflow config."""
    config_path = Path(__file__).parent.parent / "config" / "workflow.json"
    if config_path.exists():
        try:
            return json.loads(config_path.read_text())
        except json.JSONDecodeError:
            pass
    return {}


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
        - vague request → INTAKE (gather requirements)
    """
    # Use orchestrator for state management if no agent_id specified
    effective_agent_id = agent_id or "orchestrator"

    needs_intake = True

    if queue:
        content, _ = _resolve_input(queue, ".queue")
        _load_queue_content(content)
        needs_intake = False
        initial_phase = Phase.ORCHESTRATE
    elif spec:
        content, _ = _resolve_input(spec, ".spec")
        _decompose_spec_content(content)
        needs_intake = False
        initial_phase = Phase.ORCHESTRATE
    elif _is_spec(task):
        _decompose_spec_content(task)
        needs_intake = False
        initial_phase = Phase.ORCHESTRATE
    else:
        initial_phase = Phase.INTAKE

    state = {
        "active": True,
        "task": task,
        "phase": initial_phase.value,
        "iteration": 0,
        "max_iterations": max_iterations,
        "mode": "iterate-tdd",
        "workflow_invoked": True,
        "needs_intake": needs_intake,
        "tests_passed": None,
        "lint_passed": None,
        "coverage_ok": None,
        "review_status": None,
        "pr_number": None,
    }
    state_manager.set_state("orchestrator", state)
    _log("info", "Workflow started", task=task[:50], phase=initial_phase.value,
         agent_id=effective_agent_id, needs_intake=needs_intake)
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


def _decompose_spec_content(content: str) -> None:
    """Decompose spec content into task queue."""
    # TODO: integrate with decomposer to create queue
    _log("info", "Spec decomposed", length=len(content))


def get_phase() -> Optional[Phase]:
    """Get current phase, or None if not active."""
    state = state_manager.get_state("orchestrator") or {}
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
    state = state_manager.get_state("orchestrator") or {}
    return state.get("active", False)


def verify_active(expected_phase: Optional[Phase] = None) -> None:
    """Verify workflow is still active and optionally in expected phase.

    Call this before critical operations to detect premature termination.

    Args:
        expected_phase: If provided, also verify we're in this phase.

    Raises:
        RuntimeError: If workflow is not active or not in expected phase.
    """
    state = state_manager.get_state("orchestrator") or {}
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
    """Manually set phase (for kick-back scenarios)."""
    state = state_manager.get_state("orchestrator") or {}
    state["phase"] = phase.value
    state_manager.set_state("orchestrator", state)


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
    state = state_manager.get_state("orchestrator") or {}
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

    if current == Phase.INTAKE:
        # Intake complete, always go to design
        state["phase"] = Phase.DESIGN.value

    elif current == Phase.DESIGN:
        # Design complete, move to orchestrate for subagent spawning
        state["phase"] = Phase.ORCHESTRATE.value

    elif current == Phase.ORCHESTRATE:
        # Orchestrate complete, move to TDD loop
        state["phase"] = Phase.TEST_WRITING.value

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
            state_manager.set_state("orchestrator", state)
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

    state_manager.set_state("orchestrator", state)
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
    state = state_manager.get_state("orchestrator") or {}
    state["tests_passed"] = tests_passed
    state["lint_passed"] = lint_passed
    state["coverage_ok"] = coverage_ok
    state_manager.set_state("orchestrator", state)
    _log("info", "Test results recorded", tests=tests_passed, lint=lint_passed, coverage=coverage_ok)


def set_review_status(clean: bool) -> None:
    """Record review status (no issues = clean).

    Raises:
        RuntimeError: If no active workflow.
    """
    if not is_active():
        raise RuntimeError("No active workflow - cannot record review status")
    state = state_manager.get_state("orchestrator") or {}
    state["review_status"] = "clean" if clean else "issues"
    state_manager.set_state("orchestrator", state)
    _log("info", "Review status recorded", clean=clean)


def _notify_workflow_end(reason: str, task: str = "") -> None:
    """Output loud notification when workflow ends - impossible to miss."""
    import sys
    banner = f"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  ⚠️  WORKFLOW TERMINATED: {reason:<50} ║
║  Task: {task[:66]:<66} ║
║                                                                              ║
║  You are NO LONGER in /iterate mode. To continue:                            ║
║    python3 lib/iterate_workflow.py start "<task>" [max_iterations]           ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""
    print(banner, file=sys.stderr)


def stop(reason: str = "user_stopped") -> None:
    """Stop the iterate workflow."""
    state = state_manager.get_state("orchestrator") or {}
    task = state.get("task", "unknown")
    state["active"] = False
    state["exit_reason"] = reason
    state_manager.set_state("orchestrator", state)
    _log("info", "Workflow stopped", reason=reason)
    _notify_workflow_end(reason, task)


# Tools that require an active workflow to use
EDITING_TOOLS = {"Edit", "Write", "NotebookEdit"}


def is_tool_allowed(tool_name: str, command: str | None = None) -> tuple[bool, str]:
    """Check if a tool is allowed in current phase.

    Args:
        tool_name: Name of the tool being invoked.
        command: For Bash tool, the command string (used for git/gh blocking).

    Returns:
        (allowed: bool, reason: str)
    """
    phase = get_phase()
    if phase is None:
        # No active workflow - block editing tools (BUG-PHASE-MISUSE fix)
        if tool_name in EDITING_TOOLS:
            return False, f"[BLOCKED] No active workflow. Start /iterate to use {tool_name}."
        return True, "No active workflow"

    phase_config = PHASE_TOOLS.get(phase, PHASE_TOOLS[Phase.DONE])

    if tool_name in phase_config["blocked"]:
        return False, f"[BLOCKED] {tool_name} not allowed in {phase.value} phase. Run tests first."

    # Check for git/gh commands in Bash (WORKFLOW.5)
    if tool_name == "Bash" and command:
        cmd_lower = command.strip().lower()
        is_git_cmd = cmd_lower.startswith("git ") or cmd_lower == "git"
        is_gh_cmd = cmd_lower.startswith("gh ")

        if is_git_cmd or is_gh_cmd:
            # Git/gh only allowed in REVIEW phase
            if phase != Phase.REVIEW:
                return False, f"[BLOCKED] git/gh commands only allowed in review phase. Current: {phase.value}"

            # In REVIEW phase, check coverage requirement for commit/push (WORKFLOW.1)
            state = state_manager.get_state("orchestrator") or {}
            # Use word-boundary matching to avoid false positives like "commitfile.txt"
            cmd_parts = cmd_lower.split()
            is_commit_or_push = any(part in ["commit", "push"] for part in cmd_parts)

            if is_commit_or_push:
                coverage_ok = state.get("coverage_ok")
                if coverage_ok is None:
                    return False, "[BLOCKED] Run tests and record coverage before commit/push"
                if not coverage_ok:
                    return False, "[BLOCKED] Coverage threshold not met - cannot commit/push"

        # Check for evaluation commands in ORCHESTRATE phase
        if phase == Phase.ORCHESTRATE:
            # Define evaluation command patterns
            evaluation_patterns = [
                "pytest",
                "python -m pytest",
                "python3 -m pytest",
                "ruff check",
                "ruff .",
                "mypy",
                "coverage",
                "black --check",
            ]

            # Check if command matches any evaluation pattern
            for pattern in evaluation_patterns:
                if pattern in cmd_lower:
                    return False, (
                        f"[BLOCKED] In ORCHESTRATE phase, spawn a test agent instead of running "
                        f"tests directly. Use Task tool to delegate evaluation work."
                    )

    # Allow MCP variants of allowed tools
    base_tool = tool_name.split("__")[-1] if "__" in tool_name else tool_name
    if base_tool in phase_config["allowed"]:
        return True, ""

    # Default allow if not explicitly blocked
    return True, ""


def _format_queue_status() -> Optional[str]:
    """Format task queue status for display.

    Returns queue status string if queue has items, None otherwise.
    """
    try:
        from iterate_state import load_queue
        queue = load_queue()
        if not queue or not queue.tasks:
            return None

        pending = sum(1 for t in queue.tasks if t.status.value == "pending")
        active = sum(1 for t in queue.tasks if t.status.value == "active")
        done = sum(1 for t in queue.tasks if t.status.value == "done")

        lines = [f"Queue: {pending} pending | {active} active | {done} done"]

        # Show up to 5 tasks with status indicators
        for task in list(queue.tasks)[:5]:
            if task.status.value == "active":
                icon = "▶"
                suffix = f" ({task.worker_id})" if hasattr(task, 'worker_id') and task.worker_id else ""
            elif task.status.value == "done":
                icon = "✓"
                suffix = ""
            else:
                icon = " "
                deps = getattr(task, 'depends_on', None)
                suffix = f" (blocked by: {', '.join(deps)})" if deps else ""

            lines.append(f"  [{icon}] {task.id}: {task.description[:40]}{suffix}")

        if len(queue.tasks) > 5:
            lines.append(f"  ... and {len(queue.tasks) - 5} more")

        return "\n".join(lines)
    except Exception:
        return None


def print_status_banner(force: bool = False) -> None:
    """Print decorated status banner.

    Only shows when in iterate-tdd mode (or force=True).
    """
    state = state_manager.get_state("orchestrator") or {}

    if not state.get("active"):
        return

    mode = state.get("mode", "")
    if not force and mode != "iterate-tdd":
        return

    phase = state.get("phase", "unknown")
    iteration = state.get("iteration", 0)
    max_iter = state.get("max_iterations", 5)
    task_desc = state.get("task", "No task")[:60]

    lines = [
        "[ITERATE] ═══════════════════════════════════════════════════════════════",
        f"  Phase: {phase.upper()} | Iteration: {iteration}/{max_iter}",
        f"  Task: {task_desc}",
    ]

    queue_status = _format_queue_status()
    if queue_status:
        lines.append("")
        for line in queue_status.split("\n"):
            lines.append(f"  {line}")

    lines.append("═══════════════════════════════════════════════════════════════════════")
    print("\n".join(lines))


def status() -> str:
    """Get human-readable status."""
    state = state_manager.get_state("orchestrator") or {}
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

    state = state_manager.get_state("orchestrator") or {}
    if "requirements" not in state:
        state["requirements"] = []
    state["requirements"].append(requirement)
    state_manager.set_state("orchestrator", state)
    _log("info", "Requirement added", requirement=requirement[:50])


def get_requirements() -> list[str]:
    """Get all requirements gathered during intake.

    Returns:
        List of requirement strings.
    """
    state = state_manager.get_state("orchestrator") or {}
    return state.get("requirements", [])


# ============================================================================
# DESIGN PHASE AUTOMATION
# ============================================================================


def set_spec_file(path: str) -> None:
    """Set the spec file path for design phase decomposition.

    Args:
        path: Absolute or relative path to the spec markdown file.
    """
    state = state_manager.get_state("orchestrator") or {}
    state["spec_file"] = path
    state_manager.set_state("orchestrator", state)
    _log("info", "Spec file set", path=path)


def decompose_spec_to_queue() -> list[dict]:
    """Decompose the spec file into task queue items.

    Uses the decomposer to parse the spec and create implementation tasks.

    Returns:
        List of task dictionaries created.

    Raises:
        ValueError: If not in design phase or no spec file set.
    """
    phase = get_phase()
    if phase != Phase.DESIGN:
        raise ValueError("decompose_spec_to_queue only allowed in design phase")

    state = state_manager.get_state("orchestrator") or {}
    spec_file = state.get("spec_file")
    if not spec_file:
        raise ValueError("No spec file set. Call set_spec_file() first.")

    # Import decomposer (in scripts directory)
    import sys
    scripts_dir = Path(__file__).parent.parent / "scripts"
    sys.path.insert(0, str(scripts_dir))
    from decomposer import decompose_spec

    # Generate a PR ID for task grouping
    pr_id = state.get("pr_id", "workflow-" + state.get("task", "default")[:20])

    tasks = decompose_spec(spec_file, pr_id, group_enums=True)

    # Store task count in state
    state["decomposed_task_count"] = len(tasks)
    state_manager.set_state("orchestrator", state)

    _log("info", "Spec decomposed", task_count=len(tasks), spec_file=spec_file)
    return tasks


# ============================================================================
# REVIEW PHASE AUTOMATION
# ============================================================================


def _get_workflow_queue():
    """Get or create WorkflowQueue instance."""
    from workflow_queue import WorkflowQueue
    state = state_manager.get_state("orchestrator") or {}
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

    state = state_manager.get_state("orchestrator") or {}
    state["pr_number"] = pr_number
    state_manager.set_state("orchestrator", state)
    _log("info", "PR number set", pr_number=pr_number)


def get_pr_number() -> Optional[int]:
    """Get the stored PR number for review polling.

    Returns:
        The PR number if set, None otherwise.
    """
    state = state_manager.get_state("orchestrator") or {}
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
        print("  is-spec <text>           Check if text looks like a spec")
        print("  stop                     Stop workflow")

    if len(sys.argv) < 2:
        print(status())
        sys.exit(0)

    cmd = sys.argv[1]

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
        print(status())
    elif cmd == "phase":
        phase = get_phase()
        print(phase.value if phase else "none")
    elif cmd == "advance":
        new_phase = advance_phase()
        if new_phase:
            print(f"Advanced to: {new_phase.value}")
        else:
            state = state_manager.get_state("orchestrator") or {}
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
