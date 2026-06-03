#!/usr/bin/env python3
"""Regression for #129.

`workflow_base._save_state` re-persists a workflow's state dict via the daemon.
`advance()` reads that dict back through `get_state()`, so it round-trips
daemon-owned keys -- `started_at` (set at workflow_start) and
`<phase>_checkpoint_passed` (set via the daemon's `workflow_pass_checkpoint`).
The daemon rejects `workflow_set_value` for any key in
`controller.PROTECTED_KEYS` (or a `*_checkpoint_passed` key), so re-writing one
aborts the save *after* the phase already advanced: every `advance` exits
non-zero with a traceback while the state actually moved.

These tests pin the skip behaviour so it cannot regress.
"""

from unittest.mock import MagicMock, patch

import pytest

import workflow_base
from daemon_client import is_daemon_only_key
from controller import PROTECTED_KEYS


@pytest.mark.parametrize("key", sorted(PROTECTED_KEYS))
def test_client_skips_every_daemon_protected_literal_key(key):
    """Every literal key the daemon protects must be a daemon-only key, else
    _save_state would issue a workflow_set_value the daemon rejects. Guards
    against PROTECTED_KEYS / DAEMON_ONLY_KEYS drifting apart."""
    assert is_daemon_only_key(key), (
        f"{key!r} is in controller.PROTECTED_KEYS but is_daemon_only_key "
        f"returns False, so _save_state would try to set it and the daemon "
        f"would reject it"
    )


def test_save_state_does_not_rewrite_daemon_owned_keys():
    """A state dict round-tripped from get_state carries started_at and a
    <phase>_checkpoint_passed flag; _save_state must route phase through
    advance_phase and skip all daemon-owned keys, persisting only the keys the
    workflow actually owns."""
    engine = workflow_base.WorkflowEngine.__new__(workflow_base.WorkflowEngine)
    engine.workflow_id = "pr_comment"

    dc = MagicMock()
    client = MagicMock()
    client.__enter__.return_value = dc

    with patch.object(workflow_base, "DaemonClient", return_value=client):
        engine._save_state({
            "phase": "fix",
            "started_at": "2026-01-01T00:00:00Z",
            "understand_checkpoint_passed": True,
            "active_agents": {},
            "task": "do the thing",
            "iteration": 1,
        })

    # Phase change is routed through advance_phase, never set_value.
    dc.workflow_advance_phase.assert_called_once_with("pr_comment", "fix")
    set_keys = {call.args[1] for call in dc.workflow_set_value.call_args_list}
    assert "started_at" not in set_keys, "started_at is daemon-owned"
    assert "understand_checkpoint_passed" not in set_keys, "checkpoint flag is daemon-owned"
    assert "phase" not in set_keys
    assert "active_agents" not in set_keys
    # Workflow-owned keys are still persisted.
    assert "task" in set_keys
    assert "iteration" in set_keys
