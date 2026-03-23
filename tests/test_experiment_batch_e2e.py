"""End-to-end test for experiment batch resolver.

Tests the full resolve flow with inline tasks in a temporary directory.
Does NOT test actual experiment execution (that requires MCP tools).
"""
import os
import sys
import tempfile

import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))

from batch_resolver import parse_batch_goal, resolve_tasks, sort_by_dependencies


def test_e2e_inline_tasks():
    """Full flow: parse → resolve → sort → verify directory structure."""
    batch_goal = {
        "tasks": [
            {"target": "agora/adapters/foo.py", "objective": "Build foo adapter", "id": "foo"},
            {"target": "agora/analysis/bar.py", "objective": "Build bar analysis", "id": "bar", "depends_on": ["foo"]},
        ],
        "success_criteria": [{"metric": "test_pass_rate", "threshold": 1.0, "primary": True}],
        "on_failure": "continue",
    }

    goal = parse_batch_goal(batch_goal)
    assert goal.on_failure == "continue"

    with tempfile.TemporaryDirectory() as run_dir:
        resolved = resolve_tasks(goal, run_dir)
        assert len(resolved) == 2

        sorted_tasks = sort_by_dependencies(resolved)
        ids = [t["id"] for t in sorted_tasks]
        assert ids.index("foo") < ids.index("bar")

        # Verify directory structure
        for task in resolved:
            task_dir = os.path.join(run_dir, "tasks", task["id"])
            assert os.path.isdir(task_dir)
            goal_path = os.path.join(task_dir, "goal.yaml")
            assert os.path.isfile(goal_path)

            with open(goal_path) as f:
                task_goal = yaml.safe_load(f)
            assert "objective" in task_goal
            assert "success_criteria" in task_goal


def test_e2e_dir_query():
    """Full flow with dir: query picking up existing experiment directories."""
    with tempfile.TemporaryDirectory() as base:
        # Simulate existing experiment dirs
        for name, obj in [("alpha", "Build alpha"), ("beta", "Build beta")]:
            exp_dir = os.path.join(base, "experiments", name)
            os.makedirs(exp_dir)
            with open(os.path.join(exp_dir, "goal.yaml"), "w") as f:
                yaml.dump({"objective": obj, "target": f"src/{name}.py"}, f)

        batch_goal = {
            "query": f"dir:{base}/experiments/*/goal.yaml",
            "success_criteria": [{"metric": "test_pass_rate", "threshold": 1.0, "primary": True}],
        }

        goal = parse_batch_goal(batch_goal)

        run_dir = tempfile.mkdtemp()
        resolved = resolve_tasks(goal, run_dir)
        assert len(resolved) == 2

        targets = {t.get("target") for t in resolved}
        assert "src/alpha.py" in targets
        assert "src/beta.py" in targets


def test_e2e_mixed_with_dedup():
    """Inline + dir: query with overlapping targets are deduplicated."""
    with tempfile.TemporaryDirectory() as base:
        # Create a dir-based experiment
        exp_dir = os.path.join(base, "experiments", "foo")
        os.makedirs(exp_dir)
        with open(os.path.join(exp_dir, "goal.yaml"), "w") as f:
            yaml.dump({"objective": "Build foo", "target": "src/foo.py"}, f)

        batch_goal = {
            "query": f"dir:{base}/experiments/*/goal.yaml",
            "tasks": [
                {"target": "src/foo.py", "objective": "Build foo (inline)"},
                {"target": "src/bar.py", "objective": "Build bar"},
            ],
            "success_criteria": [{"metric": "test_pass_rate", "threshold": 1.0, "primary": True}],
        }

        goal = parse_batch_goal(batch_goal)
        run_dir = tempfile.mkdtemp()
        resolved = resolve_tasks(goal, run_dir)

        # foo.py appears in both inline and dir: — should be deduplicated
        targets = [t.get("target") for t in resolved]
        assert targets.count("src/foo.py") == 1
        assert "src/bar.py" in targets


def test_e2e_on_failure_stop():
    """Verify on_failure: stop is parsed correctly in full flow."""
    batch_goal = {
        "tasks": [{"target": "a.py", "objective": "A"}],
        "success_criteria": [{"metric": "test_pass_rate", "threshold": 1.0, "primary": True}],
        "on_failure": "stop",
    }
    goal = parse_batch_goal(batch_goal)
    assert goal.on_failure == "stop"


def test_e2e_success_criteria_inheritance():
    """Per-task goal.yaml inherits run-level success_criteria."""
    batch_goal = {
        "tasks": [
            {"target": "a.py", "objective": "A"},
            {"target": "b.py", "objective": "B", "success_criteria": [{"metric": "custom", "threshold": 0.9}]},
        ],
        "success_criteria": [{"metric": "test_pass_rate", "threshold": 1.0, "primary": True}],
    }
    goal = parse_batch_goal(batch_goal)

    with tempfile.TemporaryDirectory() as run_dir:
        resolved = resolve_tasks(goal, run_dir)

        # Task A should inherit run-level criteria
        a_task = next(t for t in resolved if t["target"] == "a.py")
        with open(os.path.join(a_task["dir"], "goal.yaml")) as f:
            a_goal = yaml.safe_load(f)
        assert a_goal["success_criteria"][0]["metric"] == "test_pass_rate"

        # Task B should keep its own criteria
        b_task = next(t for t in resolved if t["target"] == "b.py")
        with open(os.path.join(b_task["dir"], "goal.yaml")) as f:
            b_goal = yaml.safe_load(f)
        assert b_goal["success_criteria"][0]["metric"] == "custom"
