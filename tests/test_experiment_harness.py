"""Tests for experiment harness library."""
import pytest
import yaml
from pathlib import Path

from experiment_harness import (
    Goal, load_goal,
    Constraints, load_constraints,
    Journal,
    EvalResult, run_eval, _parse_metrics, _parse_pytest_summary,
    CriteriaResult, check_criteria,
)


@pytest.fixture
def tmp_experiment(tmp_path):
    exp_dir = tmp_path / "test-exp"
    exp_dir.mkdir()
    return exp_dir


def write_goal(exp_dir: Path, goal: dict) -> Path:
    goal_path = exp_dir / "goal.yaml"
    goal_path.write_text(yaml.dump(goal))
    return goal_path


# ---------------------------------------------------------------------------
# Goal
# ---------------------------------------------------------------------------

class TestLoadGoal:
    def test_loads_standalone_goal(self, tmp_experiment):
        write_goal(tmp_experiment, {
            "objective": "Train a model",
            "eval": "eval/test_model.py",
            "success_criteria": [
                {"metric": "accuracy", "threshold": 0.9, "primary": True}
            ],
        })
        goal = load_goal(tmp_experiment)
        assert goal.objective == "Train a model"
        assert goal.is_standalone
        assert not goal.is_integration
        assert goal.primary_criterion["metric"] == "accuracy"

    def test_loads_integration_goal(self, tmp_experiment):
        write_goal(tmp_experiment, {
            "objective": "Add retry to EventBus",
            "eval": "eval/",
            "target": "logos/logos_events/event_bus.py",
            "success_criteria": [
                {"metric": "test_pass_rate", "threshold": 1.0, "primary": True}
            ],
        })
        goal = load_goal(tmp_experiment)
        assert goal.is_integration
        assert goal.target == "logos/logos_events/event_bus.py"

    def test_missing_goal_raises(self, tmp_experiment):
        with pytest.raises(FileNotFoundError):
            load_goal(tmp_experiment)

    def test_loads_environment(self, tmp_experiment):
        write_goal(tmp_experiment, {
            "objective": "Train on GPU",
            "eval": "eval/",
            "success_criteria": [{"metric": "loss", "threshold": 0.1, "primary": True}],
            "environment": {"type": "runpod", "gpu": "RTX 3090"},
        })
        goal = load_goal(tmp_experiment)
        assert goal.environment["type"] == "runpod"

    def test_primary_criterion_defaults_to_first(self, tmp_experiment):
        write_goal(tmp_experiment, {
            "objective": "Test",
            "eval": "eval/",
            "success_criteria": [
                {"metric": "loss", "threshold": 0.1},
                {"metric": "accuracy", "threshold": 0.9},
            ],
        })
        goal = load_goal(tmp_experiment)
        assert goal.primary_criterion["metric"] == "loss"

    def test_primary_criterion_empty(self, tmp_experiment):
        write_goal(tmp_experiment, {
            "objective": "Test",
            "eval": "eval/",
            "success_criteria": [],
        })
        goal = load_goal(tmp_experiment)
        assert goal.primary_criterion is None


# ---------------------------------------------------------------------------
# Constraints
# ---------------------------------------------------------------------------

class TestLoadConstraints:
    def test_loads_constraints(self, tmp_experiment):
        constraints = {
            "time_limits": {"max_hours_per_run": 4},
            "do_not_do": ["Do NOT fine-tune encoder"],
            "escalate_if": ["Cannot load weights"],
            "known_findings": ["Batch size > 64 causes OOM"],
        }
        (tmp_experiment / "constraints.yaml").write_text(yaml.dump(constraints))
        result = load_constraints(tmp_experiment)
        assert result.max_hours_per_run == 4
        assert "Do NOT fine-tune encoder" in result.do_not_do
        assert "Cannot load weights" in result.escalate_if
        assert "Batch size > 64 causes OOM" in result.known_findings

    def test_missing_constraints_returns_empty(self, tmp_experiment):
        result = load_constraints(tmp_experiment)
        assert result.do_not_do == []
        assert result.escalate_if == []
        assert result.max_hours_per_run is None


# ---------------------------------------------------------------------------
# Journal
# ---------------------------------------------------------------------------

class TestJournal:
    def test_list_entries_empty(self, tmp_experiment):
        journal = Journal(tmp_experiment)
        assert journal.list_entries() == []

    def test_add_and_list_entry(self, tmp_experiment):
        journal = Journal(tmp_experiment)
        journal.add_entry(
            title="MSE baseline",
            hypothesis="Linear projection is sufficient",
            changes="Implemented linear layer",
            result="R@5=0.24, below threshold",
            diagnosis="Frozen encoders have no alignment",
            next_direction="Try fine-tuning text encoder",
        )
        entries = journal.list_entries()
        assert len(entries) == 1
        assert "mse_baseline" in entries[0].name

    def test_entries_auto_increment(self, tmp_experiment):
        journal = Journal(tmp_experiment)
        journal.add_entry(title="First", hypothesis="A", changes="x",
                         result="fail", diagnosis="d", next_direction="n")
        journal.add_entry(title="Second", hypothesis="B", changes="y",
                         result="pass", diagnosis="d", next_direction="n")
        entries = journal.list_entries()
        assert len(entries) == 2
        assert entries[0].name.startswith("001_")
        assert entries[1].name.startswith("002_")

    def test_summary(self, tmp_experiment):
        journal = Journal(tmp_experiment)
        journal.add_entry(title="First attempt", hypothesis="A",
                         changes="x", result="fail", diagnosis="d",
                         next_direction="try B")
        summary = journal.summary()
        assert "First attempt" in summary
        assert "try B" in summary

    def test_summary_empty(self, tmp_experiment):
        journal = Journal(tmp_experiment)
        assert journal.summary() == "No journal entries yet."


# ---------------------------------------------------------------------------
# Eval runner
# ---------------------------------------------------------------------------

class TestParseHelpers:
    def test_parse_metrics(self):
        output = "[METRIC] accuracy=0.95\n[METRIC] f1 = 0.88\nother text"
        metrics = _parse_metrics(output)
        assert metrics["accuracy"] == 0.95
        assert metrics["f1"] == 0.88

    def test_parse_pytest_summary(self):
        output = "===== 3 passed, 1 failed in 2.5s ====="
        total, passed, failed = _parse_pytest_summary(output)
        assert total == 4
        assert passed == 3
        assert failed == 1

    def test_parse_pytest_all_passed(self):
        output = "===== 5 passed in 1.0s ====="
        total, passed, failed = _parse_pytest_summary(output)
        assert total == 5
        assert passed == 5
        assert failed == 0


class TestEvalRunner:
    def test_run_pytest_eval_pass(self, tmp_experiment):
        eval_dir = tmp_experiment / "eval"
        eval_dir.mkdir()
        (eval_dir / "test_simple.py").write_text("def test_passes(): assert True\n")
        result = run_eval(tmp_experiment, eval_path="eval/")
        assert result.passed
        assert result.tests_run > 0
        assert result.tests_passed > 0

    def test_run_pytest_eval_fail(self, tmp_experiment):
        eval_dir = tmp_experiment / "eval"
        eval_dir.mkdir()
        (eval_dir / "test_simple.py").write_text("def test_fails(): assert False\n")
        result = run_eval(tmp_experiment, eval_path="eval/")
        assert not result.passed
        assert result.tests_failed > 0

    def test_eval_timeout(self, tmp_experiment):
        eval_dir = tmp_experiment / "eval"
        eval_dir.mkdir()
        (eval_dir / "test_slow.py").write_text(
            "import time\ndef test_slow(): time.sleep(10)\n"
        )
        result = run_eval(tmp_experiment, eval_path="eval/", timeout=2)
        assert not result.passed
        assert result.timed_out

    def test_eval_result_has_metrics(self, tmp_experiment):
        eval_dir = tmp_experiment / "eval"
        eval_dir.mkdir()
        (eval_dir / "test_metrics.py").write_text(
            'def test_with_metric():\n'
            '    print("[METRIC] accuracy=0.95")\n'
            '    assert True\n'
        )
        result = run_eval(tmp_experiment, eval_path="eval/")
        assert result.passed
        assert result.metrics.get("accuracy") == 0.95


# ---------------------------------------------------------------------------
# Criteria checker
# ---------------------------------------------------------------------------

class TestCheckCriteria:
    def test_all_criteria_met(self):
        criteria = [
            {"metric": "accuracy", "threshold": 0.9, "primary": True},
            {"metric": "loss", "threshold": 0.1, "comparison": "<="},
        ]
        result = check_criteria(criteria, {"accuracy": 0.95, "loss": 0.05})
        assert result.passed
        assert result.primary_passed
        assert result.all_passed

    def test_primary_failed(self):
        criteria = [{"metric": "accuracy", "threshold": 0.9, "primary": True}]
        result = check_criteria(criteria, {"accuracy": 0.7})
        assert not result.passed
        assert not result.primary_passed

    def test_missing_metric(self):
        criteria = [{"metric": "accuracy", "threshold": 0.9, "primary": True}]
        result = check_criteria(criteria, {})
        assert not result.passed

    def test_secondary_failed_primary_passed(self):
        criteria = [
            {"metric": "accuracy", "threshold": 0.9, "primary": True},
            {"metric": "f1", "threshold": 0.85},
        ]
        result = check_criteria(criteria, {"accuracy": 0.95, "f1": 0.7})
        assert result.primary_passed
        assert not result.all_passed
