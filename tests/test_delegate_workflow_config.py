"""Tests for the delegate workflow YAML configuration and its governance.

TDD: defines the expected structure of config/workflows/delegate.yaml
and its L1 governance before the files are modified.
"""
import sys
from pathlib import Path

import yaml
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

PROJECT_ROOT = Path(__file__).parent.parent
DELEGATE_YAML = PROJECT_ROOT / "config" / "workflows" / "delegate.yaml"

ALL_PHASES = ["decompose", "dispatch", "monitor", "escalate", "integrate"]
CHECKPOINT_PHASES = {"escalate", "integrate"}
FABLE_PHASES = {"decompose", "escalate", "integrate"}

EXPECTED_TRANSITIONS = {
    "decompose": {"dispatch"},
    "dispatch": {"monitor"},
    "monitor": {"dispatch", "escalate", "integrate"},
    "escalate": {"dispatch", "integrate"},
    "integrate": {"done"},
}


@pytest.fixture(scope="module")
def config():
    assert DELEGATE_YAML.exists(), f"delegate.yaml not found at {DELEGATE_YAML}"
    with open(DELEGATE_YAML) as f:
        return yaml.safe_load(f)


@pytest.fixture(scope="module")
def phases_by_name(config):
    return {p["name"]: p for p in config["phases"]}


class TestStructure:
    def test_name_and_terminals(self, config):
        assert config["name"] == "delegate"
        assert config["initial_phase"] == "decompose"
        assert config["terminal_phase"] == "done"

    def test_all_phases_declared_in_order(self, phases_by_name):
        assert list(phases_by_name) == ALL_PHASES

    def test_checkpoints(self, phases_by_name):
        for name, phase in phases_by_name.items():
            expected = name in CHECKPOINT_PHASES
            assert phase.get("checkpoint", False) == expected, name

    def test_fable_phases_carry_advisory_model(self, phases_by_name):
        for name in FABLE_PHASES:
            assert phases_by_name[name].get("model") == "fable", name

    def test_transitions(self, config):
        actual = {k: set(v) for k, v in config["transitions"].items()}
        assert actual == EXPECTED_TRANSITIONS


class TestDaemonLoader:
    def test_loads_via_daemon_loader(self):
        from lib.daemon import load_workflow_configs
        configs = load_workflow_configs(PROJECT_ROOT / "config")
        assert "delegate" in configs
        wf = configs["delegate"]
        assert wf.initial_phase == "decompose"
        assert wf.terminal_phase == "done"
        assert wf.transitions["monitor"] == {"dispatch", "escalate", "integrate"}
        assert wf.phases["escalate"].checkpoint is True
        assert wf.phases["integrate"].checkpoint is True


class TestGovernance:
    def test_delegate_in_known_workflows(self):
        from lib.permission_query import _KNOWN_WORKFLOWS
        assert "delegate" in _KNOWN_WORKFLOWS

    def test_delegate_fully_governed(self):
        from lib.conformance import analyze
        by_name = {r.name: r for r in analyze()["workflows"]}
        assert "delegate" in by_name
        assert not by_name["delegate"].fail_open, by_name["delegate"].notes
