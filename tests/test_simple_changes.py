"""Non-regression tests for simple-workflow rollout (2026-05-09).

Narrow scope: these tests cover only what isn't already validated by
`lib/daemon.py:load_workflow_configs` (structural YAML) or by
integration smoke. They guard against:

1. The additive `simple:` block in permissions.yaml accidentally
   wiping pre-existing workflow blocks.
2. The auto-start hook still importing the legacy
   `implementer_workflow` module after the swap.
3. The auto-start hook calling the wrong workflow id or initial state.
"""
from __future__ import annotations

import sys
import importlib
from pathlib import Path
from unittest.mock import MagicMock, patch

import yaml

PROJECT_ROOT = Path(__file__).parent.parent
PERMISSIONS_YAML = PROJECT_ROOT / "config" / "permissions.yaml"
SESSION_START_PY = PROJECT_ROOT / "hooks" / "session-start.py"


class TestPermissionsAdditive:
    """Ensures simple: was added without removing pre-existing workflows."""

    def test_simple_block_present(self):
        with open(PERMISSIONS_YAML) as f:
            data = yaml.safe_load(f)
        assert "workflows" in data
        assert "simple" in data["workflows"], "simple: block missing"

    def test_pre_existing_workflows_preserved(self):
        with open(PERMISSIONS_YAML) as f:
            data = yaml.safe_load(f)
        wfs = data["workflows"]
        for name in ("iterate", "debug", "pr_review", "develop", "experiment"):
            assert name in wfs, f"pre-existing workflow {name!r} removed"

    def test_simple_plan_blocks_writes(self):
        with open(PERMISSIONS_YAML) as f:
            data = yaml.safe_load(f)
        blocked = set(data["workflows"]["simple"]["plan"]["blocked"])
        assert {"native__write_file", "native__edit_file", "native__bash"} <= blocked


class TestAutoStartSwap:
    """Confirms hooks/session-start.py auto-starts simple via DaemonClient."""

    def test_no_implementer_workflow_import(self):
        src = SESSION_START_PY.read_text()
        assert "from implementer_workflow import" not in src, (
            "session-start.py still imports implementer_workflow"
        )
        assert "ImplementerWorkflow" not in src, (
            "session-start.py still references ImplementerWorkflow"
        )

    def test_auto_start_calls_simple_workflow(self):
        # Load session-start.py as a module so we can call auto_start_workflow().
        # The hook prepends lib/ to sys.path at import time, which is what we want.
        sys.path.insert(0, str(PROJECT_ROOT / "lib"))
        spec = importlib.util.spec_from_file_location(
            "session_start_under_test", SESSION_START_PY
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        fake_dc = MagicMock()
        fake_dc.__enter__ = MagicMock(return_value=fake_dc)
        fake_dc.__exit__ = MagicMock(return_value=False)
        fake_dc.workflow_is_active = MagicMock(return_value=False)
        fake_dc.workflow_start = MagicMock(return_value={})

        with patch.dict("sys.modules", {"daemon_client": MagicMock(DaemonClient=lambda: fake_dc)}):
            mod.auto_start_workflow()

        fake_dc.workflow_is_active.assert_called_once_with("simple")
        fake_dc.workflow_start.assert_called_once_with(
            "simple", initial_state={"task": "Auto-started simple workflow"}
        )

    def test_auto_start_skips_when_already_active(self):
        sys.path.insert(0, str(PROJECT_ROOT / "lib"))
        spec = importlib.util.spec_from_file_location(
            "session_start_under_test_2", SESSION_START_PY
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        fake_dc = MagicMock()
        fake_dc.__enter__ = MagicMock(return_value=fake_dc)
        fake_dc.__exit__ = MagicMock(return_value=False)
        fake_dc.workflow_is_active = MagicMock(return_value=True)
        fake_dc.workflow_start = MagicMock(return_value={})

        with patch.dict("sys.modules", {"daemon_client": MagicMock(DaemonClient=lambda: fake_dc)}):
            mod.auto_start_workflow()

        fake_dc.workflow_is_active.assert_called_once_with("simple")
        fake_dc.workflow_start.assert_not_called()
