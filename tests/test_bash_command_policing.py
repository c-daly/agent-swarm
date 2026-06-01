"""Cheap-layer compound-bash policing: decompose a command into sub-commands and
check each, so a compound command is allowed only if every part is allowed and
no part is superblocked. Fixes both the over-strict case (cd && git diff) and
the prefix-injection hole (git status && rm -rf)."""
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
PERMISSIONS_YAML = PROJECT_ROOT / "config" / "permissions.yaml"


@pytest.fixture
def checker():
    from permissions import PermissionChecker
    return PermissionChecker(PERMISSIONS_YAML)


def _reviewer():
    """Restricted: develop/review allows read-only git+pytest, agent blocks bare bash."""
    from permissions import AgentInfo
    return AgentInfo(agent_id="r", agent_type="reviewer", workflow="develop", phase="review")


def _implementer():
    """Permissive: bare native__bash via the global fallthrough."""
    from permissions import AgentInfo
    return AgentInfo(agent_id="i", agent_type="implementer")


def _ok(checker, agent, cmd):
    allowed, _ = checker.check("native__bash", {"command": cmd}, agent)
    return allowed


# ── Restricted phase (reviewer @ develop/review) ─────────────────────────────
class TestRestricted:
    def test_bare_allowed_command(self, checker):
        assert _ok(checker, _reviewer(), "git diff --stat 8165456 HEAD")

    def test_cd_prefixed_now_allowed(self, checker):           # was wrongly BLOCKED
        assert _ok(checker, _reviewer(), "cd /home/x/repo && git diff --stat")

    def test_pipe_to_benign_pager_allowed(self, checker):
        assert _ok(checker, _reviewer(), "git log --oneline | head -5")

    def test_chained_rm_now_blocked(self, checker):            # was wrongly ALLOWED (injection)
        assert not _ok(checker, _reviewer(), "git status && rm -rf /tmp/__x__")

    def test_semicolon_injection_blocked(self, checker):
        assert not _ok(checker, _reviewer(), "git log ; rm -rf /tmp/__x__")

    def test_command_substitution_blocked(self, checker):
        assert not _ok(checker, _reviewer(), "git diff $(rm -rf /tmp/__x__)")

    def test_backtick_substitution_blocked(self, checker):
        assert not _ok(checker, _reviewer(), "git diff `rm -rf /tmp/__x__`")

    def test_write_redirect_blocked(self, checker):
        assert not _ok(checker, _reviewer(), "git diff > /tmp/__stolen__")

    def test_pipe_to_sh_blocked(self, checker):
        assert not _ok(checker, _reviewer(), "git log | sh")

    def test_newline_injection_blocked(self, checker):
        assert not _ok(checker, _reviewer(), "git diff\nrm -rf /tmp/__x__")

    def test_disallowed_single_still_blocked(self, checker):   # unchanged behavior
        assert not _ok(checker, _reviewer(), "ls -la")

    def test_env_prefix_blocked(self, checker):
        assert not _ok(checker, _reviewer(), "PATH=/tmp git diff")

    def test_unparseable_fails_closed(self, checker):
        # unbalanced quote -> shlex can't tokenize -> restricted fails closed
        assert not _ok(checker, _reviewer(), 'git diff "unterminated')


# ── Permissive phase (implementer, bare bash) ────────────────────────────────
class TestPermissive:
    def test_arbitrary_command_allowed(self, checker):
        assert _ok(checker, _implementer(), "ls -la")

    def test_substitution_allowed_when_permissive(self, checker):
        assert _ok(checker, _implementer(), "git tag v$(cat VERSION)")

    def test_injection_still_blocked_by_superblock(self, checker):   # per-sub superblock
        assert not _ok(checker, _implementer(), "echo hi && rm -rf /tmp/__x__")

    def test_bare_rm_blocked(self, checker):
        assert not _ok(checker, _implementer(), "rm -rf /tmp/__x__")

    def test_unparseable_falls_back_allowed(self, checker):
        # a caller with a bare-bash grant already has full shell; an undecomposable
        # command falls back to the single-command check rather than failing closed
        assert _ok(checker, _implementer(), 'echo "unterminated')


# ── Hook gate: native-tool-blocking only allows a clean single mcp-call ───────
def _load_hook():
    import importlib.util
    from importlib.machinery import SourceFileLoader

    path = PROJECT_ROOT / "hooks" / "native-tool-blocking.py"
    loader = SourceFileLoader("ntb_hook", str(path))
    spec = importlib.util.spec_from_loader("ntb_hook", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


class TestHookMcpCallGate:
    @pytest.fixture
    def hook(self):
        return _load_hook()

    def test_clean_mcp_call_allowed(self, hook):
        assert hook._is_clean_mcp_call(
            "mcp-call --caller-id=r native__read_file '{\"file_path\": \"/x\"}'"
        )

    def test_shell_alias_allowed(self, hook):
        assert hook._is_clean_mcp_call("mcp-call --caller-id=r git diff --stat")

    def test_inner_json_ampersand_allowed(self, hook):
        # && inside the quoted JSON is the inner command (router polices it), not chaining
        assert hook._is_clean_mcp_call(
            "mcp-call --caller-id=i native__bash '{\"command\": \"git diff && pytest\"}'"
        )

    def test_chaining_blocked(self, hook):
        assert not hook._is_clean_mcp_call("mcp-call native__read_file '{}' ; rm -rf /tmp/x")

    def test_pipe_blocked(self, hook):
        assert not hook._is_clean_mcp_call("mcp-call git log | sh")

    def test_substitution_blocked(self, hook):
        assert not hook._is_clean_mcp_call("mcp-call native__read_file $(rm -rf /tmp/x)")

    def test_backtick_blocked(self, hook):
        assert not hook._is_clean_mcp_call("mcp-call foo `rm -rf /tmp/x`")

    def test_non_mcp_call_rejected(self, hook):
        assert not hook._is_clean_mcp_call("git diff")
