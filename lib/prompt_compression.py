"""Prompt compression utilities for reducing agent briefing size.

Provides compressed versions of protocols, deduplication of enforcement rules,
and context summarization for agents.
"""

from pathlib import Path
from typing import Optional
import sys

# Add context module to path
sys.path.insert(0, str(Path(__file__).parent.parent))


# Agent-type to key rules mapping (compressed from full protocol)
COMPRESSED_PROTOCOLS = {
    "implementer": """## Implementer Rules
- Write code to make tests pass
- Follow existing conventions
- No over-engineering
- Commit frequently
""",
    "explorer": """## Explorer Rules
- Search and understand codebase
- Report findings clearly
- No editing allowed
""",
    "reviewer": """## Reviewer Rules
- Check conventions and patterns
- Note pitfalls
- Suggest improvements
""",
    "architect": """## Architect Rules
- Design structure and interfaces
- Consider dependencies
- Document decisions
""",
    "debugger": """## Debugger Rules
- Trace execution paths
- Identify root causes
- Suggest minimal fixes
""",
    "git-agent": """## Git Agent Rules
- Follow commit conventions
- No force pushes
- Clear commit messages
""",
    "researcher": """## Researcher Rules
- Gather information
- Summarize findings
- No code changes
""",
}

# Default rules for unknown agent types
DEFAULT_PROTOCOL = """## Agent Rules
- Follow instructions precisely
- Use appropriate tools
- Report progress clearly
"""


def get_compressed_protocol(agent_type: str) -> str:
    """Get compressed protocol rules for an agent type.

    Args:
        agent_type: Type of agent (implementer, explorer, etc.)

    Returns:
        Compressed protocol string (~100-200 tokens vs ~500+ for full).
    """
    return COMPRESSED_PROTOCOLS.get(agent_type, DEFAULT_PROTOCOL)


def generate_agent_briefing(
    agent_type: str,
    phase: Optional[str] = None,
    max_tokens: int = 1000,
    include_context: bool = True,
) -> str:
    """Generate a compressed agent briefing.

    Args:
        agent_type: Type of agent being briefed.
        phase: Current workflow phase (optional).
        max_tokens: Maximum token budget for briefing.
        include_context: Whether to include context reference.

    Returns:
        Compressed briefing string within token budget.
    """
    parts = []

    # Add compressed protocol
    protocol = get_compressed_protocol(agent_type)
    parts.append(protocol)

    # Add phase-specific guidance if provided
    if phase:
        phase_guidance = _get_phase_guidance(phase)
        parts.append(phase_guidance)

    # Add enforcement reference (not full rules)
    if include_context:
        parts.append("## Enforcement\nSee CORE_PROTOCOL.md for full rules.")

    # Combine and truncate if needed
    briefing = "\n\n".join(parts)

    # Estimate tokens (~4 chars per token) and truncate if over budget
    estimated_tokens = len(briefing) / 4
    if estimated_tokens > max_tokens:
        char_budget = max_tokens * 4
        briefing = briefing[:int(char_budget)] + "\n[Truncated]"

    return briefing


def _get_phase_guidance(phase: str) -> str:
    """Get phase-specific guidance."""
    guidance = {
        "intake": "## Phase: Intake\n- Gather requirements\n- No editing allowed",
        "design": "## Phase: Design\n- Write specifications\n- Create task breakdown",
        "test_writing": "## Phase: Test Writing\n- Write failing tests first\n- Define expected behavior",
        "implement": "## Phase: Implement\n- Make tests pass\n- Follow conventions",
        "test": "## Phase: Test\n- Run verification\n- No editing allowed",
        "review": "## Phase: Review\n- Address feedback\n- Fix issues found",
    }
    return guidance.get(phase, f"## Phase: {phase}")


def get_context_for_agent(
    agent_type: str,
    working_dir: Path,
    summary: bool = True,
    phase: Optional[str] = None,
    max_tokens: int = 500,
) -> str:
    """Get context tailored and optionally summarized for an agent.

    Args:
        agent_type: Type of agent.
        working_dir: Working directory for context resolution.
        summary: If True, return summarized version.
        phase: Current workflow phase.
        max_tokens: Token budget for context.

    Returns:
        Context string, summarized if requested.
    """
    try:
        from context.resolver import get_agent_context
    except ImportError:
        return f"[Context unavailable for {agent_type}]"

    full_context = get_agent_context(agent_type, working_dir, phase)

    if not summary:
        return full_context

    # Summarize by keeping only first few lines of each section
    summarized_lines = []
    current_section = None
    section_line_count = 0
    max_lines_per_section = 3

    for line in full_context.split("\n"):
        if line.startswith("## "):
            # New section - reset counter
            current_section = line
            section_line_count = 0
            summarized_lines.append(line)
        elif current_section and section_line_count < max_lines_per_section:
            summarized_lines.append(line)
            if line.strip():  # Only count non-empty lines
                section_line_count += 1

    summarized = "\n".join(summarized_lines)

    # Enforce token budget
    estimated_tokens = len(summarized) / 4
    if estimated_tokens > max_tokens:
        char_budget = max_tokens * 4
        summarized = summarized[:int(char_budget)] + "\n[Context truncated]"

    return summarized


def estimate_tokens(text: str) -> int:
    """Estimate token count for text.

    Uses rough 4-chars-per-token approximation.
    """
    return len(text) // 4
