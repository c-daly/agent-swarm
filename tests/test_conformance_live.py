"""Live conformance — Slice 2 of the L1 conformance harness (#104/#105).

Spins up a HERMETIC in-process daemon loaded from the REAL config (so the
governance cascade is active) and drives the `simple` workflow end-to-end
against it, asserting the runtime governance matches the declared config:

  * binding: workflow_start binds the caller to the initial phase (the
    workflow_start binding fix in controller._wf_start);
  * per-phase tool gating matches config/permissions.yaml workflows['simple'];
  * legal transitions advance + propagate the bound agent's phase, illegal
    transitions are rejected, and the terminal phase is reached;
  * telemetry: each tool call's event is stamped with the agent's bound phase.

Unlike Slice 1 (lib/conformance.py, static), this exercises the live
daemon + router + controller assembly. Hermetic (own ephemeral port, tmp
data dir) so it is reproducible and needs no shared daemon.

Telemetry phase-stamping (the datastore `phase` column, which has since landed)
is asserted by test_tool_call_telemetry_is_phase_stamped.
"""

from __future__ import annotations

import shutil
import socket
import threading
import time
from pathlib import Path

import pytest

from lib.controller import Controller
from lib.daemon_client import DaemonClient, DaemonError
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
    assert agent is not None, f"agent {agent_id} is not registered"
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
        with pytest.raises(DaemonError, match="Invalid transition"):
            client.workflow_advance_phase("simple", "plan")

        # reach terminal
        client.workflow_pass_checkpoint("simple")  # verify is a checkpoint
        client.workflow_advance_phase("simple", "done")
        assert controller.permissions.get_agent(agent_id).phase == "done"
    finally:
        try:
            client.workflow_stop("simple")
        except DaemonError:
            pass  # workflow may never have started if an earlier assertion failed
        client.close()


def test_tool_call_telemetry_is_phase_stamped(governed_daemon, tmp_path):
    """Each tool call's telemetry event is stamped with the agent's bound phase
    (datastore `phase` column) -- the assertion #104 deferred until the column
    landed. Drive a real allowed tool through the controller, then read the
    recorded event back and assert its phase + workflow match the binding."""
    controller = governed_daemon["controller"]
    agent_id = "conf-telemetry"
    # Read a file inside the hermetic sandbox (same tmp_path the fixture uses),
    # not the real project tree, so the test stays self-contained.
    probe = tmp_path / "telemetry_probe.txt"
    probe.write_text("conformance telemetry probe")
    with DaemonClient(port=governed_daemon["port"], timeout=5.0) as client:
        client.register(
            agent_id=agent_id, agent_type="orchestrator",
            session_id="telemetry", workflow_id="",
        )
        # workflow_start binds the caller to simple/plan; native__read_file is
        # allowed in plan, so the call succeeds and records a success event.
        client._call("workflow/start", {
            "workflow_id": "simple", "initial_state": {}, "_caller": agent_id,
        })
        controller.handle_call("native__read_file", {
            "file_path": str(probe), "_caller": agent_id,
        })
    # Filter by agent_id in Python: the session_id passed to register() is not
    # propagated onto AgentInfo, so the recorded event's session_id is "" and a
    # DB-layer session_id filter would match nothing (see PR #127 review).
    events = [
        e for e in controller.data.query_events(
            tool="native__read_file", status="success")
        if e.agent_id == agent_id
    ]
    assert events, "no success telemetry recorded for the read_file call"
    assert events[-1].phase == "plan", (
        f"event not stamped with bound phase (phase={events[-1].phase!r})")
    assert events[-1].workflow_id == "simple"
