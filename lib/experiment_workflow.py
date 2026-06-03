"""Experiment workflow — autonomous experiment execution with eval gates.

Flow: read -> plan -> work -> eval -> journal -> decide -> [plan | done]
State persisted via DaemonClient. Phase transitions validated by daemon
against config/workflows/experiment.yaml.
"""

import sys
from pathlib import Path
from typing import Optional

lib_dir = Path(__file__).parent
if str(lib_dir) not in sys.path:
    sys.path.insert(0, str(lib_dir))

from daemon_client import DaemonClient, DaemonError, is_daemon_only_key  # noqa: E402

WORKFLOW_ID = "experiment"

DEFAULTS = {"max_iterations": 10, "max_agents": 4}


class ExperimentWorkflowError(Exception):
    """Error in experiment workflow logic."""


def _criteria_pass(criteria: list, metrics: dict) -> bool:
    """Decide whether eval metrics satisfy the success criteria.

    Uses primary-criteria passing when at least one criterion is marked
    primary; otherwise falls back to requiring ALL criteria to pass. This
    closes the no-primary bypass where CriteriaResult.passed (== primary_passed)
    is vacuously True when no criterion is primary, even if every criterion
    fails. Empty criteria -> no primary -> all_passed is vacuously True ->
    still passes (convention preserved).
    """
    import experiment_harness
    result = experiment_harness.check_criteria(criteria, metrics)
    has_primary = any(c.get("primary") for c in criteria)
    return result.passed if has_primary else result.all_passed


def _get_state() -> dict:
    with DaemonClient() as dc:
        return dc.workflow_get_state(WORKFLOW_ID) or {}


def _set_state(state: dict, advance_to: str | None = None) -> None:
    """Persist experiment state. Only calls workflow_advance_phase when advance_to is set."""
    with DaemonClient() as dc:
        started = False
        if state.get("active") and not dc.workflow_is_active(WORKFLOW_ID):
            dc.workflow_start(WORKFLOW_ID, initial_state={"phase": state.get("phase", "read")})
            started = True
        if advance_to is not None and not started:
            dc.workflow_advance_phase(WORKFLOW_ID, advance_to)
        for key, value in state.items():
            if is_daemon_only_key(key):
                continue
            dc.workflow_set_value(WORKFLOW_ID, key, value)


def _stop_daemon_workflow() -> None:
    """Stop the daemon workflow record, ignoring errors if already stopped."""
    with DaemonClient() as dc:
        try:
            dc.workflow_stop(WORKFLOW_ID)
        except (DaemonError, ConnectionError):
            pass


def start_experiment(
    experiment_dir: str,
    task: str,
    max_iterations: Optional[int] = None,
    max_agents: Optional[int] = None,
    success_criteria: Optional[list] = None,
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
        "success_criteria": success_criteria or [],
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
    _stop_daemon_workflow()


def get_phase() -> Optional[str]:
    state = _get_state()
    return state.get("phase") if state else None


def is_active() -> bool:
    state = _get_state()
    return bool(state and state.get("active"))


def advance_phase(target: str) -> dict:
    """Advance to target phase.

    Transition validation is delegated to the daemon (experiment.yaml config).
    Business logic (iteration counting, max_iterations) is handled here.
    """
    state = _get_state()
    if not state or not state.get("active"):
        raise ExperimentWorkflowError("Workflow not active")

    current = state["phase"]

    # Business logic: iteration counting on kickback
    if current == "decide" and target == "plan":
        state["iteration"] = state.get("iteration", 0) + 1
        max_iter = state.get("max_iterations", DEFAULTS["max_iterations"])
        if state["iteration"] >= max_iter:
            state["active"] = False
            state["exit_reason"] = "max_iterations"
            state["phase"] = target
            try:
                _set_state(state, advance_to=target)
            except DaemonError as e:
                raise ExperimentWorkflowError(str(e)) from e
            _stop_daemon_workflow()
            raise ExperimentWorkflowError(
                f"Max iterations ({max_iter}) reached"
            )

    # Hard gate: decide->done must independently re-verify success criteria.
    # Recompute from RECORDED metrics rather than trusting last_eval_passed
    # (claimed-vs-actual independent check, mirroring run_scorer). Empty
    # success_criteria preserves prior behavior (gate passes) by convention.
    if current == "decide" and target == "done":
        import experiment_harness
        criteria = state.get("success_criteria", [])
        if criteria:
            recorded = state.get("last_eval_metrics")
            if recorded is None:
                raise ExperimentWorkflowError(
                    "decide->done blocked: success criteria not met "
                    "(no eval result recorded)"
                )
            if not _criteria_pass(criteria, recorded):
                recheck = experiment_harness.check_criteria(criteria, recorded)
                raise ExperimentWorkflowError(
                    "decide->done blocked: success criteria not met "
                    f"(recomputed from recorded metrics: {recheck.details})"
                )

    state["phase"] = target

    if target == "done":
        state["active"] = False
        state["exit_reason"] = "success"

    try:
        _set_state(state, advance_to=target)
    except DaemonError as e:
        raise ExperimentWorkflowError(str(e)) from e

    if target == "done":
        _stop_daemon_workflow()

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


def run_eval_phase(eval_path: str = "eval/") -> dict:
    """Auto-run the eval harness during the eval phase.

    The engine runs the eval itself rather than trusting the model to
    self-report. Requires an active workflow in the "eval" phase. Runs the
    harness, checks the recorded metrics against the configured success
    criteria, records the result, and returns a structured summary.
    """
    import experiment_harness

    state = _get_state()
    if not state or not state.get("active"):
        raise ExperimentWorkflowError("Workflow not active")
    if state.get("phase") != "eval":
        raise ExperimentWorkflowError(
            f"run_eval_phase requires phase 'eval', got '{state.get('phase')}'"
        )

    exp_dir = state.get("experiment_dir")
    if not exp_dir:
        raise ExperimentWorkflowError("Workflow state missing 'experiment_dir'")

    result = experiment_harness.run_eval(Path(exp_dir), eval_path)
    success_criteria = state.get("success_criteria", [])
    criteria = experiment_harness.check_criteria(success_criteria, result.metrics)
    passed = _criteria_pass(success_criteria, result.metrics)
    record_eval_result(result.metrics, passed=passed)
    return {
        "metrics": result.metrics,
        "passed": passed,
        "criteria_details": criteria.details,
    }


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
        _set_state(state, advance_to=args.phase)
        print(f"Phase set to: {args.phase}")
    elif args.command == "stop":
        stop()
        print("Workflow stopped.")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
