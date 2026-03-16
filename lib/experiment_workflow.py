"""Experiment workflow — autonomous experiment execution with eval gates.

Flow: read -> plan -> work -> eval -> journal -> decide -> [plan | done]
State persisted via DaemonClient.
"""

import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

lib_dir = Path(__file__).parent
if str(lib_dir) not in sys.path:
    sys.path.insert(0, str(lib_dir))

from daemon_client import DaemonClient, is_daemon_only_key  # noqa: E402
from errors import RouterError  # noqa: E402

WORKFLOW_ID = "experiment"

TRANSITIONS: dict[str, set[str]] = {
    "read": {"plan"},
    "plan": {"work"},
    "work": {"eval"},
    "eval": {"journal", "work"},
    "journal": {"decide"},
    "decide": {"plan", "done"},
}

ALL_PHASES: set[str] = set(TRANSITIONS.keys()) | {"done"}

DEFAULTS = {"max_iterations": 10, "max_agents": 4}


class ExperimentWorkflowError(Exception):
    """Error in experiment workflow logic."""


def _get_state() -> dict:
    with DaemonClient() as dc:
        return dc.workflow_get_state(WORKFLOW_ID) or {}


def _set_state(state: dict) -> None:
    with DaemonClient() as dc:
        if state.get("active") and not dc.workflow_is_active(WORKFLOW_ID):
            dc.workflow_start(WORKFLOW_ID, initial_state={"phase": state.get("phase", "read")})
        if "phase" in state:
            dc.workflow_advance_phase(WORKFLOW_ID, state["phase"])
        for key, value in state.items():
            if is_daemon_only_key(key):
                continue
            dc.workflow_set_value(WORKFLOW_ID, key, value)


def start_experiment(
    experiment_dir: str,
    task: str,
    max_iterations: Optional[int] = None,
    max_agents: Optional[int] = None,
) -> dict:
    """Start a new experiment workflow."""
    state = {
        "active": True,
        "task": task,
        "phase": "read",
        "experiment_dir": experiment_dir,
        "iteration": 0,
        "max_iterations": max_iterations or DEFAULTS["max_iterations"],
        "max_agents": max_agents or DEFAULTS["max_agents"],
        "best_metrics": {},
        "hypotheses_tested": [],
        "execution_mode": None,
        "environment": "local",
    }
    _set_state(state)
    return state


def stop(reason: str = "user_stopped") -> None:
    """Stop the experiment workflow."""
    state = _get_state()
    if not state:
        return
    state["active"] = False
    state["exit_reason"] = reason
    _set_state(state)


def get_phase() -> Optional[str]:
    state = _get_state()
    return state.get("phase") if state else None


def is_active() -> bool:
    state = _get_state()
    return bool(state and state.get("active"))


def advance_phase(target: str) -> dict:
    """Advance to target phase with validation."""
    state = _get_state()
    if not state or not state.get("active"):
        raise ExperimentWorkflowError("Workflow not active")

    current = state["phase"]

    if target not in ALL_PHASES:
        raise ExperimentWorkflowError(
            f"Unknown phase: {target}. Valid: {sorted(ALL_PHASES)}"
        )

    valid_targets = TRANSITIONS.get(current, set())
    if target not in valid_targets:
        raise ExperimentWorkflowError(
            f"Invalid transition: {current} -> {target}. "
            f"Valid targets from {current}: {sorted(valid_targets)}"
        )

    if current == "decide" and target == "plan":
        state["iteration"] = state.get("iteration", 0) + 1
        max_iter = state.get("max_iterations", DEFAULTS["max_iterations"])
        if state["iteration"] >= max_iter:
            state["active"] = False
            state["exit_reason"] = "max_iterations"
            state["phase"] = target
            _set_state(state)
            raise ExperimentWorkflowError(
                f"Max iterations ({max_iter}) reached"
            )

    state["phase"] = target

    if target == "done":
        state["active"] = False
        state["exit_reason"] = "success"

    _set_state(state)
    return state


def record_eval_result(metrics: dict, passed: bool) -> None:
    """Record eval results in workflow state."""
    state = _get_state()
    state["last_eval_passed"] = passed
    state["last_eval_metrics"] = metrics

    lower_is_better = set()
    for c in state.get("success_criteria", []):
        if c.get("comparison", ">=") in ("<=", "<"):
            lower_is_better.add(c["metric"])

    best = state.get("best_metrics", {})
    for k, v in metrics.items():
        if k not in best:
            best[k] = v
        elif k in lower_is_better:
            best[k] = min(best[k], v)
        else:
            best[k] = max(best[k], v)
    state["best_metrics"] = best
    _set_state(state)


def record_hypothesis(hypothesis: str, result: str) -> None:
    """Record a tested hypothesis."""
    state = _get_state()
    tested = state.get("hypotheses_tested", [])
    tested.append({
        "hypothesis": hypothesis,
        "result": result,
        "iteration": state.get("iteration", 0),
    })
    state["hypotheses_tested"] = tested
    _set_state(state)


def _print_status():
    state = _get_state()
    if not state:
        print("No experiment workflow active.")
        return
    print(f"Experiment: {state.get('task', '?')}")
    print(f"Phase: {state.get('phase', '?')}")
    print(f"Iteration: {state.get('iteration', 0)}/{state.get('max_iterations', '?')}")
    print(f"Active: {state.get('active', False)}")
    print(f"Mode: {state.get('execution_mode', '?')}")
    print(f"Environment: {state.get('environment', 'local')}")
    best = state.get("best_metrics", {})
    if best:
        print(f"Best metrics: {best}")


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Experiment workflow control")
    sub = parser.add_subparsers(dest="command")

    start_p = sub.add_parser("start", help="Start experiment workflow")
    start_p.add_argument("experiment_dir", help="Path to experiment directory")
    start_p.add_argument("task", help="Experiment description")
    start_p.add_argument("--max-iterations", type=int, default=None)

    sub.add_parser("status", help="Show workflow status")
    sub.add_parser("phase", help="Show current phase")

    adv_p = sub.add_parser("advance", help="Advance to next phase")
    adv_p.add_argument("target", help="Target phase")

    setp = sub.add_parser("set-phase", help="Force phase (testing only)")
    setp.add_argument("phase", help="Phase to set")

    sub.add_parser("stop", help="Stop workflow")

    args = parser.parse_args()

    if args.command == "start":
        start_experiment(args.experiment_dir, args.task,
                        max_iterations=args.max_iterations)
        print(f"Started experiment workflow: {args.task}")
    elif args.command == "status":
        _print_status()
    elif args.command == "phase":
        print(get_phase() or "No active workflow")
    elif args.command == "advance":
        try:
            advance_phase(args.target)
            print(f"Advanced to: {args.target}")
        except ExperimentWorkflowError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)
    elif args.command == "set-phase":
        state = _get_state()
        state["phase"] = args.phase
        _set_state(state)
        print(f"Phase set to: {args.phase}")
    elif args.command == "stop":
        stop()
        print("Workflow stopped.")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
