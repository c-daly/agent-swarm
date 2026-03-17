"""Integration test — full harness loop without daemon."""
import yaml
from pathlib import Path

from experiment_harness import load_goal, load_constraints, Journal, run_eval, check_criteria


def test_full_loop_trivial_pass(tmp_path):
    exp = tmp_path / "trivial"
    exp.mkdir()
    (exp / "goal.yaml").write_text(yaml.dump({
        "objective": "Make a trivial test pass",
        "eval": "eval/",
        "success_criteria": [{"metric": "test_pass_rate", "threshold": 1.0, "primary": True}],
    }))
    eval_dir = exp / "eval"
    eval_dir.mkdir()
    (eval_dir / "test_trivial.py").write_text("def test_ok(): assert True\n")
    (exp / "workspace").mkdir()

    goal = load_goal(exp)
    constraints = load_constraints(exp)
    journal = Journal(exp)

    assert goal.is_standalone
    assert constraints.do_not_do == []
    assert journal.list_entries() == []

    result = run_eval(exp, eval_path=goal.eval)
    assert result.passed

    rate = result.tests_passed / max(result.tests_run, 1)
    criteria = check_criteria(goal.success_criteria, {"test_pass_rate": rate})
    assert criteria.primary_passed

    journal.add_entry(title="Trivial", hypothesis="Already passes",
                     changes="None", result=f"rate={rate}",
                     diagnosis="OK", next_direction="Done")
    assert len(journal.list_entries()) == 1


def test_full_loop_failing_then_passing(tmp_path):
    """Simulate a two-iteration experiment."""
    exp = tmp_path / "two-iter"
    exp.mkdir()
    (exp / "goal.yaml").write_text(yaml.dump({
        "objective": "Get accuracy above 0.9",
        "eval": "eval/",
        "success_criteria": [{"metric": "accuracy", "threshold": 0.9, "primary": True}],
    }))
    eval_dir = exp / "eval"
    eval_dir.mkdir()

    journal = Journal(exp)

    # Iteration 1: eval reports low accuracy
    (eval_dir / "test_accuracy.py").write_text(
        'def test_accuracy():\n'
        '    print("[METRIC] accuracy=0.7")\n'
        '    assert True\n'
    )
    result = run_eval(exp, eval_path="eval/")
    assert result.passed  # test passes but metric is low
    criteria = check_criteria(
        [{"metric": "accuracy", "threshold": 0.9, "primary": True}],
        result.metrics,
    )
    assert not criteria.primary_passed  # 0.7 < 0.9

    journal.add_entry(title="Low accuracy", hypothesis="Baseline",
                     changes="Initial impl", result="accuracy=0.7",
                     diagnosis="Need better approach", next_direction="Try X")

    # Iteration 2: eval reports high accuracy
    (eval_dir / "test_accuracy.py").write_text(
        'def test_accuracy():\n'
        '    print("[METRIC] accuracy=0.95")\n'
        '    assert True\n'
    )
    result = run_eval(exp, eval_path="eval/")
    criteria = check_criteria(
        [{"metric": "accuracy", "threshold": 0.9, "primary": True}],
        result.metrics,
    )
    assert criteria.primary_passed  # 0.95 >= 0.9

    journal.add_entry(title="High accuracy", hypothesis="Try X",
                     changes="Applied X", result="accuracy=0.95",
                     diagnosis="X worked", next_direction="Done")
    assert len(journal.list_entries()) == 2
