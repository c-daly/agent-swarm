#!/usr/bin/env python3
"""
Remember - Save a learning to persistent memory with automatic scope inference.

Usage:
    remember.py <content> [--scope=<scope>]
    
Scopes:
    user/global - Save to ~/.claude/.context/MEMORY.md
    repo        - Save to repo root .context/MEMORY.md
    component   - Save to current directory .context/MEMORY.md
"""

import argparse
import sys
from pathlib import Path
from typing import Optional

# Import from resolver for scope inference
try:
    from resolver import infer_scope, _find_repo_root
except ImportError:
    # Handle case where module is run directly
    sys.path.insert(0, str(Path(__file__).parent))
    from resolver import infer_scope, _find_repo_root


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Save a learning to persistent memory"
    )
    parser.add_argument(
        "content",
        nargs="+",
        help="The content to remember",
    )
    parser.add_argument(
        "--scope",
        choices=["user", "global", "repo", "component"],
        help="Explicit scope (overrides auto-inference)",
    )

    args = parser.parse_args(argv)
    
    # Join content parts into single string (handles both quoted and unquoted)
    args.content = " ".join(args.content)
    
    return args


def save_memory(
    content: str,
    scope: Optional[str],
    working_dir: Path,
    user_dir: Optional[Path] = None,
) -> Path:
    """
    Save content to MEMORY.md at the appropriate scope.

    Args:
        content: The content to save
        scope: Explicit scope ('user', 'global', 'repo', 'component') or None for auto
        working_dir: Current working directory
        user_dir: User's .claude directory (for testing)

    Returns:
        Path where the content was saved
    """
    if user_dir is None:
        user_dir = Path.home() / ".claude"

    # Determine target directory based on scope
    if scope in ("user", "global"):
        target_dir = user_dir
    elif scope == "component":
        target_dir = working_dir
    elif scope == "repo":
        repo_root = _find_repo_root(working_dir)
        target_dir = repo_root if repo_root else working_dir
    else:
        # Auto-infer scope using resolver
        inferred_scope, target_dir = infer_scope(content, working_dir)
        # Map 'user' scope to user_dir for test isolation
        if inferred_scope == "user":
            target_dir = user_dir

    # Ensure .context directory exists
    context_dir = target_dir / ".context"
    context_dir.mkdir(parents=True, exist_ok=True)

    target_file = context_dir / "MEMORY.md"

    # Format content with timestamp
    from datetime import datetime
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    formatted_content = f"- [{timestamp}] {content}"

    # Append content (with separator if file exists)
    if target_file.exists():
        existing = target_file.read_text()
        if not existing.endswith("\n"):
            existing += "\n"
        new_content = existing + formatted_content + "\n"
    else:
        # Create file with header
        new_content = "# Memory\n\nLearnings and patterns for this scope.\n\n" + formatted_content + "\n"

    target_file.write_text(new_content)

    return target_file


def _scope_name(path: Path, user_dir: Path, working_dir: Path) -> str:
    """Get human-readable scope name for a path."""
    if path.parent.parent == user_dir:
        return "user"
    
    repo_root = _find_repo_root(working_dir)
    if repo_root and path.parent.parent == repo_root:
        return "repo"
    
    return "component"


def main(
    argv: list[str],
    working_dir: Optional[Path] = None,
    user_dir: Optional[Path] = None,
) -> int:
    """
    Main entry point for remember CLI.

    Args:
        argv: Command line arguments
        working_dir: Working directory (for testing)
        user_dir: User's .claude directory (for testing)

    Returns:
        Exit code (0 for success)
    """
    if working_dir is None:
        working_dir = Path.cwd()
    if user_dir is None:
        user_dir = Path.home() / ".claude"

    args = parse_args(argv)

    result_path = save_memory(
        content=args.content,
        scope=args.scope,
        working_dir=working_dir,
        user_dir=user_dir,
    )

    scope_label = _scope_name(result_path, user_dir, working_dir)
    print(f"Saved to {scope_label} scope: {result_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
