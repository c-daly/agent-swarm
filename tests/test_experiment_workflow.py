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
