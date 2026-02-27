#\!/usr/bin/env python3
"""Integration tests: develop workflow through the real Controller.

These tests load the actual develop.yaml config and verify that
workflow operations (start, advance, checkpoint, stop) behave
correctly when dispatched through Controller.handle_call().
"""

import json
from pathlib import Path

import pytest
import yaml

from lib.controller import Controller
from lib.daemon import load_workflow_configs
from lib.errors import WorkflowError


# --- Fixtures ---

_PERM_CONFIG = {
    "global": {
        "allowed": ["native__*", "router__*", "workflow__*", "serena__*"],
        "blocked": [],
        "superblocked": [],
    },
}

_BACKEND_CONFIG = {
    "serena": {"command": ["echo"], "tool_prefix": "serena"},
}


@pytest.fixture
def ctrl(tmp_path):
    """Controller wired to real workflow configs from config/workflows/*.yaml."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "permissions.yaml").write_text(yaml.dump(_PERM_CONFIG))
    (config_dir / "backends.json").write_text(json.dumps(_BACKEND_CONFIG))
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    # Load real workflow configs from the actual config directory
    real_config_dir = Path(__file__).parent.parent / "config"
    workflow_configs = load_workflow_configs(real_config_dir)

    c = Controller(
        config_dir=config_dir,
        data_dir=data_dir,
        workflow_configs=workflow_configs,
    )
    yield c
    c.shutdown()


# --- Tests ---


class TestDevelopWorkflowViaController:
    """End-to-end develop workflow operations through Controller.handle_call."""

    def test_start_returns_state_with_intake_phase(self, ctrl):
        """workflow_start with workflow_id=develop sets phase to intake."""
        result = ctrl.handle_call(
            "workflow__workflow_start",
            {"workflow_id": "develop", "initial_state": {"task": "test"}},
        )
        assert result["phase"] == "intake"
        assert result["task"] == "test"
        assert "started_at" in result
        assert result["active_agents"] == {}

    def test_get_state_returns_current_state(self, ctrl):
        """workflow_get_state returns the full state dict."""
        ctrl.handle_call(
            "workflow__workflow_start",
            {"workflow_id": "develop", "initial_state": {"task": "test"}},
        )
        state = ctrl.handle_call(
            "workflow__workflow_get_state",
            {"workflow_id": "develop"},
        )
        assert state is not None
        assert state["phase"] == "intake"
        assert state["task"] == "test"

    def test_advance_phase_intake_to_research(self, ctrl):
        """Valid transition intake -> research succeeds."""
        ctrl.handle_call(
            "workflow__workflow_start",
            {"workflow_id": "develop", "initial_state": {}},
        )
        result = ctrl.handle_call(
            "workflow__workflow_advance_phase",
            {"workflow_id": "develop", "target_phase": "research"},
        )
        assert result["status"] == "advanced"
        assert result["phase"] == "research"

    def test_invalid_transition_raises_workflow_error(self, ctrl):
        """Invalid transition intake -> implement is rejected."""
        ctrl.handle_call(
            "workflow__workflow_start",
            {"workflow_id": "develop", "initial_state": {}},
        )
        with pytest.raises(WorkflowError, match="Invalid transition"):
            ctrl.handle_call(
                "workflow__workflow_advance_phase",
                {"workflow_id": "develop", "target_phase": "implement"},
            )

    def test_checkpoint_required_before_advance(self, ctrl):
        """design phase has checkpoint=true; advance without passing it fails."""
        ctrl.handle_call(
            "workflow__workflow_start",
            {"workflow_id": "develop", "initial_state": {}},
        )
        # Advance to design: intake -> research -> design
        ctrl.handle_call(
            "workflow__workflow_advance_phase",
            {"workflow_id": "develop", "target_phase": "research"},
        )
        ctrl.handle_call(
            "workflow__workflow_advance_phase",
            {"workflow_id": "develop", "target_phase": "design"},
        )
        # Try to advance past design without checkpoint
        with pytest.raises(WorkflowError, match="Checkpoint not passed"):
            ctrl.handle_call(
                "workflow__workflow_advance_phase",
                {"workflow_id": "develop", "target_phase": "branch"},
            )

    def test_pass_checkpoint_then_advance(self, ctrl):
        """After passing the design checkpoint, advance to branch succeeds."""
        ctrl.handle_call(
            "workflow__workflow_start",
            {"workflow_id": "develop", "initial_state": {}},
        )
        # Advance to design
        ctrl.handle_call(
            "workflow__workflow_advance_phase",
            {"workflow_id": "develop", "target_phase": "research"},
        )
        ctrl.handle_call(
            "workflow__workflow_advance_phase",
            {"workflow_id": "develop", "target_phase": "design"},
        )
        # Pass checkpoint
        ck = ctrl.handle_call(
            "workflow__workflow_pass_checkpoint",
            {"workflow_id": "develop"},
        )
        assert ck["status"] == "checkpoint_passed"
        assert ck["phase"] == "design"
        # Now advance succeeds
        result = ctrl.handle_call(
            "workflow__workflow_advance_phase",
            {"workflow_id": "develop", "target_phase": "branch"},
        )
        assert result["phase"] == "branch"

    def test_stop_workflow(self, ctrl):
        """workflow_stop removes state; is_active returns False."""
        ctrl.handle_call(
            "workflow__workflow_start",
            {"workflow_id": "develop", "initial_state": {}},
        )
        stopped = ctrl.handle_call(
            "workflow__workflow_stop",
            {"workflow_id": "develop"},
        )
        assert stopped is True

    def test_is_active_false_after_stop(self, ctrl):
        """After stop, workflow_is_active returns False."""
        ctrl.handle_call(
            "workflow__workflow_start",
            {"workflow_id": "develop", "initial_state": {}},
        )
        ctrl.handle_call(
            "workflow__workflow_stop",
            {"workflow_id": "develop"},
        )
        active = ctrl.handle_call(
            "workflow__workflow_is_active",
            {"workflow_id": "develop"},
        )
        assert active is False
