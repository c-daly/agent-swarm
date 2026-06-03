"""Tests for bin/mcp-call registration binding (issues #116/#117).

bin/mcp-call must not fabricate a default agent_type/workflow_id. Defaulting to
"implementer"/"iterate" silently fresh-binds an unknown caller id to the iterate
base on its first call -- bypassing the orchestrator-intended binding. When the
env vars are unset, mcp-call should send empty values so the daemon leaves the id
unbound (-> global/default-deny) until it is explicitly bound.
"""
import importlib.machinery
import importlib.util
from pathlib import Path
from unittest import mock

import pytest

_MCP_CALL = Path(__file__).resolve().parent.parent / "bin" / "mcp-call"


def _load_mcp_call():
    # bin/mcp-call has no .py extension, so spec_from_file_location can't infer a
    # loader -- supply a SourceFileLoader explicitly.
    loader = importlib.machinery.SourceFileLoader("mcp_call_under_test", str(_MCP_CALL))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


@pytest.fixture
def mcp_call():
    return _load_mcp_call()


def _patched_dc(mcp_call):
    """Return (context-manager mock, inner dc mock) wired for `with DaemonClient()`."""
    fake_dc = mock.MagicMock()
    cm = mock.MagicMock()
    cm.__enter__.return_value = fake_dc
    cm.__exit__.return_value = False
    return cm, fake_dc


def test_no_env_defaults_does_not_fabricate_iterate_implementer(mcp_call, monkeypatch):
    monkeypatch.delenv("AGENT_TYPE", raising=False)
    monkeypatch.delenv("WORKFLOW_ID", raising=False)

    cm, fake_dc = _patched_dc(mcp_call)
    with mock.patch.object(mcp_call, "DaemonClient", return_value=cm):
        mcp_call.call_tool("router__ping", {}, caller_id="harness-1")

    assert fake_dc.register.call_count == 1
    kwargs = fake_dc.register.call_args.kwargs
    assert kwargs["agent_id"] == "harness-1"
    # The whole point: NOT "implementer"/"iterate".
    assert kwargs["agent_type"] == ""
    assert kwargs["workflow_id"] == ""


def test_env_binding_is_respected_when_set(mcp_call, monkeypatch):
    monkeypatch.setenv("AGENT_TYPE", "git-agent")
    monkeypatch.setenv("WORKFLOW_ID", "develop")

    cm, fake_dc = _patched_dc(mcp_call)
    with mock.patch.object(mcp_call, "DaemonClient", return_value=cm):
        mcp_call.call_tool("router__ping", {}, caller_id="h2")

    kwargs = fake_dc.register.call_args.kwargs
    assert kwargs["agent_type"] == "git-agent"
    assert kwargs["workflow_id"] == "develop"


def test_no_caller_id_skips_registration(mcp_call):
    cm, fake_dc = _patched_dc(mcp_call)
    with mock.patch.object(mcp_call, "DaemonClient", return_value=cm):
        mcp_call.call_tool("router__ping", {})

    fake_dc.register.assert_not_called()
