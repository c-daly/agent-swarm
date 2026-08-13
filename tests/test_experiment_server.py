"""Tests for the experiment MCP server's tool surface and dispatch.

The stdio loop mirrors workflow_server.py; the dispatch is extracted into
handle_call() so it can be exercised without the JSON-RPC transport.
"""

import json

import pytest

from experiment_store import LocalFsExperimentStore, open_experiment_writer
from experiment_server import TOOLS, handle_call, store_from_env


_WRITER_TOOLS = {"experiment_start_run", "experiment_record_observation", "experiment_end_run"}
_READER_TOOLS = {"experiment_list_runs", "experiment_get_run", "experiment_observations"}


@pytest.fixture
def rw(tmp_path):
    store = LocalFsExperimentStore(tmp_path / "e")
    writer = open_experiment_writer(store, memory=False)
    return store, writer


def test_tools_list_covers_reader_and_writer():
    names = {t["name"] for t in TOOLS}
    assert _WRITER_TOOLS <= names
    assert _READER_TOOLS <= names
    for t in TOOLS:
        assert "inputSchema" in t and t["description"]


def test_start_record_observations_roundtrip(rw):
    store, writer = rw
    text, err = handle_call(store, writer, "experiment_start_run",
                            {"experiment": "exp", "goal": "g"})
    assert not err
    run_id = json.loads(text)["run_id"]

    _, err = handle_call(store, writer, "experiment_record_observation",
                         {"run_id": run_id, "observation": {"title": "t", "hypothesis": "h"}})
    assert not err

    text, err = handle_call(store, writer, "experiment_observations", {"run_id": run_id})
    assert not err
    obs = json.loads(text)
    assert len(obs) == 1 and obs[0]["title"] == "t" and obs[0]["number"] == 1


def test_end_run_and_get_run(rw):
    store, writer = rw
    run_id = json.loads(handle_call(store, writer, "experiment_start_run",
                                    {"experiment": "exp", "goal": "g"})[0])["run_id"]
    _, err = handle_call(store, writer, "experiment_end_run",
                         {"run_id": run_id, "outcome": "success", "metrics": {"acc": 1.0}})
    assert not err
    text, err = handle_call(store, writer, "experiment_get_run", {"run_id": run_id})
    assert not err
    run = json.loads(text)
    assert run["outcome"] == "success" and run["metrics"]["acc"] == 1.0


def test_get_run_missing_is_error(rw):
    store, writer = rw
    _, err = handle_call(store, writer, "experiment_get_run", {"run_id": "exp/run-999"})
    assert err


def test_unknown_tool_is_error(rw):
    store, writer = rw
    _, err = handle_call(store, writer, "experiment_bogus", {})
    assert err


def test_store_from_env_local(tmp_path):
    env = {"EXPERIMENT_STORE_BACKEND": "local",
           "EXPERIMENT_STORE_ROOT": str(tmp_path / "e")}
    assert isinstance(store_from_env(env), LocalFsExperimentStore)


def test_store_from_env_defaults_to_vault(tmp_path):
    from experiment_store import VaultExperimentStore
    env = {"VAULT_DIR": str(tmp_path), "EXPERIMENT_PROJECT": "agent-swarm"}
    assert isinstance(store_from_env(env), VaultExperimentStore)
