"""Tests for batch_resolver."""
import pytest
import sys
import os
import tempfile
import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))

from batch_resolver import parse_batch_goal, BatchGoal, resolve_tasks, _task_id, sort_by_dependencies


def test_parse_query_based():
    goal = parse_batch_goal({
        "query": "repo:c-daly/agora label:experiment-ready is:open",
        "success_criteria": [{"metric": "test_pass_rate", "threshold": 1.0, "primary": True}],
    })
    assert goal.query == "repo:c-daly/agora label:experiment-ready is:open"
    assert goal.tasks == []
    assert goal.success_criteria[0]["metric"] == "test_pass_rate"


def test_parse_explicit_tasks():
    goal = parse_batch_goal({
        "tasks": [{"issue": 42}, {"issue": 43}],
        "success_criteria": [{"metric": "test_pass_rate", "threshold": 1.0, "primary": True}],
    })
    assert len(goal.tasks) == 2
    assert goal.tasks[0]["issue"] == 42


def test_parse_inline_tasks():
    goal = parse_batch_goal({
        "tasks": [
            {"target": "agora/adapters/foo.py", "objective": "Build foo"},
        ],
        "success_criteria": [{"metric": "test_pass_rate", "threshold": 1.0, "primary": True}],
    })
    assert goal.tasks[0]["target"] == "agora/adapters/foo.py"


def test_parse_mixed():
    goal = parse_batch_goal({
        "query": "repo:c-daly/agora label:ready",
        "tasks": [{"target": "agora/analysis/bar.py", "objective": "Build bar"}],
        "success_criteria": [{"metric": "test_pass_rate", "threshold": 1.0, "primary": True}],
    })
    assert goal.query is not None
    assert len(goal.tasks) == 1


def test_parse_on_failure_default():
    goal = parse_batch_goal({
        "tasks": [{"issue": 1}],
        "success_criteria": [{"metric": "test_pass_rate", "threshold": 1.0, "primary": True}],
    })
    assert goal.on_failure == "continue"


def test_parse_on_failure_stop():
    goal = parse_batch_goal({
        "tasks": [{"issue": 1}],
        "on_failure": "stop",
        "success_criteria": [{"metric": "test_pass_rate", "threshold": 1.0, "primary": True}],
    })
    assert goal.on_failure == "stop"


def test_requires_query_or_tasks():
    with pytest.raises(ValueError, match="query.*tasks"):
        parse_batch_goal({
            "success_criteria": [{"metric": "test_pass_rate", "threshold": 1.0, "primary": True}],
        })


def test_requires_success_criteria():
    with pytest.raises(ValueError, match="success_criteria"):
        parse_batch_goal({"tasks": [{"issue": 1}]})


def test_resolve_inline_tasks():
    goal = BatchGoal(
        tasks=[
            {"target": "agora/adapters/foo.py", "objective": "Build foo"},
            {"target": "agora/adapters/bar.py", "objective": "Build bar"},
        ],
        success_criteria=[{"metric": "test_pass_rate", "threshold": 1.0, "primary": True}],
    )
    with tempfile.TemporaryDirectory() as run_dir:
        resolved = resolve_tasks(goal, run_dir)
        assert len(resolved) == 2
        for task in resolved:
            task_goal_path = os.path.join(run_dir, "tasks", task["id"], "goal.yaml")
            assert os.path.exists(task_goal_path)
            with open(task_goal_path) as f:
                task_goal = yaml.safe_load(f)
            assert "objective" in task_goal
            assert "target" in task_goal


def test_resolve_deduplicates_by_target():
    goal = BatchGoal(
        tasks=[
            {"target": "agora/adapters/foo.py", "objective": "Build foo"},
            {"target": "agora/adapters/foo.py", "objective": "Build foo again"},
        ],
        success_criteria=[{"metric": "test_pass_rate", "threshold": 1.0, "primary": True}],
    )
    with tempfile.TemporaryDirectory() as run_dir:
        resolved = resolve_tasks(goal, run_dir)
        assert len(resolved) == 1


def test_resolve_inherits_success_criteria():
    goal = BatchGoal(
        tasks=[{"target": "foo.py", "objective": "Build foo"}],
        success_criteria=[{"metric": "test_pass_rate", "threshold": 1.0, "primary": True}],
    )
    with tempfile.TemporaryDirectory() as run_dir:
        resolved = resolve_tasks(goal, run_dir)
        task_goal_path = os.path.join(run_dir, "tasks", resolved[0]["id"], "goal.yaml")
        with open(task_goal_path) as f:
            task_goal = yaml.safe_load(f)
        assert task_goal["success_criteria"][0]["metric"] == "test_pass_rate"


def test_resolve_dir_query():
    with tempfile.TemporaryDirectory() as base:
        for name in ["exp_a", "exp_b"]:
            exp_dir = os.path.join(base, name)
            os.makedirs(exp_dir)
            with open(os.path.join(exp_dir, "goal.yaml"), "w") as f:
                yaml.dump({"objective": f"Do {name}", "target": f"{name}.py"}, f)

        goal = BatchGoal(
            query=f"dir:{base}/*/goal.yaml",
            success_criteria=[{"metric": "test_pass_rate", "threshold": 1.0, "primary": True}],
        )
        run_dir = tempfile.mkdtemp()
        resolved = resolve_tasks(goal, run_dir)
        assert len(resolved) == 2


def test_task_id_from_issue():
    assert _task_id({"issue": 42}, 0) == "42"


def test_task_id_from_target():
    assert _task_id({"target": "agora/adapters/foo.py"}, 0) == "foo"


def test_task_id_fallback():
    assert _task_id({"objective": "something"}, 3) == "task_3"


def test_sort_independent_tasks():
    tasks = [
        {"id": "a", "dir": "/tmp/a"},
        {"id": "b", "dir": "/tmp/b"},
    ]
    sorted_tasks = sort_by_dependencies(tasks)
    assert len(sorted_tasks) == 2


def test_sort_with_dependency():
    tasks = [
        {"id": "yield_curve", "dir": "/tmp/yc", "depends_on": ["treasury_adapter"]},
        {"id": "treasury_adapter", "dir": "/tmp/ta"},
    ]
    sorted_tasks = sort_by_dependencies(tasks)
    ids = [t["id"] for t in sorted_tasks]
    assert ids.index("treasury_adapter") < ids.index("yield_curve")


def test_sort_circular_dependency_raises():
    tasks = [
        {"id": "a", "dir": "/tmp/a", "depends_on": ["b"]},
        {"id": "b", "dir": "/tmp/b", "depends_on": ["a"]},
    ]
    with pytest.raises(ValueError, match="[Cc]ircular"):
        sort_by_dependencies(tasks)
