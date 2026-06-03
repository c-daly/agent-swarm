"""Tests for experiment workflow state machine."""
import pytest
from unittest.mock import patch, MagicMock
from daemon_client import DaemonError


# Transition map matching config/workflows/experiment.yaml
_TRANSITIONS = {
    "read": {"plan"},
    "plan": {"work"},
    "work": {"eval"},
    "eval": {"journal", "work"},
    "journal": {"decide"},
    "decide": {"plan", "done"},
}


@pytest.fixture
def mock_daemon():
    """Mock DaemonClient that simulates daemon-side state separately from client state."""
    state = {}  # shared state dict returned by workflow_get_state
    daemon = {"phase": "", "active": False}  # daemon's own tracking

    mock_dc = MagicMock()
    mock_dc.workflow_get_state.return_value = state
    mock_dc.workflow_set_value.side_effect = lambda wf_id, k, v: state.update({k: v})

    def validate_advance(wf_id, phase):
        """Simulate daemon transition validation using daemon's own phase."""
        current = daemon["phase"]
        valid = _TRANSITIONS.get(current, set())
        if phase not in valid:
            raise DaemonError(
                code=-32603,
                message=f"Invalid transition: {current} -> {phase}. "
                        f"Valid targets: {sorted(valid)}",
            )
        daemon["phase"] = phase
        state["phase"] = phase

    def mock_start(wf_id, initial_state):
        p = initial_state.get("phase", "read")
        daemon["phase"] = p
        daemon["active"] = True
        state.update(initial_state)

    def mock_stop(wf_id):
        daemon["active"] = False
        return True

    def mock_is_active(wf_id):
        return daemon["active"]

    mock_dc.workflow_advance_phase.side_effect = validate_advance
    mock_dc.workflow_start.side_effect = mock_start
    mock_dc.workflow_stop.side_effect = mock_stop
    mock_dc.workflow_is_active.side_effect = mock_is_active
    mock_dc.__enter__ = MagicMock(return_value=mock_dc)
    mock_dc.__exit__ = MagicMock(return_value=False)
    with patch("experiment_workflow.DaemonClient", return_value=mock_dc):
        yield mock_dc, state


class TestExperimentWorkflow:
    def test_start(self, mock_daemon):
        from experiment_workflow import start_experiment

        _, state = mock_daemon
        start_experiment(experiment_dir="/tmp/test-exp", task="Train model")
        assert state["phase"] == "read"
        assert state["task"] == "Train model"
        assert state["iteration"] == 0

    def test_valid_transitions(self, mock_daemon):
        from experiment_workflow import start_experiment, advance_phase

        _, state = mock_daemon
        start_experiment(experiment_dir="/tmp/exp", task="test")
        for phase in ["plan", "work", "eval", "journal", "decide"]:
            advance_phase(phase)
            assert state["phase"] == phase

    def test_invalid_transition_raises(self, mock_daemon):
        from experiment_workflow import start_experiment, advance_phase, ExperimentWorkflowError

        _, state = mock_daemon
        start_experiment(experiment_dir="/tmp/exp", task="test")
        with pytest.raises(ExperimentWorkflowError, match="Invalid transition"):
            advance_phase("work")

    def test_kickback_from_decide_to_plan(self, mock_daemon):
        from experiment_workflow import start_experiment, advance_phase

        _, state = mock_daemon
        start_experiment(experiment_dir="/tmp/exp", task="test")
        for phase in ["plan", "work", "eval", "journal", "decide"]:
            advance_phase(phase)
        advance_phase("plan")
        assert state["phase"] == "plan"
        assert state["iteration"] == 1

    def test_decide_to_done(self, mock_daemon):
        from experiment_workflow import start_experiment, advance_phase

        mock_dc, state = mock_daemon
        start_experiment(experiment_dir="/tmp/exp", task="test")
        for phase in ["plan", "work", "eval", "journal", "decide"]:
            advance_phase(phase)
        advance_phase("done")
        assert state["active"] is False
        assert state["exit_reason"] == "success"
        mock_dc.workflow_stop.assert_called_with("experiment")

    def test_max_iterations(self, mock_daemon):
        from experiment_workflow import start_experiment, advance_phase, ExperimentWorkflowError

        mock_dc, state = mock_daemon
        start_experiment(experiment_dir="/tmp/exp", task="test", max_iterations=2)

        # Iteration 1
        for phase in ["plan", "work", "eval", "journal", "decide"]:
            advance_phase(phase)
        advance_phase("plan")  # kickback 1
        assert state["iteration"] == 1

        # Iteration 2
        for phase in ["work", "eval", "journal", "decide"]:
            advance_phase(phase)
        with pytest.raises(ExperimentWorkflowError, match="Max iterations"):
            advance_phase("plan")
        mock_dc.workflow_stop.assert_called_with("experiment")

    def test_eval_to_work_kickback(self, mock_daemon):
        from experiment_workflow import start_experiment, advance_phase

        _, state = mock_daemon
        start_experiment(experiment_dir="/tmp/exp", task="test")
        for phase in ["plan", "work", "eval"]:
            advance_phase(phase)
        # eval -> work (eval crashed)
        advance_phase("work")
        assert state["phase"] == "work"

    def test_stop(self, mock_daemon):
        from experiment_workflow import start_experiment, stop

        mock_dc, state = mock_daemon
        start_experiment(experiment_dir="/tmp/exp", task="test")
        stop()
        assert state["exit_reason"] == "user_stopped"
        mock_dc.workflow_stop.assert_called_with("experiment")

    def test_record_eval_result(self, mock_daemon):
        from experiment_workflow import start_experiment, record_eval_result

        _, state = mock_daemon
        start_experiment(experiment_dir="/tmp/exp", task="test")
        record_eval_result({"accuracy": 0.85}, passed=False)
        assert state["last_eval_metrics"]["accuracy"] == 0.85
        assert state["best_metrics"]["accuracy"] == 0.85

        # Better result updates best
        record_eval_result({"accuracy": 0.92}, passed=True)
        assert state["best_metrics"]["accuracy"] == 0.92

    def test_record_hypothesis(self, mock_daemon):
        from experiment_workflow import start_experiment, record_hypothesis

        _, state = mock_daemon
        start_experiment(experiment_dir="/tmp/exp", task="test")
        record_hypothesis("Linear projection", "R@5=0.24, failed")
        assert len(state["hypotheses_tested"]) == 1
        assert state["hypotheses_tested"][0]["hypothesis"] == "Linear projection"

    def test_inactive_workflow_raises(self, mock_daemon):
        from experiment_workflow import advance_phase, ExperimentWorkflowError

        _, state = mock_daemon
        # No workflow started
        with pytest.raises(ExperimentWorkflowError, match="not active"):
            advance_phase("plan")

    def test_workflow_start_called_on_fresh_experiment(self, mock_daemon):
        from experiment_workflow import start_experiment

        mock_dc, _ = mock_daemon
        start_experiment(experiment_dir="/tmp/exp", task="test")
        mock_dc.workflow_start.assert_called_once_with(
            "experiment", initial_state={"phase": "read"}
        )

    def test_workflow_start_not_called_when_already_active(self, mock_daemon):
        from experiment_workflow import start_experiment

        mock_dc, _ = mock_daemon
        # Start once to activate
        start_experiment(experiment_dir="/tmp/exp", task="test1")
        mock_dc.workflow_start.reset_mock()
        # Second start should skip workflow_start since daemon reports active
        start_experiment(experiment_dir="/tmp/exp", task="test2")
        mock_dc.workflow_start.assert_not_called()

    def test_best_metrics_lower_is_better(self, mock_daemon):
        from experiment_workflow import start_experiment, record_eval_result

        _, state = mock_daemon
        start_experiment(
            experiment_dir="/tmp/exp", task="test",
            success_criteria=[
                {"metric": "loss", "threshold": 0.1, "comparison": "<=", "primary": True},
                {"metric": "accuracy", "threshold": 0.9, "comparison": ">="},
            ],
        )

        record_eval_result({"loss": 0.5, "accuracy": 0.80}, passed=False)
        assert state["best_metrics"]["loss"] == 0.5
        assert state["best_metrics"]["accuracy"] == 0.80

        # Second eval: loss decreases (better), accuracy increases (better)
        record_eval_result({"loss": 0.3, "accuracy": 0.85}, passed=False)
        assert state["best_metrics"]["loss"] == 0.3
        assert state["best_metrics"]["accuracy"] == 0.85

        # Third eval: loss increases (worse), accuracy increases (better)
        record_eval_result({"loss": 0.4, "accuracy": 0.90}, passed=True)
        assert state["best_metrics"]["loss"] == 0.3   # stays at minimum
        assert state["best_metrics"]["accuracy"] == 0.90  # tracks maximum

    def test_success_criteria_stored_in_state(self, mock_daemon):
        from experiment_workflow import start_experiment

        _, state = mock_daemon
        criteria = [{"metric": "accuracy", "threshold": 0.9, "comparison": ">=", "primary": True}]
        result = start_experiment(
            experiment_dir="/tmp/exp", task="test", success_criteria=criteria,
        )
        assert result["success_criteria"] == criteria
        assert state["success_criteria"] == criteria

    def test_success_criteria_defaults_empty(self, mock_daemon):
        from experiment_workflow import start_experiment

        _, state = mock_daemon
        start_experiment(experiment_dir="/tmp/exp", task="test")
        assert state["success_criteria"] == []

    def test_no_advance_phase_on_data_only_update(self, mock_daemon):
        from experiment_workflow import start_experiment, record_eval_result

        mock_dc, state = mock_daemon
        start_experiment(experiment_dir="/tmp/exp", task="test")
        mock_dc.workflow_advance_phase.reset_mock()

        record_eval_result({"accuracy": 0.85}, passed=False)
        mock_dc.workflow_advance_phase.assert_not_called()

    def test_no_advance_phase_on_hypothesis(self, mock_daemon):
        from experiment_workflow import start_experiment, record_hypothesis

        mock_dc, state = mock_daemon
        start_experiment(experiment_dir="/tmp/exp", task="test")
        mock_dc.workflow_advance_phase.reset_mock()

        record_hypothesis("test hypothesis", "inconclusive")
        mock_dc.workflow_advance_phase.assert_not_called()

    def test_no_advance_phase_on_stop(self, mock_daemon):
        from experiment_workflow import start_experiment, stop

        mock_dc, state = mock_daemon
        start_experiment(experiment_dir="/tmp/exp", task="test")
        mock_dc.workflow_advance_phase.reset_mock()

        stop()
        mock_dc.workflow_advance_phase.assert_not_called()


import experiment_harness  # noqa: E402
from experiment_harness import EvalResult  # noqa: E402


class TestEvalPhaseAutoRun:
    """CHANGE 1: eval phase runs the harness itself rather than trusting self-report."""

    def _to_eval(self, advance_phase):
        for phase in ["plan", "work", "eval"]:
            advance_phase(phase)

    def test_run_eval_phase_auto_runs_harness_and_records(self, mock_daemon):
        from experiment_workflow import start_experiment, advance_phase, run_eval_phase

        _, state = mock_daemon
        criteria = [{"metric": "accuracy", "threshold": 0.9, "comparison": ">=", "primary": True}]
        start_experiment(experiment_dir="/tmp/exp", task="test", success_criteria=criteria)
        self._to_eval(advance_phase)

        fake = EvalResult(passed=True, metrics={"accuracy": 0.95})
        with patch("experiment_harness.run_eval", return_value=fake) as mock_run:
            out = run_eval_phase()

        mock_run.assert_called_once()
        assert out["passed"] is True
        assert out["metrics"] == {"accuracy": 0.95}
        assert any(d["metric"] == "accuracy" for d in out["criteria_details"])
        assert state["last_eval_metrics"] == {"accuracy": 0.95}
        assert state["last_eval_passed"] is True

    def test_run_eval_phase_passed_reflects_criteria_not_result(self, mock_daemon):
        from experiment_workflow import start_experiment, advance_phase, run_eval_phase

        _, state = mock_daemon
        criteria = [{"metric": "accuracy", "threshold": 0.9, "comparison": ">=", "primary": True}]
        start_experiment(experiment_dir="/tmp/exp", task="test", success_criteria=criteria)
        self._to_eval(advance_phase)

        fake = EvalResult(passed=True, metrics={"accuracy": 0.5})
        with patch("experiment_harness.run_eval", return_value=fake):
            out = run_eval_phase()

        assert out["passed"] is False
        assert state["last_eval_passed"] is False

    def test_run_eval_phase_requires_eval_phase(self, mock_daemon):
        from experiment_workflow import (
            start_experiment, advance_phase, run_eval_phase, ExperimentWorkflowError,
        )

        _, state = mock_daemon
        start_experiment(experiment_dir="/tmp/exp", task="test")
        advance_phase("plan")
        fake = EvalResult(passed=True, metrics={})
        with patch("experiment_harness.run_eval", return_value=fake):
            with pytest.raises(ExperimentWorkflowError):
                run_eval_phase()

    def test_run_eval_phase_requires_active(self, mock_daemon):
        from experiment_workflow import run_eval_phase, ExperimentWorkflowError

        _, state = mock_daemon
        with pytest.raises(ExperimentWorkflowError):
            run_eval_phase()


class TestDecideToDoneGate:
    """CHANGE 2: decide->done independently re-verifies success criteria."""

    def _drive_to_decide(self, advance_phase):
        for phase in ["plan", "work", "eval", "journal", "decide"]:
            advance_phase(phase)

    def test_done_blocked_when_recorded_metrics_fail(self, mock_daemon):
        from experiment_workflow import (
            start_experiment, advance_phase, record_eval_result, ExperimentWorkflowError,
        )

        _, state = mock_daemon
        criteria = [{"metric": "accuracy", "threshold": 0.9, "comparison": ">=", "primary": True}]
        start_experiment(experiment_dir="/tmp/exp", task="test", success_criteria=criteria)
        for phase in ["plan", "work", "eval"]:
            advance_phase(phase)
        record_eval_result({"accuracy": 0.5}, passed=False)
        for phase in ["journal", "decide"]:
            advance_phase(phase)
        with pytest.raises(ExperimentWorkflowError, match="criteria not met"):
            advance_phase("done")
        assert state.get("active") is not False

    def test_done_blocked_when_no_eval_recorded(self, mock_daemon):
        from experiment_workflow import (
            start_experiment, advance_phase, ExperimentWorkflowError,
        )

        _, state = mock_daemon
        criteria = [{"metric": "accuracy", "threshold": 0.9, "comparison": ">=", "primary": True}]
        start_experiment(experiment_dir="/tmp/exp", task="test", success_criteria=criteria)
        self._drive_to_decide(advance_phase)
        with pytest.raises(ExperimentWorkflowError, match="criteria not met"):
            advance_phase("done")

    def test_done_blocked_when_claimed_pass_but_metrics_fail(self, mock_daemon):
        from experiment_workflow import (
            start_experiment, advance_phase, record_eval_result, ExperimentWorkflowError,
        )

        _, state = mock_daemon
        criteria = [{"metric": "accuracy", "threshold": 0.9, "comparison": ">=", "primary": True}]
        start_experiment(experiment_dir="/tmp/exp", task="test", success_criteria=criteria)
        for phase in ["plan", "work", "eval"]:
            advance_phase(phase)
        record_eval_result({"accuracy": 0.5}, passed=True)
        for phase in ["journal", "decide"]:
            advance_phase(phase)
        with pytest.raises(ExperimentWorkflowError, match="criteria not met"):
            advance_phase("done")

    def test_done_allowed_when_metrics_pass(self, mock_daemon):
        from experiment_workflow import (
            start_experiment, advance_phase, record_eval_result,
        )

        mock_dc, state = mock_daemon
        criteria = [{"metric": "accuracy", "threshold": 0.9, "comparison": ">=", "primary": True}]
        start_experiment(experiment_dir="/tmp/exp", task="test", success_criteria=criteria)
        for phase in ["plan", "work", "eval"]:
            advance_phase(phase)
        record_eval_result({"accuracy": 0.95}, passed=True)
        for phase in ["journal", "decide"]:
            advance_phase(phase)
        advance_phase("done")
        assert state["active"] is False
        assert state["exit_reason"] == "success"
        mock_dc.workflow_stop.assert_called_with("experiment")

    def test_done_allowed_when_no_criteria(self, mock_daemon):
        from experiment_workflow import start_experiment, advance_phase

        mock_dc, state = mock_daemon
        start_experiment(experiment_dir="/tmp/exp", task="test")
        for phase in ["plan", "work", "eval", "journal", "decide"]:
            advance_phase(phase)
        advance_phase("done")
        assert state["active"] is False
        assert state["exit_reason"] == "success"


class TestNoPrimaryCriteriaGate:
    """PR #121 review: close the no-primary-criteria bypass.

    When success_criteria is non-empty but NO criterion is marked primary,
    CriteriaResult.passed (== primary_passed) is vacuously True even if every
    criterion fails. The gate and run_eval_phase must fall back to all_passed.
    """

    def test_done_blocked_when_nonprimary_criteria_fail(self, mock_daemon):
        from experiment_workflow import (
            start_experiment, advance_phase, record_eval_result, ExperimentWorkflowError,
        )

        _, state = mock_daemon
        # NON-empty criteria, NO primary, recorded metrics FAIL all of them.
        criteria = [{"metric": "accuracy", "threshold": 0.9, "comparison": ">="}]
        start_experiment(experiment_dir="/tmp/exp", task="test", success_criteria=criteria)
        for phase in ["plan", "work", "eval"]:
            advance_phase(phase)
        record_eval_result({"accuracy": 0.5}, passed=False)
        for phase in ["journal", "decide"]:
            advance_phase(phase)
        with pytest.raises(ExperimentWorkflowError, match="criteria not met"):
            advance_phase("done")
        assert state.get("active") is not False

    def test_done_allowed_when_nonprimary_criteria_pass(self, mock_daemon):
        from experiment_workflow import (
            start_experiment, advance_phase, record_eval_result,
        )

        mock_dc, state = mock_daemon
        criteria = [{"metric": "accuracy", "threshold": 0.9, "comparison": ">="}]
        start_experiment(experiment_dir="/tmp/exp", task="test", success_criteria=criteria)
        for phase in ["plan", "work", "eval"]:
            advance_phase(phase)
        record_eval_result({"accuracy": 0.95}, passed=True)
        for phase in ["journal", "decide"]:
            advance_phase(phase)
        advance_phase("done")
        assert state["active"] is False
        assert state["exit_reason"] == "success"
        mock_dc.workflow_stop.assert_called_with("experiment")

    def test_run_eval_phase_records_false_when_nonprimary_fail(self, mock_daemon):
        from experiment_workflow import start_experiment, advance_phase, run_eval_phase

        _, state = mock_daemon
        criteria = [{"metric": "accuracy", "threshold": 0.9, "comparison": ">="}]
        start_experiment(experiment_dir="/tmp/exp", task="test", success_criteria=criteria)
        for phase in ["plan", "work", "eval"]:
            advance_phase(phase)

        fake = EvalResult(passed=True, metrics={"accuracy": 0.5})
        with patch("experiment_harness.run_eval", return_value=fake):
            out = run_eval_phase()

        # Previously would record True (no primary -> primary_passed vacuously True).
        assert out["passed"] is False
        assert state["last_eval_passed"] is False

    def test_run_eval_phase_records_true_when_nonprimary_pass(self, mock_daemon):
        from experiment_workflow import start_experiment, advance_phase, run_eval_phase

        _, state = mock_daemon
        criteria = [{"metric": "accuracy", "threshold": 0.9, "comparison": ">="}]
        start_experiment(experiment_dir="/tmp/exp", task="test", success_criteria=criteria)
        for phase in ["plan", "work", "eval"]:
            advance_phase(phase)

        fake = EvalResult(passed=False, metrics={"accuracy": 0.95})
        with patch("experiment_harness.run_eval", return_value=fake):
            out = run_eval_phase()

        assert out["passed"] is True
        assert state["last_eval_passed"] is True

    def test_run_eval_phase_missing_experiment_dir_raises(self, mock_daemon):
        from experiment_workflow import (
            start_experiment, advance_phase, run_eval_phase, ExperimentWorkflowError,
        )

        _, state = mock_daemon
        start_experiment(experiment_dir="/tmp/exp", task="test")
        for phase in ["plan", "work", "eval"]:
            advance_phase(phase)
        # Simulate state that lost experiment_dir.
        state.pop("experiment_dir", None)

        fake = EvalResult(passed=True, metrics={})
        with patch("experiment_harness.run_eval", return_value=fake):
            with pytest.raises(ExperimentWorkflowError, match="experiment_dir"):
                run_eval_phase()


class TestDoneGateMetricsDistinction:
    """decide->done gate must distinguish None (no eval) from {} (empty eval).

    Regression for PR #121 review: the guard used a falsy check that
    conflated last_eval_metrics is None (no eval ran) with {} (empty eval).
    """

    def _advance_to_decide(self, mock_daemon, **start_kwargs):
        from experiment_workflow import start_experiment, advance_phase

        _, state = mock_daemon
        start_experiment(experiment_dir="/tmp/exp", task="test", **start_kwargs)
        for phase in ["plan", "work", "eval", "journal", "decide"]:
            advance_phase(phase)
        return state

    def test_none_metrics_with_criteria_blocks_no_eval_recorded(self, mock_daemon):
        from experiment_workflow import advance_phase, ExperimentWorkflowError

        state = self._advance_to_decide(mock_daemon)
        state["success_criteria"] = [{"metric": "accuracy", "threshold": 0.9}]
        state["last_eval_metrics"] = None
        with pytest.raises(ExperimentWorkflowError, match="no eval result recorded"):
            advance_phase("done")
        assert state.get("active") is not False

    def test_empty_metrics_empty_criteria_allows_done(self, mock_daemon):
        from experiment_workflow import advance_phase

        mock_dc, state = mock_daemon
        state = self._advance_to_decide(mock_daemon)
        state["success_criteria"] = []
        state["last_eval_metrics"] = {}
        advance_phase("done")
        assert state["phase"] == "done"
        assert state["active"] is False
        assert state["exit_reason"] == "success"
        mock_dc.workflow_stop.assert_called_with("experiment")

    def test_empty_metrics_with_criteria_blocks_criteria_not_met(self, mock_daemon):
        from experiment_workflow import advance_phase, ExperimentWorkflowError

        state = self._advance_to_decide(mock_daemon)
        state["success_criteria"] = [{"metric": "accuracy", "threshold": 0.9}]
        state["last_eval_metrics"] = {}
        with pytest.raises(ExperimentWorkflowError) as exc:
            advance_phase("done")
        msg = str(exc.value)
        assert "criteria not met" in msg
        assert "no eval result recorded" not in msg
