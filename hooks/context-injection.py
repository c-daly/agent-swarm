#!/usr/bin/env python3
"""
Context Injection Hook

Injects hierarchical context into agent briefings based on the
working directory and agent type. Also logs episodes on task completion.

Usage:
  - Called during agent startup to inject context
  - Called on agent completion to log episode
"""

import sys
import os
import json
from pathlib import Path
from datetime import datetime

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from context.resolver import resolve_context, get_agent_context
from context.memory import log_episode, trigger_distillation


def inject_context(agent_type: str, working_dir: str, phase: str = None) -> dict:
    """
    Generate context injection for an agent.

    Args:
        agent_type: Type of agent being spawned
        working_dir: Directory where agent will work
        phase: Current workflow phase

    Returns:
        Dict with context to inject into agent prompt
    """
    work_path = Path(working_dir).resolve()

    # Get agent-specific filtered context
    context_md = get_agent_context(agent_type, work_path, phase)

    # Also get full context for reference
    full_context = resolve_context(work_path)

    return {
        'context_markdown': context_md,
        'context_layers': [
            {
                'level': layer.level,
                'path': str(layer.path),
            }
            for layer in full_context.layers
        ],
        'agent_type': agent_type,
        'phase': phase,
        'working_dir': working_dir,
    }


def format_context_block(context_data: dict) -> str:
    """Format context data as a markdown block for injection."""
    lines = [
        "<!-- HIERARCHICAL CONTEXT -->",
        "<context>",
    ]

    if context_data.get('context_markdown'):
        lines.append(context_data['context_markdown'])
    else:
        lines.append("*No context files found in hierarchy*")

    # Add layer info as comment
    if context_data.get('context_layers'):
        lines.append("")
        lines.append("<!-- Context loaded from:")
        for layer in context_data['context_layers']:
            lines.append(f"  - [{layer['level']}] {layer['path']}")
        lines.append("-->")

    lines.append("</context>")

    return '\n'.join(lines)


def on_agent_start(agent_type: str, working_dir: str, phase: str = None) -> str:
    """
    Hook called when an agent starts.

    Returns markdown context block to inject into agent prompt.
    """
    context_data = inject_context(agent_type, working_dir, phase)
    return format_context_block(context_data)


def on_agent_complete(
    agent_type: str,
    working_dir: str,
    task: str,
    outcome: str,
    learnings: list[str] = None,
    phase: str = None,
    duration_minutes: int = 0,
):
    """
    Hook called when an agent completes.

    Logs the episode for later distillation.
    """
    work_path = Path(working_dir).resolve()

    episode = log_episode(
        scope_path=work_path,
        task=task,
        outcome=outcome,
        learnings=learnings or [],
        agent_type=agent_type,
        phase=phase,
        duration_minutes=duration_minutes,
    )

    return episode.id


def check_distillation_needed(working_dir: str, max_episodes: int = 10) -> bool:
    """Check if distillation should be triggered."""
    from context.memory import EpisodeStore

    work_path = Path(working_dir).resolve()
    store = EpisodeStore(work_path)
    episodes = store.get_episodes()

    return len(episodes) >= max_episodes


def run_distillation(working_dir: str) -> dict:
    """Run distillation and return summary."""
    work_path = Path(working_dir).resolve()
    memory = trigger_distillation(work_path)

    return {
        'patterns_count': len(memory.patterns),
        'categories': {
            cat: len(memory.get_by_category(cat))
            for cat in ['pattern', 'pitfall', 'preference', 'approach']
        },
        'last_distilled': memory.last_distilled,
    }


# CLI interface for testing
if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: context-injection.py <command> [args]")
        print("Commands:")
        print("  inject <agent_type> [dir] [phase]  - Show context injection")
        print("  complete <agent> <task> <outcome>  - Log completion")
        print("  check-distill [dir]                - Check if distillation needed")
        print("  distill [dir]                      - Run distillation")
        sys.exit(1)

    command = sys.argv[1]

    if command == 'inject':
        agent_type = sys.argv[2] if len(sys.argv) > 2 else 'explorer'
        working_dir = sys.argv[3] if len(sys.argv) > 3 else '.'
        phase = sys.argv[4] if len(sys.argv) > 4 else None

        context_block = on_agent_start(agent_type, working_dir, phase)
        print(context_block)

    elif command == 'complete':
        if len(sys.argv) < 5:
            print("Usage: context-injection.py complete <agent> <task> <outcome>")
            sys.exit(1)

        agent_type = sys.argv[2]
        task = sys.argv[3]
        outcome = sys.argv[4]

        episode_id = on_agent_complete(
            agent_type=agent_type,
            working_dir='.',
            task=task,
            outcome=outcome,
        )
        print(f"Logged episode: {episode_id}")

    elif command == 'check-distill':
        working_dir = sys.argv[2] if len(sys.argv) > 2 else '.'
        needed = check_distillation_needed(working_dir)
        print(f"Distillation needed: {needed}")

    elif command == 'distill':
        working_dir = sys.argv[2] if len(sys.argv) > 2 else '.'
        result = run_distillation(working_dir)
        print(json.dumps(result, indent=2))

    else:
        print(f"Unknown command: {command}")
        sys.exit(1)
