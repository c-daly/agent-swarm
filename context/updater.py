#!/usr/bin/env python3
"""
Context Update Helper

Provides safe interface for agents to propose context updates.
Separates stable (manual-only) from dynamic (agent-updateable) sections.
"""

import fcntl
import json
from pathlib import Path
from datetime import datetime
from typing import Literal, Optional

UpdateType = Literal["append", "replace", "delete"]

# Sections that agents can update
DYNAMIC_SECTIONS = {
    "current_state",
    "recent_decisions",
    "active_work",
    "blockers",
    "patterns",  # Via memory distillation
    "pitfalls",  # Via memory distillation
}

# Sections reserved for manual editing
STABLE_SECTIONS = {
    "purpose",
    "boundaries",
    "key_decisions",
    "conventions",
}


def find_context_file(scope_path: Path) -> Path:
    """Find the CONTEXT.md file for this scope."""
    candidates = [
        scope_path / ".context" / "CONTEXT.md",
        scope_path / ".claude" / "CONTEXT.md",
        scope_path / "CONTEXT.md",
    ]

    for candidate in candidates:
        if candidate.exists():
            return candidate

    # Default: create in .context
    return scope_path / ".context" / "CONTEXT.md"


def find_proposals_file(scope_path: Path) -> Path:
    """Find or create the proposals file for this scope."""
    context_file = find_context_file(scope_path)
    return context_file.parent / "CONTEXT.proposals.json"


def propose_context_update(
    scope_path: Path,
    section: str,
    content: str,
    update_type: UpdateType = "append",
    agent_id: str = "unknown"
) -> dict:
    """
    Propose a context update for review.

    Args:
        scope_path: Directory containing CONTEXT.md
        section: Section name (lowercase, underscored)
        content: Content to add/replace
        update_type: How to apply update
        agent_id: ID of proposing agent

    Returns:
        dict with success status and message
    """
    section_lower = section.lower().replace(" ", "_")

    # Check if section is updateable
    if section_lower in STABLE_SECTIONS:
        return {
            "success": False,
            "error": f"Section '{section}' is stable and cannot be updated by agents. "
                     f"Stable sections: {', '.join(sorted(STABLE_SECTIONS))}"
        }

    # Create proposal
    proposal = {
        "id": datetime.now().strftime("%Y%m%d-%H%M%S"),
        "timestamp": datetime.now().isoformat(),
        "agent_id": agent_id,
        "section": section_lower,
        "update_type": update_type,
        "content": content
    }

    # Find proposals file
    proposals_file = find_proposals_file(scope_path)

    # Load existing proposals and save with file locking
    proposals_file.parent.mkdir(parents=True, exist_ok=True)

    with open(proposals_file, 'a+') as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        f.seek(0)
        content = f.read()
        try:
            proposals = json.loads(content) if content else []
        except json.JSONDecodeError:
            proposals = []

        proposals.append(proposal)

        f.seek(0)
        f.truncate()
        f.write(json.dumps(proposals, indent=2))
        fcntl.flock(f.fileno(), fcntl.LOCK_UN)

    return {
        "success": True,
        "proposal_id": proposal["id"],
        "message": f"Proposed {update_type} to section '{section_lower}'. "
                   f"Review with: python3 scripts/context-update.py list"
    }


def list_proposals(scope_path: Optional[Path] = None) -> list[dict]:
    """List all pending proposals for a scope."""
    if scope_path is None:
        scope_path = Path.cwd()

    proposals_file = find_proposals_file(scope_path)

    if not proposals_file.exists():
        return []

    try:
        return json.loads(proposals_file.read_text())
    except json.JSONDecodeError:
        return []


def apply_proposal(proposal_id: str, scope_path: Optional[Path] = None) -> dict:
    """Apply a specific proposal to CONTEXT.md."""
    if scope_path is None:
        scope_path = Path.cwd()

    proposals_file = find_proposals_file(scope_path)
    context_file = find_context_file(scope_path)

    if not proposals_file.exists():
        return {"success": False, "error": "No proposals file found"}

    proposals = json.loads(proposals_file.read_text())

    # Find proposal
    proposal = None
    for p in proposals:
        if p["id"] == proposal_id:
            proposal = p
            break

    if not proposal:
        return {"success": False, "error": f"Proposal {proposal_id} not found"}

    # Read current context
    if context_file.exists():
        content = context_file.read_text()
    else:
        content = f"# Context: {scope_path.name}\n\n"

    # Apply update
    section_header = f"## {proposal['section'].replace('_', ' ').title()}"

    if proposal["update_type"] == "replace":
        # Replace entire section
        import re
        pattern = rf"({re.escape(section_header)}\n)(.*?)(?=\n## |\Z)"
        if re.search(pattern, content, re.DOTALL):
            content = re.sub(pattern, rf"\1{proposal['content']}\n\n", content, flags=re.DOTALL)
        else:
            content += f"\n\n{section_header}\n{proposal['content']}\n"

    elif proposal["update_type"] == "append":
        if section_header in content:
            # Find end of section and append
            lines = content.split("\n")
            new_lines = []
            in_section = False
            appended = False

            for line in lines:
                new_lines.append(line)
                if line.strip() == section_header.strip():
                    in_section = True
                elif in_section and line.strip().startswith("## "):
                    # Next section, insert before it
                    new_lines.insert(-1, "")
                    new_lines.insert(-1, proposal["content"])
                    appended = True
                    in_section = False

            if in_section and not appended:
                # Section was at end, append at end
                new_lines.append("")
                new_lines.append(proposal["content"])

            content = "\n".join(new_lines)
        else:
            # Section doesn't exist - create it
            content += f"\n\n{section_header}\n{proposal['content']}\n"

    elif proposal["update_type"] == "delete":
        # Remove content from section (simplified: just note it was deleted)
        pass

    # Write updated context
    context_file.parent.mkdir(parents=True, exist_ok=True)
    context_file.write_text(content)

    # Remove applied proposal
    proposals = [p for p in proposals if p["id"] != proposal_id]
    proposals_file.write_text(json.dumps(proposals, indent=2))

    return {
        "success": True,
        "message": f"Applied proposal {proposal_id} to {context_file}"
    }


def reject_proposal(proposal_id: str, scope_path: Optional[Path] = None) -> dict:
    """Reject (remove) a proposal without applying it."""
    if scope_path is None:
        scope_path = Path.cwd()

    proposals_file = find_proposals_file(scope_path)

    if not proposals_file.exists():
        return {"success": False, "error": "No proposals file found"}

    proposals = json.loads(proposals_file.read_text())
    original_count = len(proposals)

    proposals = [p for p in proposals if p["id"] != proposal_id]

    if len(proposals) == original_count:
        return {"success": False, "error": f"Proposal {proposal_id} not found"}

    proposals_file.write_text(json.dumps(proposals, indent=2))

    return {
        "success": True,
        "message": f"Rejected proposal {proposal_id}"
    }


# CLI interface
if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: updater.py <command> [args]")
        print("Commands:")
        print("  propose <scope> <section> <content>  - Propose an update")
        print("  list [scope]                          - List pending proposals")
        print("  apply <id> [scope]                    - Apply a proposal")
        print("  reject <id> [scope]                   - Reject a proposal")
        print()
        print("Dynamic sections (agent-updateable):")
        print(f"  {', '.join(sorted(DYNAMIC_SECTIONS))}")
        print()
        print("Stable sections (manual-only):")
        print(f"  {', '.join(sorted(STABLE_SECTIONS))}")
        sys.exit(1)

    command = sys.argv[1]

    if command == "propose":
        if len(sys.argv) < 5:
            print("Usage: updater.py propose <scope> <section> <content>")
            sys.exit(1)

        scope = Path(sys.argv[2])
        section = sys.argv[3]
        content = sys.argv[4]

        result = propose_context_update(scope, section, content)
        if result["success"]:
            print(f"Proposed: {result['message']}")
            sys.exit(0)
        else:
            print(f"Error: {result['error']}")
            sys.exit(1)

    elif command == "list":
        scope = Path(sys.argv[2]) if len(sys.argv) > 2 else None
        proposals = list_proposals(scope)

        if not proposals:
            print("No pending proposals")
        else:
            print(f"Pending proposals ({len(proposals)}):\n")
            for p in proposals:
                print(f"ID: {p['id']}")
                print(f"  Section: {p['section']}")
                print(f"  Type: {p['update_type']}")
                print(f"  Agent: {p['agent_id']}")
                print(f"  Content: {p['content'][:80]}...")
                print()

    elif command == "apply":
        if len(sys.argv) < 3:
            print("Usage: updater.py apply <id> [scope]")
            sys.exit(1)

        proposal_id = sys.argv[2]
        scope = Path(sys.argv[3]) if len(sys.argv) > 3 else None

        result = apply_proposal(proposal_id, scope)
        if result["success"]:
            print(result["message"])
            sys.exit(0)
        else:
            print(f"Error: {result['error']}")
            sys.exit(1)

    elif command == "reject":
        if len(sys.argv) < 3:
            print("Usage: updater.py reject <id> [scope]")
            sys.exit(1)

        proposal_id = sys.argv[2]
        scope = Path(sys.argv[3]) if len(sys.argv) > 3 else None

        result = reject_proposal(proposal_id, scope)
        if result["success"]:
            print(result["message"])
            sys.exit(0)
        else:
            print(f"Error: {result['error']}")
            sys.exit(1)

    else:
        print(f"Unknown command: {command}")
        sys.exit(1)
