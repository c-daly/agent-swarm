#!/usr/bin/env python3
"""
Hierarchical Context Resolver

Walks up the directory tree collecting context files and merges them
with locality-of-reference priority (more specific overrides more general).
"""

import re
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

# Context file search order within each directory
CONTEXT_FILE_PATTERNS = [
    ".context/CONTEXT.md",
    ".claude/CONTEXT.md",
    "CONTEXT.md",
    ".context.md",
]

MEMORY_FILE_PATTERNS = [
    ".context/MEMORY.md",
    ".claude/MEMORY.md",
    "MEMORY.md",
    ".memory.md",
]

# Standard sections in context files
CONTEXT_SECTIONS = [
    "purpose",
    "boundaries",
    "conventions",
    "key_decisions",
    "dependencies",
    "patterns",
    "pitfalls",
    "preferences",
]


@dataclass
class ContextLayer:
    """A single layer of context from one directory level."""

    path: Path
    level: str  # 'user', 'project', 'repo', 'feature', 'component'
    content: str
    sections: dict = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)

    def __post_init__(self):
        self.sections = self._parse_sections()
        self.metadata = self._parse_metadata()

    def _parse_sections(self) -> dict:
        """Parse markdown sections from content."""
        sections = {}
        current_section = None
        current_content = []

        for line in self.content.split("\n"):
            # Match ## Section headers
            header_match = re.match(r"^##\s+(.+)$", line)
            if header_match:
                if current_section:
                    sections[current_section.lower()] = "\n".join(
                        current_content
                    ).strip()
                current_section = header_match.group(1)
                current_content = []
            elif current_section:
                current_content.append(line)

        # Don't forget last section
        if current_section:
            sections[current_section.lower()] = "\n".join(current_content).strip()

        return sections

    def _parse_metadata(self) -> dict:
        """Parse @directives from content."""
        metadata = {
            "inherit": True,
            "override": [],
            "ignore": [],
            "priority": "normal",
        }

        for line in self.content.split("\n"):
            if line.startswith("@inherit:"):
                metadata["inherit"] = line.split(":")[1].strip().lower() == "true"
            elif line.startswith("@override:"):
                metadata["override"].append(line.split(":")[1].strip())
            elif line.startswith("@ignore:"):
                metadata["ignore"].append(line.split(":")[1].strip())
            elif line.startswith("@priority:"):
                metadata["priority"] = line.split(":")[1].strip()

        return metadata


@dataclass
class AggregatedContext:
    """Merged context from all layers."""

    layers: list[ContextLayer]
    merged_sections: dict = field(default_factory=dict)

    def __post_init__(self):
        self.merged_sections = self._merge_all()

    def _merge_all(self) -> dict:
        """Merge all layers with inheritance rules."""
        result = {}

        # Process from most general (first) to most specific (last)
        for layer in self.layers:
            if not layer.metadata.get("inherit", True):
                # This layer doesn't inherit - start fresh
                result = {}

            for section, content in layer.sections.items():
                # Check if this section should be ignored from parent
                if section in layer.metadata.get("ignore", []):
                    continue

                # Check if this section overrides parent completely
                if section in layer.metadata.get("override", []):
                    result[section] = content
                else:
                    # Default: append to existing
                    if section in result:
                        result[section] = f"{result[section]}\n\n{content}"
                    else:
                        result[section] = content

        return result

    def get_section(self, name: str) -> Optional[str]:
        """Get a specific section from merged context."""
        return self.merged_sections.get(name.lower())

    def get_sections(self, names: list[str]) -> dict:
        """Get multiple sections as a dict."""
        return {
            name: self.merged_sections.get(name.lower())
            for name in names
            if name.lower() in self.merged_sections
        }

    def to_markdown(self, max_tokens: int = 4500) -> str:
        """Render merged context as markdown with token budget."""
        parts = []

        for section, content in self.merged_sections.items():
            if content:
                parts.append(f"## {section.title()}\n{content}")

        result = "\n\n".join(parts)

        # Rough token estimate (4 chars per token)
        if len(result) > max_tokens * 4:
            result = (
                result[: max_tokens * 4] + "\n\n[Context truncated due to token limit]"
            )

        return result

    def to_dict(self) -> dict:
        """Export as dictionary for JSON serialization."""
        return {
            "layers": [
                {
                    "path": str(layer.path),
                    "level": layer.level,
                    "sections": layer.sections,
                }
                for layer in self.layers
            ],
            "merged": self.merged_sections,
        }


def find_context_file(directory: Path) -> Optional[Path]:
    """Find the first matching context file in a directory."""
    for pattern in CONTEXT_FILE_PATTERNS:
        candidate = directory / pattern
        if candidate.exists():
            return candidate
    return None


def find_memory_file(directory: Path) -> Optional[Path]:
    """Find the first matching memory file in a directory."""
    for pattern in MEMORY_FILE_PATTERNS:
        candidate = directory / pattern
        if candidate.exists():
            return candidate
    return None


def detect_level(path: Path, working_dir: Path, user_dir: Path) -> str:
    """Detect what level of hierarchy this path represents."""
    if path == user_dir:
        return "user"

    # Check for .git to identify repo root
    if (path / ".git").exists():
        return "repo"

    # Check for project markers
    if (path / ".project").exists() or (path / "PROJECT.md").exists():
        return "project"

    # Relative depth from working dir determines feature vs component
    try:
        rel = working_dir.relative_to(path)
        depth = len(rel.parts)
        if depth <= 2:
            return "feature"
        return "component"
    except ValueError:
        return "unknown"


def resolve_context(
    working_dir: Path, user_dir: Optional[Path] = None
) -> AggregatedContext:
    """
    Walk up from working_dir collecting context files.

    Args:
        working_dir: The directory where work is happening
        user_dir: User's .claude directory (defaults to ~/.claude)

    Returns:
        AggregatedContext with all layers merged
    """
    if user_dir is None:
        user_dir = Path.home() / ".claude"

    layers = []

    # Walk up from working directory
    current = working_dir.resolve()
    filesystem_root = Path(current.anchor)

    while current != filesystem_root:
        context_file = find_context_file(current)
        if context_file:
            content = context_file.read_text()
            level = detect_level(current, working_dir, user_dir)
            layers.append(
                ContextLayer(
                    path=current,
                    level=level,
                    content=content,
                )
            )
        current = current.parent

    # Add user-level context
    user_context_file = find_context_file(user_dir)
    if user_context_file:
        content = user_context_file.read_text()
        layers.append(
            ContextLayer(
                path=user_dir,
                level="user",
                content=content,
            )
        )

    # Reverse so general comes first (user -> project -> repo -> feature)
    layers.reverse()

    return AggregatedContext(layers=layers)


def get_agent_context(
    agent_type: str, working_dir: Path, phase: Optional[str] = None
) -> str:
    """
    Get context tailored for a specific agent type and phase.

    Args:
        agent_type: Type of agent (explorer, implementer, architect, etc.)
        working_dir: Directory where agent is working
        phase: Current workflow phase (optional)

    Returns:
        Markdown string with filtered context
    """
    full_context = resolve_context(working_dir)

    # Agent-specific section priorities
    agent_sections = {
        "explorer": ["boundaries", "conventions", "patterns"],
        "implementer": ["conventions", "patterns", "pitfalls", "dependencies"],
        "architect": ["purpose", "key_decisions", "dependencies", "boundaries"],
        "reviewer": ["conventions", "pitfalls", "patterns"],
        "researcher": ["purpose", "dependencies"],
        "debugger": ["patterns", "pitfalls", "conventions"],
        "git-agent": ["conventions"],
    }

    # Phase-specific section priorities
    phase_sections = {
        "intake": ["purpose", "boundaries"],
        "explore": ["conventions", "boundaries", "patterns"],
        "design": ["key_decisions", "dependencies", "patterns"],
        "implement": ["conventions", "patterns", "pitfalls"],
        "review": ["conventions", "pitfalls"],
        "git": ["conventions"],
    }

    # Combine agent and phase priorities
    sections = set(agent_sections.get(agent_type, CONTEXT_SECTIONS))
    if phase:
        sections.update(phase_sections.get(phase, []))

    filtered = full_context.get_sections(list(sections))

    # Build output
    parts = []
    for section, content in filtered.items():
        if content:
            parts.append(f"## {section.title()}\n{content}")

    return "\n\n".join(parts)


def show_context_tree(working_dir: Path) -> str:
    """Generate a visual tree of context hierarchy."""
    context = resolve_context(working_dir)

    lines = ["Context Hierarchy:", ""]

    for i, layer in enumerate(context.layers):
        indent = "  " * i
        marker = "└── " if i == len(context.layers) - 1 else "├── "
        lines.append(f"{indent}{marker}[{layer.level}] {layer.path}")

        for section in layer.sections.keys():
            section_indent = "  " * (i + 1)
            lines.append(f"{section_indent}    • {section}")

    return "\n".join(lines)


# CLI interface
if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: resolver.py <command> [args]")
        print("Commands:")
        print("  resolve [dir]     - Show resolved context")
        print("  tree [dir]        - Show context hierarchy tree")
        print("  agent <type> [dir] - Show agent-filtered context")
        sys.exit(1)

    command = sys.argv[1]
    work_dir = Path(sys.argv[2] if len(sys.argv) > 2 else ".").resolve()

    if command == "resolve":
        ctx = resolve_context(work_dir)
        print(ctx.to_markdown())

    elif command == "tree":
        print(show_context_tree(work_dir))

    elif command == "agent":
        if len(sys.argv) < 3:
            print("Usage: resolver.py agent <type> [dir]")
            sys.exit(1)
        agent_type = sys.argv[2]
        work_dir = Path(sys.argv[3] if len(sys.argv) > 3 else ".").resolve()
        print(get_agent_context(agent_type, work_dir))

    else:
        print(f"Unknown command: {command}")
        sys.exit(1)
