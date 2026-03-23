"""Tests for batch_resolver."""
import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))

from batch_resolver import parse_batch_goal, BatchGoal


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
