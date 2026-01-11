#!/usr/bin/env python3
"""
Decomposer: Parse spec files and generate implementation tasks.

Takes a markdown spec file and breaks it into independent tasks
suitable for the iterate workflow queue.
"""

import argparse
import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import IntEnum
from pathlib import Path


class TaskPriority(IntEnum):
    """Task priority levels (lower = higher priority)."""
    TEST_FAILURE = 0
    GREPTILE_CRITICAL = 1
    GREPTILE_WARNING = 2
    ORIGINAL = 3
    COVERAGE_GAP = 4


# Section types and their ordering (lower = implement first)
SECTION_ORDER = {
    "enum": 0,
    "constant": 1,
    "dataclass": 2,
    "class": 3,
    "function": 4,
    "method": 5,
    "cli": 6,
    "other": 10,
}


@dataclass
class SpecSection:
    """A parsed section from a spec file."""
    title: str
    content: str
    type: str
    spec_file: str = ""
    line_number: int = 0
    code_block: str = ""


def detect_section_type(title: str, content: str, code_block: str = "") -> str:
    """Detect the type of a spec section."""
    title_lower = title.lower()
    code_lower = code_block.lower()

    # Check title first
    if "enum" in title_lower:
        return "enum"
    if "constant" in title_lower:
        return "constant"
    if "dataclass" in title_lower or "@dataclass" in code_lower:
        return "dataclass"
    if "class" in title_lower and "dataclass" not in title_lower:
        return "class"

    # Check for CLI commands
    if any(x in title_lower for x in ["cli", "command", "queue ", "pr "]):
        return "cli"

    # Check code block for hints
    if code_lower:
        if "@dataclass" in code_lower:
            return "dataclass"
        if "class " in code_lower and "(str, enum)" in code_lower:
            return "enum"
        if "class " in code_lower:
            return "class"
        if "def " in code_lower:
            return "function"

    # Check for method signatures in title (e.g., "add_task(task: Task)")
    if re.search(r'\w+\s*\([^)]*\)', title):
        return "method"

    return "other"


def parse_spec_sections(spec_content: str, group_enums: bool = False) -> list[dict]:
    """
    Parse a spec file into sections representing implementation units.

    Args:
        spec_content: The markdown content of the spec
        group_enums: If True, group related enums/constants together

    Returns:
        List of section dictionaries with title, content, type
    """
    sections = []
    lines = spec_content.split('\n')

    current_section = None
    current_content = []
    current_code_block = []
    in_code_block = False
    section_start_line = 0

    for i, line in enumerate(lines):
        # Track code blocks
        if line.strip().startswith('```'):
            if in_code_block:
                in_code_block = False
                current_code_block.append(line)
            else:
                in_code_block = True
                current_code_block = [line]
            current_content.append(line)
            continue

        if in_code_block:
            current_content.append(line)
            current_code_block.append(line)
            continue

        # Check for headers (implementation units)
        header_match = re.match(r'^(#{2,4})\s+(.+)$', line)

        if header_match:
            # Save previous section if exists
            if current_section:
                code_block_text = '\n'.join(current_code_block) if current_code_block else ""
                section_type = detect_section_type(
                    current_section,
                    '\n'.join(current_content),
                    code_block_text
                )

                # Skip overview/intro sections
                if section_type != "other" or _is_implementation_section(current_section, current_content):
                    sections.append({
                        "title": current_section,
                        "content": '\n'.join(current_content).strip(),
                        "type": section_type,
                        "line_number": section_start_line,
                        "code_block": code_block_text,
                    })

            # Start new section
            current_section = header_match.group(2).strip()
            current_content = []
            current_code_block = []
            section_start_line = i + 1
        else:
            current_content.append(line)

    # Don't forget the last section
    if current_section:
        code_block_text = '\n'.join(current_code_block) if current_code_block else ""
        section_type = detect_section_type(
            current_section,
            '\n'.join(current_content),
            code_block_text
        )
        if section_type != "other" or _is_implementation_section(current_section, current_content):
            sections.append({
                "title": current_section,
                "content": '\n'.join(current_content).strip(),
                "type": section_type,
                "line_number": section_start_line,
                "code_block": code_block_text,
            })

    # Optionally group enums/constants
    if group_enums:
        sections = _group_related_sections(sections)

    return sections


def _is_implementation_section(title: str, content: list[str]) -> bool:
    """Check if a section represents something to implement."""
    title_lower = title.lower()
    content_str = '\n'.join(content).lower()

    # Skip meta sections
    skip_keywords = ["overview", "summary", "introduction", "out of scope",
                     "verification", "test cases", "integration notes"]
    if any(kw in title_lower for kw in skip_keywords):
        return False

    # Include if has code block or method signature
    if '```' in content_str:
        return True
    if re.search(r'\w+\s*\([^)]*\)\s*->', content_str):
        return True

    return False


def _group_related_sections(sections: list[dict]) -> list[dict]:
    """Group related enum/constant sections together."""
    grouped = []
    enum_group = []

    for section in sections:
        if section["type"] in ("enum", "constant"):
            enum_group.append(section)
        else:
            # Flush enum group if we hit a non-enum
            if enum_group:
                if len(enum_group) == 1:
                    grouped.append(enum_group[0])
                else:
                    # Combine into single section
                    combined = {
                        "title": "Enums and Constants",
                        "content": '\n\n'.join(s["content"] for s in enum_group),
                        "type": "enum",
                        "line_number": enum_group[0]["line_number"],
                        "code_block": '\n\n'.join(s.get("code_block", "") for s in enum_group),
                    }
                    grouped.append(combined)
                enum_group = []
            grouped.append(section)

    # Don't forget trailing enums
    if enum_group:
        if len(enum_group) == 1:
            grouped.append(enum_group[0])
        else:
            combined = {
                "title": "Enums and Constants",
                "content": '\n\n'.join(s["content"] for s in enum_group),
                "type": "enum",
                "line_number": enum_group[0]["line_number"],
                "code_block": '\n\n'.join(s.get("code_block", "") for s in enum_group),
            }
            grouped.append(combined)

    return grouped


def generate_task(section: dict, pr_id: str) -> dict:
    """
    Generate a task from a parsed spec section.

    Args:
        section: Parsed section with title, content, type
        pr_id: PR ID to assign the task to

    Returns:
        Task dictionary matching TaskQueue schema
    """
    task_id = f"task-{uuid.uuid4().hex[:8]}"

    # Clean up title for description
    description = section["title"]
    if not description.lower().startswith(("implement", "add", "create")):
        # Add action verb based on type
        type_actions = {
            "dataclass": "Implement",
            "class": "Implement",
            "enum": "Implement",
            "constant": "Define",
            "function": "Implement",
            "method": "Implement",
            "cli": "Add CLI command:",
        }
        action = type_actions.get(section["type"], "Implement")
        description = f"{action} {description}"

    return {
        "id": task_id,
        "description": description,
        "status": "pending",
        "priority": TaskPriority.ORIGINAL,
        "source": "original",
        "pr_id": pr_id,
        "assigned_agent": None,
        "phase": "test_writing",
        "iteration": 0,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "metadata": {
            "spec_file": section.get("spec_file", ""),
            "line_number": section.get("line_number", 0),
            "section_type": section["type"],
            "original_content": section["content"][:500],  # Truncate for storage
        }
    }


def decompose_spec(spec_path: str, pr_id: str, group_enums: bool = False) -> list[dict]:
    """
    Decompose a spec file into implementation tasks.

    Args:
        spec_path: Path to the spec markdown file
        pr_id: PR ID to assign tasks to
        group_enums: Whether to group enum/constant sections

    Returns:
        List of tasks ordered by implementation dependency
    """
    spec_file = Path(spec_path)
    if not spec_file.exists():
        return []

    content = spec_file.read_text()
    if not content.strip():
        return []

    # Parse into sections
    sections = parse_spec_sections(content, group_enums=group_enums)

    # Add spec file reference to each section
    for section in sections:
        section["spec_file"] = spec_file.name

    # Sort by dependency order (data structures first)
    sections.sort(key=lambda s: SECTION_ORDER.get(s["type"], 10))

    # Generate tasks
    tasks = [generate_task(section, pr_id) for section in sections]

    return tasks


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Decompose a spec file into implementation tasks"
    )
    parser.add_argument("spec_file", help="Path to the spec markdown file")
    parser.add_argument("--pr", default="default", help="PR ID to assign tasks to")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--output", "-o", help="Write tasks to file instead of stdout")
    parser.add_argument("--group-enums", action="store_true",
                       help="Group related enums/constants into single task")

    args = parser.parse_args()

    tasks = decompose_spec(args.spec_file, args.pr, group_enums=args.group_enums)

    if args.output:
        Path(args.output).write_text(json.dumps(tasks, indent=2))
        print(f"Wrote {len(tasks)} tasks to {args.output}")
    elif args.json:
        print(json.dumps(tasks, indent=2))
    else:
        # Human-readable output
        print(f"Decomposed into {len(tasks)} tasks:\n")
        for i, task in enumerate(tasks, 1):
            print(f"{i}. [{task['metadata']['section_type']}] {task['description']}")
            print(f"   ID: {task['id']}")
            print()


if __name__ == "__main__":
    main()
