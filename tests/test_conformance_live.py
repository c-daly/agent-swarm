"""Live conformance — Slice 2 of the L1 conformance harness (#104/#105).

Spins up a HERMETIC in-process daemon loaded from the REAL config (so the
governance cascade is active) and drives the `simple` workflow end-to-end
against it, asserting the runtime governance matches the declared config:

  * binding: workflow_start binds the caller to the initial phase (the
    workflow_start binding fix in controller._wf_start);
  * per-phase tool gating matches config/permissions.yaml workflows['simple'];
  * legal transitions advance + propagate the bound agent's phase, illegal
    transitions are rejected, and the terminal phase is reached.

Unlike Slice 1 (lib/conformance.py, static), this exercises the live
daemon + router + controller assembly. Hermetic (own ephemeral port, tmp
data dir) so it is reproducible and needs no shared daemon.

The telemetry phase-stamp assertion is deferred until the datastore `phase`
column lands (PR #111); binding/gating/transitions do not depend on it.
"""

from __future__ import annotations

import shutil
import socket
import threading
import time
from pathlib import Path

import pytest

from lib.controller import Controller
from lib.daemon_client import DaemonClient
from lib.router import Router

PLUGIN_ROOT = Path(__file__).resolve().parent.parent


def _free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture()
def governed_daemon(tmp_path):
    """In-process daemon loaded from the REAL config so governance is active."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    shutil.copy(PLUGIN_ROOT / "config" / "permissions.yaml", config_dir / "permissions.yaml")
    shutil.copytree(PLUGIN_ROOT / "config" / "workflows", config_dir / "workflows")
    (config_dir / "backends.json").write_text("{}")
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    port = _free_port()
    from lib.daemon import load_workflow_configs
    workflow_configs = load_workflow_configs(config_dir)
    controller = Controller(
        config_dir=config_dir, data_dir=data_dir, workflow_configs=workflow_configs
    )
    router = Router(port=port, controller=controller)
    thread = threading.Thread(target=router.serve_forever, daemon=True)
    thread.start()
    for _ in range(30):
        try:
            probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            probe.settimeout(0.5)
            probe.connect(("127.0.0.1", port))
            probe.close()
            break
        except OSError:
            time.sleep(0.1)
    else:
        pytest.fail("hermetic daemon did not start")

    yield {"port": port, "controller": controller}

    router.shutdown()
    thread.join(timeout=3)


# config/permissions.yaml workflows['simple'] is the oracle. One representative
# allowed + blocked tool per phase that the L1 layer decides outright.
SIMPLE_GATING = {
    "plan": ("native__read_file", "native__write_file"),
    "work": ("native__write_file", None),
    "verify": ("native__read_file", "native__write_file"),
}


def _assert_gating(controller, agent_id, phase):
    agent = controller.permissions.get_agent(agent_id)
    assert agent.phase == phase, f"expected phase {phase}, agent is in {agent.phase}"
    allowed_tool, blocked_tool = SIMPLE_GATING[phase]
    ok, _ = controller.permissions.check(allowed_tool, {}, agent)
    assert ok, f"{allowed_tool} should be ALLOWED in simple/{phase}"
    if blocked_tool is not None:
        ok, _ = controller.permissions.check(blocked_tool, {}, agent)
        assert not ok, f"{blocked_tool} should be BLOCKED in simple/{phase}"


def test_simple_live_conformance(governed_daemon):
    controller = governed_daemon["controller"]
    agent_id = "conf-simple"
    client = DaemonClient(port=governed_daemon["port"], timeout=5.0)
    client.connect()
    # Register as orchestrator: at workflow_start time the caller isn't yet in a
    # phase, so L1 is skipped and the agent-type layer decides — only an
    # orchestrator-class type is allowed to start (and thus get bound to) a workflow.
    client.register(
        agent_id=agent_id, agent_type="orchestrator",
        session_id="conformance", workflow_id="",
    )
    try:
        # binding: workflow_start binds the caller to the initial phase.
        # bin/mcp-router stamps `_caller` from --caller-id at the source; the bare
        # DaemonClient helper omits it, so replicate that stamping here so the
        # daemon resolves our registered identity (and binds us).
        state = client._call("workflow/start", {
            "workflow_id": "simple", "initial_state": {}, "_caller": agent_id,
        })
        assert state.get("phase") == "plan"
        bound = controller.permissions.get_agent(agent_id)
        assert bound.workflow == "simple", f"caller not bound to simple (workflow={bound.workflow})"
        assert bound.phase == "plan", f"caller not bound to plan (phase={bound.phase})"

        # per-phase gating + legal transitions plan -> work -> verify
        _assert_gating(controller, agent_id, "plan")
        client.workflow_pass_checkpoint("simple")  # plan is a checkpoint
        client.workflow_advance_phase("simple", "work")
        _assert_gating(controller, agent_id, "work")
        client.workflow_advance_phase("simple", "verify")  # work has no checkpoint
        _assert_gating(controller, agent_id, "verify")

        # illegal transition is rejected (verify -> plan is not a legal edge)
        with pytest.raises(Exception, match="Invalid transition"):
            client.workflow_advance_phase("simple", "plan")

        # reach terminal
        client.workflow_pass_checkpoint("simple")  # verify is a checkpoint
        client.workflow_advance_phase("simple", "done")
        assert controller.permissions.get_agent(agent_id).phase == "done"
    finally:
        client.workflow_stop("simple")
        client.close()
