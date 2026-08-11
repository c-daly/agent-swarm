#!/usr/bin/env python3
"""End-to-end phase-lifecycle enforcement for the pr_comment workflow.

Drives a realistic "address a PR review comment" scenario through the real
PermissionChecker (loaded from config/permissions.yaml) across the full phase
sequence understand -> fix -> verify -> push -> check_reviews -> done, and
asserts the gate enforces the right thing at each phase.

Guards the C2 migration: pr_comment previously had no L1 block (keyed as the
stale "pr_review"), so the read-only understand phase fell through to the
implementer role and could edit files. test_understand_would_leak_without_gate
pins that contrast so a regression to an ungoverned pr_comment is caught.
"""

from pathlib import Path

import pytest

from lib.permissions import PermissionChecker

_PERMISSIONS = Path(__file__).parent.parent / "config" / "permissions.yaml"


@pytest.fixture
def gate():
    pc = PermissionChecker(_PERMISSIONS)
    pc.register_agent("pr-worker", agent_type="implementer", roles=["implementer"])

    def can(phase, tool, args=None):
        pc.update_agent_phase("pr-worker", "pr_comment", phase)
        return pc.check(tool, args or {}, pc._agents["pr-worker"])[0]

    return can


def test_understand_is_read_only(gate):
    assert gate("understand", "native__read_file") is True
    assert gate("understand", "native__grep") is True
    assert gate("understand", "native__edit_file") is False
    assert gate("understand", "native__write_file") is False
    # serena write path must also be closed, not just the native one
    assert gate("understand", "serena__replace_content") is False
    assert gate("understand", "native__bash", {"command": "python x.py"}) is False


def test_fix_allows_edits_and_tests(gate):
    assert gate("fix", "native__edit_file") is True
    assert gate("fix", "native__write_file") is True
    assert gate("fix", "native__bash", {"command": "pytest -q"}) is True


def test_verify_runs_tests_but_no_edits(gate):
    assert gate("verify", "native__bash", {"command": "pytest -q"}) is True
    assert gate("verify", "native__edit_file") is False
    assert gate("verify", "native__write_file") is False


def test_push_allows_git_gh_not_edits(gate):
    assert gate("push", "native__bash", {"command": "git push"}) is True
    assert gate("push", "native__bash", {"command": "gh pr comment 42 -b done"}) is True
    assert gate("push", "native__edit_file") is False


def test_check_reviews_reads_and_polls_no_edits(gate):
    assert gate("check_reviews", "native__bash", {"command": "gh pr view 42"}) is True
    assert gate("check_reviews", "native__read_file") is True
    assert gate("check_reviews", "native__edit_file") is False


def test_understand_would_leak_without_gate(gate):
    """Contrast: an ungoverned phase (as pr_comment was, keyed 'pr_review')
    falls through to the implementer role, which allows edits. This is the
    hole the C2 migration closed; if pr_comment's understand block regresses
    to absent, test_understand_is_read_only flips and this stays green."""
    pc = PermissionChecker(_PERMISSIONS)
    pc.register_agent("x", agent_type="implementer", roles=["implementer"])
    pc.update_agent_phase("x", "pr_review", "analyze")  # a base_wf with no block
    assert pc.check("native__edit_file", {}, pc._agents["x"])[0] is True
