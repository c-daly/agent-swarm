"""Tests for the develop workflow YAML configuration.

TDD: These tests define the expected structure and behavior of
config/workflows/develop.yaml before the file is created.
"""
import sys
from pathlib import Path

import yaml
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

PROJECT_ROOT = Path(__file__).parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"
DEVELOP_YAML = CONFIG_DIR / "workflows" / "develop.yaml"

ALL_PHASES = [
    "intake", "research", "design", "branch", "test_writing",
    "implement", "test", "review", "merge", "acceptance", "complete",
]

CHECKPOINT_PHASES = {"design", "test", "review", "acceptance"}

EXPECTED_TRANSITIONS = {
    "intake": {"research"},
    "research": {"design"},
    "design": {"branch"},
    "branch": {"test_writing"},
    "test_writing": {"implement"},
    "implement": {"test"},
    "test": {"review", "implement"},
    "review": {"merge", "implement", "test_writing"},
    "merge": {"acceptance", "implement"},
    "acceptance": {"complete", "implement", "test_writing"},
}


@pytest.fixture(scope="module")
def config():
    """Load and return the parsed YAML config."""
    assert DEVELOP_YAML.exists(), f"develop.yaml not found at {DEVELOP_YAML}"
    with open(DEVELOP_YAML) as f:
        return yaml.safe_load(f)


@pytest.fixture(scope="module")
def phases_by_name(config):
    """Return a dict mapping phase name to phase dict."""
    return {p["name"]: p for p in config["phases"]}


class TestConfigFileStructure:
    def test_file_exists(self):
        assert DEVELOP_YAML.exists(), "develop.yaml must exist"

    def test_valid_yaml(self):
        with open(DEVELOP_YAML) as f:
            data = yaml.safe_load(f)
        assert isinstance(data, dict)

    def test_name_is_develop(self, config):
        assert config["name"] == "develop"

    def test_initial_phase(self, config):
        assert config["initial_phase"] == "intake"

    def test_terminal_phase(self, config):
        assert config["terminal_phase"] == "complete"

    def test_has_description(self, config):
        assert "description" in config
        assert isinstance(config["description"], str)
        assert len(config["description"]) > 0

    def test_has_max_agents(self, config):
        assert "max_agents" in config
        assert isinstance(config["max_agents"], int)
        assert config["max_agents"] == 8


class TestPhases:
    def test_has_all_eleven_phases(self, config):
        phase_names = [p["name"] for p in config["phases"]]
        assert phase_names == ALL_PHASES

    @pytest.mark.parametrize("phase_name", ALL_PHASES)
    def test_phase_present(self, phases_by_name, phase_name):
        assert phase_name in phases_by_name

    @pytest.mark.parametrize("phase_name", ALL_PHASES)
    def test_phase_has_allowed_tool_categories(self, phases_by_name, phase_name):
        phase = phases_by_name[phase_name]
        assert "allowed_tool_categories" in phase
        assert isinstance(phase["allowed_tool_categories"], list)

    @pytest.mark.parametrize("phase_name", ALL_PHASES)
    def test_phase_has_blocked_tools(self, phases_by_name, phase_name):
        phase = phases_by_name[phase_name]
        assert "blocked_tools" in phase
        assert isinstance(phase["blocked_tools"], list)

    @pytest.mark.parametrize("phase_name", ALL_PHASES)
    def test_phase_has_eligible_agents(self, phases_by_name, phase_name):
        phase = phases_by_name[phase_name]
        assert "eligible_agents" in phase
        assert isinstance(phase["eligible_agents"], list)

    @pytest.mark.parametrize("phase_name", sorted(CHECKPOINT_PHASES))
    def test_checkpoint_phases_are_true(self, phases_by_name, phase_name):
        assert phases_by_name[phase_name]["checkpoint"] is True

    @pytest.mark.parametrize("phase_name", sorted(set(ALL_PHASES) - CHECKPOINT_PHASES))
    def test_non_checkpoint_phases_are_false(self, phases_by_name, phase_name):
        assert phases_by_name[phase_name].get("checkpoint", False) is False

    def test_intake_categories(self, phases_by_name):
        cats = phases_by_name["intake"]["allowed_tool_categories"]
        assert set(cats) == {"FILE_READ", "FILE_SEARCH", "CODE_QUERY", "USER_INTERACTION"}

    def test_intake_blocked(self, phases_by_name):
        blocked = phases_by_name["intake"]["blocked_tools"]
        assert "native__bash" in blocked
        assert "native__write_file" in blocked
        assert "native__edit_file" in blocked

    def test_intake_agents(self, phases_by_name):
        assert phases_by_name["intake"]["eligible_agents"] == ["pm"]

    def test_research_categories(self, phases_by_name):
        cats = phases_by_name["research"]["allowed_tool_categories"]
        assert set(cats) == {"FILE_READ", "FILE_SEARCH", "CODE_QUERY", "WEB_RESEARCH"}

    def test_research_agents(self, phases_by_name):
        assert phases_by_name["research"]["eligible_agents"] == ["researcher"]

    def test_design_categories(self, phases_by_name):
        cats = phases_by_name["design"]["allowed_tool_categories"]
        assert set(cats) == {"FILE_READ", "FILE_SEARCH", "CODE_QUERY"}

    def test_design_agents(self, phases_by_name):
        assert phases_by_name["design"]["eligible_agents"] == ["architect"]

    def test_branch_categories(self, phases_by_name):
        cats = phases_by_name["branch"]["allowed_tool_categories"]
        assert set(cats) == {"SHELL_SAFE"}

    def test_branch_agents(self, phases_by_name):
        assert phases_by_name["branch"]["eligible_agents"] == ["git-agent"]

    def test_test_writing_categories(self, phases_by_name):
        cats = phases_by_name["test_writing"]["allowed_tool_categories"]
        assert set(cats) == {"FILE_READ", "FILE_WRITE", "CODE_QUERY", "CODE_EDIT", "FILE_SEARCH", "SHELL_SAFE"}

    def test_test_writing_no_blocked(self, phases_by_name):
        assert phases_by_name["test_writing"]["blocked_tools"] == []

    def test_implement_categories(self, phases_by_name):
        cats = phases_by_name["implement"]["allowed_tool_categories"]
        assert set(cats) == {"FILE_READ", "FILE_WRITE", "CODE_QUERY", "CODE_EDIT", "FILE_SEARCH", "SHELL_SAFE"}

    def test_implement_no_blocked(self, phases_by_name):
        assert phases_by_name["implement"]["blocked_tools"] == []

    def test_test_categories(self, phases_by_name):
        cats = phases_by_name["test"]["allowed_tool_categories"]
        assert set(cats) == {"FILE_READ", "SHELL_SAFE"}

    def test_test_agents(self, phases_by_name):
        assert set(phases_by_name["test"]["eligible_agents"]) == {"implementer", "debugger"}

    def test_review_categories(self, phases_by_name):
        cats = phases_by_name["review"]["allowed_tool_categories"]
        assert set(cats) == {"FILE_READ", "CODE_QUERY"}

    def test_review_agents(self, phases_by_name):
        assert phases_by_name["review"]["eligible_agents"] == ["reviewer"]

    def test_merge_categories(self, phases_by_name):
        cats = phases_by_name["merge"]["allowed_tool_categories"]
        assert set(cats) == {"FILE_READ", "SHELL_SAFE"}

    def test_merge_agents(self, phases_by_name):
        assert phases_by_name["merge"]["eligible_agents"] == ["git-agent"]

    def test_acceptance_categories(self, phases_by_name):
        cats = phases_by_name["acceptance"]["allowed_tool_categories"]
        assert set(cats) == {"FILE_READ", "CODE_QUERY", "USER_INTERACTION"}

    def test_acceptance_agents(self, phases_by_name):
        assert phases_by_name["acceptance"]["eligible_agents"] == ["pm"]

    def test_complete_empty_categories(self, phases_by_name):
        assert phases_by_name["complete"]["allowed_tool_categories"] == []

    def test_complete_empty_blocked(self, phases_by_name):
        assert phases_by_name["complete"]["blocked_tools"] == []

    def test_complete_empty_agents(self, phases_by_name):
        assert phases_by_name["complete"]["eligible_agents"] == []


class TestTransitions:
    def test_all_forward_transitions(self, config):
        transitions = config["transitions"]
        forward_chain = [
            ("intake", "research"),
            ("research", "design"),
            ("design", "branch"),
            ("branch", "test_writing"),
            ("test_writing", "implement"),
            ("implement", "test"),
        ]
        for src, dst in forward_chain:
            assert dst in transitions[src], f"Missing forward transition {src}->{dst}"

    def test_test_kickbacks(self, config):
        targets = set(config["transitions"]["test"])
        assert targets == {"review", "implement"}

    def test_review_kickbacks(self, config):
        targets = set(config["transitions"]["review"])
        assert targets == {"merge", "implement", "test_writing"}

    def test_merge_kickbacks(self, config):
        targets = set(config["transitions"]["merge"])
        assert targets == {"acceptance", "implement"}

    def test_acceptance_kickbacks(self, config):
        targets = set(config["transitions"]["acceptance"])
        assert targets == {"complete", "implement", "test_writing"}

    def test_no_transition_from_complete(self, config):
        assert "complete" not in config["transitions"]

    def test_all_transition_sources_are_phases(self, config, phases_by_name):
        for src in config["transitions"]:
            assert src in phases_by_name

    def test_all_transition_targets_are_phases_or_terminal(self, config, phases_by_name):
        for src, targets in config["transitions"].items():
            for t in targets:
                assert t in phases_by_name or t == config["terminal_phase"]

    def test_full_transitions_match(self, config):
        actual = {
            src: set(targets) for src, targets in config["transitions"].items()
        }
        assert actual == EXPECTED_TRANSITIONS


class TestCustomConfig:
    def test_max_review_retries_present(self, config):
        assert "max_review_retries" in config
        assert config["max_review_retries"] == 0

    def test_max_agent_respawns_present(self, config):
        assert "max_agent_respawns" in config
        assert config["max_agent_respawns"] == 3

    def test_tickets_section_exists(self, config):
        assert "tickets" in config
        assert isinstance(config["tickets"], dict)

    def test_tickets_enabled(self, config):
        assert config["tickets"]["enabled"] is True

    def test_tickets_provider(self, config):
        assert config["tickets"]["provider"] == "github"

    def test_tickets_feature_ticket(self, config):
        assert config["tickets"]["feature_ticket"] is True

    def test_tickets_subtask_tickets(self, config):
        assert config["tickets"]["subtask_tickets"] is True

    def test_tickets_followup_tickets(self, config):
        assert config["tickets"]["followup_tickets"] is True


class TestDaemonLoading:
    """Verify that load_workflow_configs() from lib/daemon.py parses develop.yaml."""

    @pytest.fixture(scope="class")
    def loaded(self):
        from daemon import load_workflow_configs
        return load_workflow_configs(CONFIG_DIR)

    def test_develop_in_configs(self, loaded):
        assert "develop" in loaded

    def test_initial_phase(self, loaded):
        assert loaded["develop"].initial_phase == "intake"

    def test_terminal_phase(self, loaded):
        assert loaded["develop"].terminal_phase == "complete"

    def test_all_phases_loaded(self, loaded):
        assert set(loaded["develop"].phases.keys()) == set(ALL_PHASES)

    def test_checkpoint_phases_correct(self, loaded):
        wf = loaded["develop"]
        for name in ALL_PHASES:
            expected = name in CHECKPOINT_PHASES
            assert wf.phases[name].checkpoint is expected

    def test_transitions_loaded(self, loaded):
        wf = loaded["develop"]
        for src, expected_targets in EXPECTED_TRANSITIONS.items():
            assert wf.transitions[src] == expected_targets

    def test_no_extra_transitions(self, loaded):
        wf = loaded["develop"]
        assert set(wf.transitions.keys()) == set(EXPECTED_TRANSITIONS.keys())
