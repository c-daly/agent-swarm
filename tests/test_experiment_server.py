"""Tests for the experiment MCP server: tool surface, dispatch, and per-project
routing.

The stdio loop mirrors workflow_server.py; dispatch is extracted into
handle_call(server, name, args) so it can be exercised without the transport.
A single ExperimentServer multiplexes projects — the optional `project`
argument selects the vault subtree; the local backend is single-root.
"""

import json

import pytest

from experiment_store import LocalFsExperimentStore, VaultExperimentStore
from experiment_server import TOOLS, ExperimentServer, handle_call, store_from_env

_WRITER_TOOLS = {"experiment_start_run", "experiment_record_observation", "experiment_end_run"}
_READER_TOOLS = {"experiment_list_runs", "experiment_get_run", "experiment_observations"}


@pytest.fixture
def local_server(tmp_path):
    return ExperimentServer(env={"EXPERIMENT_STORE_BACKEND": "local",
                                 "EXPERIMENT_STORE_ROOT": str(tmp_path / "e")})


def test_tools_list_covers_reader_and_writer():
    names = {t["name"] for t in TOOLS}
    assert _WRITER_TOOLS <= names
    assert _READER_TOOLS <= names
    for t in TOOLS:
        assert "inputSchema" in t and t["description"]
        # every tool accepts optional project routing
        assert "project" in t["inputSchema"]["properties"]
        assert "project" not in t["inputSchema"].get("required", [])


def test_start_record_observations_roundtrip(local_server):
    text, err = handle_call(local_server, "experiment_start_run",
                            {"experiment": "exp", "goal": "g"})
    assert not err
    run_id = json.loads(text)["run_id"]

    _, err = handle_call(local_server, "experiment_record_observation",
                         {"run_id": run_id, "observation": {"title": "t", "hypothesis": "h"}})
    assert not err

    text, err = handle_call(local_server, "experiment_observations", {"run_id": run_id})
    assert not err
    obs = json.loads(text)
    assert len(obs) == 1 and obs[0]["title"] == "t" and obs[0]["number"] == 1


def test_end_run_and_get_run(local_server):
    run_id = json.loads(handle_call(local_server, "experiment_start_run",
                                    {"experiment": "exp", "goal": "g"})[0])["run_id"]
    _, err = handle_call(local_server, "experiment_end_run",
                         {"run_id": run_id, "outcome": "success", "metrics": {"acc": 1.0}})
    assert not err
    text, err = handle_call(local_server, "experiment_get_run", {"run_id": run_id})
    assert not err
    run = json.loads(text)
    assert run["outcome"] == "success" and run["metrics"]["acc"] == 1.0


def test_get_run_missing_is_error(local_server):
    _, err = handle_call(local_server, "experiment_get_run", {"run_id": "exp/run-999"})
    assert err


def test_unknown_tool_is_error(local_server):
    _, err = handle_call(local_server, "experiment_bogus", {})
    assert err


def test_store_from_env_local(tmp_path):
    env = {"EXPERIMENT_STORE_BACKEND": "local", "EXPERIMENT_STORE_ROOT": str(tmp_path / "e")}
    assert isinstance(store_from_env(env), LocalFsExperimentStore)


def test_store_from_env_defaults_to_vault(tmp_path):
    env = {"VAULT_DIR": str(tmp_path), "EXPERIMENT_PROJECT": "agent-swarm"}
    assert isinstance(store_from_env(env), VaultExperimentStore)


def test_store_from_env_project_override(tmp_path):
    env = {"VAULT_DIR": str(tmp_path), "EXPERIMENT_PROJECT": "default-proj"}
    store = store_from_env(env, project="other-proj")
    assert store.project == "other-proj"


# -- per-project routing -----------------------------------------------------

def test_server_routes_by_project_to_distinct_subtrees(tmp_path):
    vault = tmp_path / "vault"
    server = ExperimentServer(env={"EXPERIMENT_STORE_BACKEND": "vault",
                                   "VAULT_DIR": str(vault)})
    ra = json.loads(handle_call(server, "experiment_start_run",
                                {"experiment": "e", "goal": "g", "project": "proj-a"})[0])["run_id"]
    handle_call(server, "experiment_start_run",
                {"experiment": "e", "goal": "g", "project": "proj-b"})
    assert (vault / "10-projects" / "proj-a" / "experiments" / "e" / "runs").exists()
    assert (vault / "10-projects" / "proj-b" / "experiments" / "e" / "runs").exists()

    # reads route by project too
    _, err = handle_call(server, "experiment_record_observation",
                         {"run_id": ra, "observation": {"title": "a"}, "project": "proj-a"})
    assert not err
    obs = json.loads(handle_call(server, "experiment_observations",
                                 {"run_id": ra, "project": "proj-a"})[0])
    assert len(obs) == 1


def test_server_uses_default_project_when_omitted(tmp_path):
    vault = tmp_path / "vault"
    server = ExperimentServer(env={"EXPERIMENT_STORE_BACKEND": "vault",
                                   "VAULT_DIR": str(vault),
                                   "EXPERIMENT_PROJECT": "default-proj"})
    handle_call(server, "experiment_start_run", {"experiment": "e", "goal": "g"})
    assert (vault / "10-projects" / "default-proj" / "experiments" / "e" / "runs").exists()


def test_stores_cached_per_project(tmp_path):
    server = ExperimentServer(env={"EXPERIMENT_STORE_BACKEND": "vault",
                                   "VAULT_DIR": str(tmp_path)})
    assert server.stores_for("x") is server.stores_for("x")
    assert server.stores_for("x") is not server.stores_for("y")
