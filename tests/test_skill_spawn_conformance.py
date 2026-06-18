"""Static conformance gate for skill spawn-protocol compliance.

Pins the post-fix contract so that doc drift (prescribing native subagent
types, dropping register_agent/briefing references) cannot silently
re-enter any spawning skill.

Rules enforced:
  1. No spawning skill prescribes a native subagent type (general-purpose,
     Explore, Plan) unless the file carries the exemption marker, is
     skills/spawn/SKILL.md itself, or the matching line is a negative
     instruction (contains "never", "not", or "don't", case-insensitive).
  2. Every spawning skill references the dispatch protocol (register_agent,
     briefing, or skills/spawn); exempt-marked files pass via marker.
  3. The two fixed skills (delegate, parallel-orchestrate) each contain
     register_agent AND reg["briefing"].
  4. hooks/agent-dispatch.py contains "## Your Agent Identity".

A spawning skill is any skills/*/SKILL.md containing "subagent_type".
"""

import re
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Repo root -- resolve from this file location (tests/ -> parent)
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = REPO_ROOT / "skills"
HOOKS_DIR = REPO_ROOT / "hooks"

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EXEMPTION_MARKER = "<!-- spawn-conformance: native-teams-exempt -->"

# Prescription patterns -- positive prescription of a native subagent type.
# Matches: subagent_type: "X", subagent_type: 'X', subagent_type = "X"
_NATIVE_TYPES = ["general-purpose", "Explore", "Plan"]
_PRESCRIPTION_RE = re.compile(
    r"subagent_type\s*[:=]\s*[\"'](" + "|".join(re.escape(t) for t in _NATIVE_TYPES) + r")[\"']"
)

# Protocol reference: at least one must appear in a spawning skill.
_PROTOCOL_REFS = ["register_agent", "briefing", "skills/spawn"]

# The two skills pinned by test 3.
_FIXED_SKILLS = ["delegate", "parallel-orchestrate"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _spawning_skills() -> list[Path]:
    """Return all skills/*/SKILL.md paths containing subagent_type."""
    candidates = sorted(SKILLS_DIR.glob("*/SKILL.md"))
    return [p for p in candidates if "subagent_type" in p.read_text(encoding="utf-8")]


def _is_negative_instruction(line: str) -> bool:
    """Return True if the line is a prohibition or warning (case-insensitive)."""
    line_lower = line.lower()
    return any(kw in line_lower for kw in ("never", "not", "don't"))


def _offending_prescriptions(text: str, path: Path) -> list[str]:
    """Return lines that positively prescribe a native subagent type.

    A line is offending iff: it matches _PRESCRIPTION_RE AND the file is not
    skills/spawn/SKILL.md AND the line is not a negative instruction.
    """
    if path.parent.name == "spawn":
        return []
    offending = []
    for line in text.splitlines():
        if _PRESCRIPTION_RE.search(line) and not _is_negative_instruction(line):
            offending.append(line.strip())
    return offending


def _skill_id(path: Path) -> str:
    return path.parent.name


# ---------------------------------------------------------------------------
# Test 1 -- No spawning skill prescribes a native type (unless exempt)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("skill_path", _spawning_skills(), ids=_skill_id)
def test_no_native_type_prescription(skill_path: Path) -> None:
    """A spawning skill must not positively prescribe a native subagent type.

    Exempt: file carries the exemption marker; file is skills/spawn/SKILL.md;
    or the matching line is a negative instruction.
    """
    text = skill_path.read_text(encoding="utf-8")
    if EXEMPTION_MARKER in text:
        return  # Exempt via marker -- pass.
    offending = _offending_prescriptions(text, skill_path)
    assert not offending, (
        f"{skill_path.relative_to(REPO_ROOT)} positively prescribes a native "
        f"subagent type on line(s): {offending!r}\n"
        "Add register_agent+briefing pattern and remove or negate the "
        f"prescription, or add the exemption marker {EXEMPTION_MARKER!r}."
    )


# ---------------------------------------------------------------------------
# Test 2 -- Every spawning skill references the dispatch protocol
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("skill_path", _spawning_skills(), ids=_skill_id)
def test_spawning_skill_references_protocol(skill_path: Path) -> None:
    """A spawning skill must reference at least one of: register_agent,
    briefing, or skills/spawn -- OR carry the exemption marker.
    """
    text = skill_path.read_text(encoding="utf-8")
    if EXEMPTION_MARKER in text:
        return  # Exempt via marker -- pass.
    has_ref = any(ref in text for ref in _PROTOCOL_REFS)
    assert has_ref, (
        f"{skill_path.relative_to(REPO_ROOT)} contains subagent_type but "
        f"references none of {_PROTOCOL_REFS!r}.\n"
        "Add register_agent / briefing references per the spawn protocol, "
        f"or add the exemption marker {EXEMPTION_MARKER!r}."
    )


# ---------------------------------------------------------------------------
# Test 3 -- delegate and parallel-orchestrate contain protocol primitives
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("skill_name", _FIXED_SKILLS)
def test_fixed_skills_contain_protocol_primitives(skill_name: str) -> None:
    """Post-fix: delegate and parallel-orchestrate must contain
    register_agent AND reg["briefing"].
    """
    skill_path = SKILLS_DIR / skill_name / "SKILL.md"
    assert skill_path.exists(), f"Expected skill file not found: {skill_path}"
    text = skill_path.read_text(encoding="utf-8")

    assert "register_agent" in text, (
        f"{skill_name}/SKILL.md missing 'register_agent'. "
        "The doc-fix for this skill has not landed or was reverted."
    )
    assert 'reg["briefing"]' in text, (
        f"{skill_name}/SKILL.md missing 'reg[\"briefing\"]' prepend pattern. "
        "The doc-fix for this skill has not landed or was reverted."
    )


# ---------------------------------------------------------------------------
# Test 4 -- hooks/agent-dispatch.py contains the briefing marker
# ---------------------------------------------------------------------------


def test_agent_dispatch_contains_briefing_marker() -> None:
    """hooks/agent-dispatch.py must contain "## Your Agent Identity".

    Its absence means briefing injection is broken.
    """
    dispatch_path = HOOKS_DIR / "agent-dispatch.py"
    assert dispatch_path.exists(), f"hooks/agent-dispatch.py not found at {dispatch_path}"
    text = dispatch_path.read_text(encoding="utf-8")
    assert "## Your Agent Identity" in text, (
        "hooks/agent-dispatch.py does not contain '## Your Agent Identity'.\n"
        "The doc-fix that moves the briefing header into the dispatch hook "
        "has not landed or was reverted."
    )
