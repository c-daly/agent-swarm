#!/usr/bin/env python3
"""Experiment (reader, writer) MCP Server.

Exposes experiment's reader/writer contract over stdio so the router can mount
it as the ``experiment`` backend (tool_prefix ``experiment`` in
config/backends.json), alongside ``workflow`` and ``native``. Mirrors
workflow_server.py's plain JSON-RPC stdio loop.

A single server multiplexes projects: the optional ``project`` argument on each
call selects the vault subtree (``<vault>/10-projects/<project>/experiments/``);
omitted, it falls back to ``EXPERIMENT_PROJECT``. The local backend is
single-root and ignores project. A registered memory plugin is used additively
via presence-gated mirroring — memory stays optional.
"""

import json
import os
import sys
from pathlib import Path

lib_dir = Path(__file__).parent
if str(lib_dir) not in sys.path:
    sys.path.insert(0, str(lib_dir))

from experiment_store import (  # noqa: E402
    Observation,
    Run,
    make_experiment_backend,
    open_experiment_writer,
)

_OBS_FIELDS = ("title", "hypothesis", "changes", "result", "diagnosis", "next_direction")
_DEFAULT_PROJECT = "agent-swarm"


# ---------------------------------------------------------------------------
# Backend resolution + per-project routing
# ---------------------------------------------------------------------------

def store_from_env(env=None, project=None):
    """Build the base store from environment configuration.

    ``EXPERIMENT_STORE_BACKEND`` selects vault (default) or local. Vault dir
    resolves from EXPERIMENT_VAULT_DIR / VAULT_DIR / MEMORY_VAULT_DIR; the
    project from the ``project`` argument, else EXPERIMENT_PROJECT.
    """
    env = env if env is not None else os.environ
    backend = env.get("EXPERIMENT_STORE_BACKEND", "vault")
    if backend == "local":
        return make_experiment_backend("local", root=env.get("EXPERIMENT_STORE_ROOT"))
    return make_experiment_backend(
        "vault",
        vault_dir=(env.get("EXPERIMENT_VAULT_DIR") or env.get("VAULT_DIR")
                   or env.get("MEMORY_VAULT_DIR")),
        project=project or env.get("EXPERIMENT_PROJECT", _DEFAULT_PROJECT),
    )


class ExperimentServer:
    """Routes experiment tool calls to per-project (reader, writer) stores.

    ``stores_for(project)`` returns a cached ``(reader, writer)`` pair for the
    project's subtree; the writer wraps the base store with presence-gated
    memory mirroring. The local backend is single-root, so all projects share
    one store there.
    """

    def __init__(self, env=None):
        self.env = env if env is not None else os.environ
        self._cache: dict[str, tuple] = {}

    def stores_for(self, project=None):
        key = project or self.env.get("EXPERIMENT_PROJECT", _DEFAULT_PROJECT)
        if key not in self._cache:
            base = store_from_env(self.env, project=key)
            self._cache[key] = (base, open_experiment_writer(base))
        return self._cache[key]


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------

def _run_dict(run: Run) -> dict:
    return {
        "run_id": run.run_id,
        "experiment": run.experiment,
        "goal": run.goal,
        "started_at": run.started_at,
        "ended_at": run.ended_at,
        "outcome": run.outcome,
        "metrics": run.metrics,
    }


def _obs_dict(obs: Observation) -> dict:
    d = {"run_id": obs.run_id, "number": obs.number}
    for f in _OBS_FIELDS:
        d[f] = getattr(obs, f)
    return d


def _observation_from_args(payload: dict) -> Observation:
    payload = payload or {}
    return Observation(**{f: payload.get(f, "") for f in _OBS_FIELDS})


# ---------------------------------------------------------------------------
# Dispatch (transport-independent, unit-testable)
# ---------------------------------------------------------------------------

def handle_call(server: ExperimentServer, name: str, args: dict) -> tuple[str, bool]:
    """Execute one tool call, routing by args['project']. Returns (text, is_error)."""
    args = args or {}
    try:
        reader, writer = server.stores_for(args.get("project"))
        if name == "experiment_start_run":
            run_id = writer.start_run(args["experiment"], args.get("goal", ""))
            return json.dumps({"run_id": run_id}), False
        if name == "experiment_record_observation":
            obs_id = writer.record_observation(
                args["run_id"], _observation_from_args(args.get("observation")))
            return json.dumps({"observation_id": obs_id}), False
        if name == "experiment_end_run":
            writer.end_run(args["run_id"], args.get("outcome", ""), args.get("metrics", {}))
            return json.dumps({"success": True}), False
        if name == "experiment_list_runs":
            return json.dumps([_run_dict(r) for r in reader.list_runs(args["experiment"])]), False
        if name == "experiment_get_run":
            return json.dumps(_run_dict(reader.get_run(args["run_id"]))), False
        if name == "experiment_observations":
            return json.dumps([_obs_dict(o) for o in reader.observations(args["run_id"])]), False
        return f"Unknown tool: {name}", True
    except KeyError as e:
        return f"Missing or unknown key: {e}", True
    except (ValueError, RuntimeError) as e:
        return str(e), True


# ---------------------------------------------------------------------------
# MCP tool definitions
# ---------------------------------------------------------------------------

_PROJECT_PROP = {
    "project": {
        "type": "string",
        "description": "Vault project subtree (optional; defaults to EXPERIMENT_PROJECT).",
    }
}
_OBSERVATION_SCHEMA = {
    "type": "object",
    "properties": {f: {"type": "string"} for f in _OBS_FIELDS},
    "description": "Observation fields (title required; rest optional prose).",
}


def _tool(name, description, properties, required):
    return {
        "name": name,
        "description": description,
        "inputSchema": {
            "type": "object",
            "properties": {**properties, **_PROJECT_PROP},
            "required": required,
        },
    }


TOOLS = [
    _tool("experiment_start_run", "Begin an experiment run; returns its run_id.",
          {"experiment": {"type": "string", "description": "Experiment name"},
           "goal": {"type": "string", "description": "Run objective"}},
          ["experiment"]),
    _tool("experiment_record_observation",
          "Append an observation (journal attempt) to a run.",
          {"run_id": {"type": "string"}, "observation": _OBSERVATION_SCHEMA},
          ["run_id", "observation"]),
    _tool("experiment_end_run", "Finalize a run with an outcome and metrics.",
          {"run_id": {"type": "string"}, "outcome": {"type": "string"},
           "metrics": {"type": "object"}},
          ["run_id", "outcome"]),
    _tool("experiment_list_runs", "List all runs for an experiment.",
          {"experiment": {"type": "string"}}, ["experiment"]),
    _tool("experiment_get_run", "Get one run by run_id.",
          {"run_id": {"type": "string"}}, ["run_id"]),
    _tool("experiment_observations", "List a run's observations in order.",
          {"run_id": {"type": "string"}}, ["run_id"]),
]


# ---------------------------------------------------------------------------
# MCP server loop (mirrors workflow_server.py)
# ---------------------------------------------------------------------------

def run_server():
    """Run the MCP server loop on stdio."""
    server = ExperimentServer()

    def send(msg: dict) -> None:
        print(json.dumps(msg), flush=True)

    for line in sys.stdin:
        request_id = None
        try:
            request = json.loads(line.strip())
            method = request.get("method", "")
            params = request.get("params", {})
            request_id = request.get("id")

            if method == "initialize":
                result = {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "experiment-server", "version": "1.0.0"},
                }
            elif method == "notifications/initialized":
                continue
            elif method == "tools/list":
                result = {"tools": TOOLS}
            elif method == "tools/call":
                text, is_error = handle_call(
                    server, params.get("name", ""), params.get("arguments", {}))
                result = {"content": [{"type": "text", "text": text}]}
                if is_error:
                    result["isError"] = True
            else:
                result = {"error": f"Unknown method: {method}"}

            if request_id is not None:
                send({"jsonrpc": "2.0", "id": request_id, "result": result})

        except json.JSONDecodeError as e:
            send({"jsonrpc": "2.0", "id": request_id,
                  "error": {"code": -32700, "message": f"Parse error: {e}"}})
        except Exception as e:  # noqa: BLE001
            send({"jsonrpc": "2.0", "id": request_id,
                  "error": {"code": -32603, "message": str(e)}})


if __name__ == "__main__":
    run_server()
