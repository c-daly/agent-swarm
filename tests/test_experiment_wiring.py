"""Guards the shipped wiring that makes the experiment MCP backend usable
through the router: it must be registered as a backend AND granted in the
global permission allowlist. Either missing means the tools are silently
unreachable (exposed-but-blocked, or not spawned at all).
"""

import json
from pathlib import Path

import yaml

_CONFIG = Path(__file__).parent.parent / "config"


def test_experiment_backend_registered():
    backends = json.loads((_CONFIG / "backends.json").read_text())
    assert "experiment" in backends, "experiment backend missing from backends.json"
    exp = backends["experiment"]
    assert exp.get("tool_prefix") == "experiment"
    assert exp["command"][-1].endswith("experiment_server.py")


def test_experiment_tools_granted_globally():
    perms = yaml.safe_load((_CONFIG / "permissions.yaml").read_text())
    assert "experiment__*" in perms["global"]["allowed"], (
        "experiment__* not in global.allowed — tools would be exposed but "
        "denied by the permission checker")
