"""Tests for experiment workflow state machine."""
import pytest
from unittest.mock import patch, MagicMock


@pytest.fixture
def mock_daemon():
    state = {}
    mock_dc = MagicMock()
    mock_dc.workflow_get_state.return_value = state
    mock_dc.workflow_set_value.side_effect = lambda wf_id, k, v: state.update({k: v})
    mock_dc.workflow_advance_phase.side_effect = lambda wf_id, phase: state.update({"phase": phase})
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

        _, state = mock_daemon
        start_experiment(experiment_dir="/tmp/exp", task="test")
        for phase in ["plan", "work", "eval", "journal", "decide"]:
            advance_phase(phase)
        advance_phase("done")
        assert state["phase"] == "done"
        assert state["active"] == False

    def test_max_iterations(self, mock_daemon):
        from experiment_workflow import start_experiment, advance_phase, ExperimentWorkflowError

        _, state = mock_daemon
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

        _, state = mock_daemon
        start_experiment(experiment_dir="/tmp/exp", task="test")
        stop()
        assert state["active"] == False
        assert state["exit_reason"] == "user_stopped"

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

    def test_unknown_phase_raises(self, mock_daemon):
        from experiment_workflow import start_experiment, advance_phase, ExperimentWorkflowError

        _, state = mock_daemon
        start_experiment(experiment_dir="/tmp/exp", task="test")
        with pytest.raises(ExperimentWorkflowError, match="Unknown phase"):
            advance_phase("nonexistent")

    def test_inactive_workflow_raises(self, mock_daemon):
        from experiment_workflow import advance_phase, ExperimentWorkflowError

        _, state = mock_daemon
        # No workflow started
        with pytest.raises(ExperimentWorkflowError, match="not active"):
            advance_phase("plan")
