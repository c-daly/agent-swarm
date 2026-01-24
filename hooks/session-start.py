#!/usr/bin/env python3
"""
Session Start Hook - Auto-search episodic memory & reset counters & inject capabilities

Automatically searches episodic memory at the start of each session
to recover relevant context from past conversations.

Also resets enforcement counters for the new conversation.

Runs inventory.py to inject available MCP servers, skills, and capabilities.
"""

import json
import sys
import subprocess
from pathlib import Path

# Add lib and context to path
plugin_dir = Path(__file__).parent.parent
lib_dir = plugin_dir / "lib"
context_dir = plugin_dir / "context"
sys.path.insert(0, str(lib_dir))
sys.path.insert(0, str(context_dir))

try:
    from hook_logging import log_error, log_warning, log_info, log_debug, ConfigError, StateError
except ImportError:
    # Fallback: define minimal logging functions
    def log_error(msg, **kw):
        pass
    def log_warning(msg, **kw):
        pass
    def log_info(msg, **kw):
        pass
    def log_debug(msg, **kw):
        pass
    class ConfigError(Exception):
        pass
    class StateError(Exception):
        pass

try:
    from workflow_client import workflow_get_state, workflow_set_state, agent_set_state
except ImportError:
    # Fallback if workflow_client not available
    def workflow_get_state(workflow_id: str) -> dict | None:
        return None
    def workflow_set_state(workflow_id: str, state: dict) -> dict | None:
        return None
    def agent_set_state(agent_id: str, state: dict) -> dict | None:
        return None

try:
    from resolver import resolve_context
except ImportError:
    resolve_context = None


def load_iterate_state() -> dict:
    """Load iterate workflow state from state server."""
    state = workflow_get_state("iterate")
    return state if state else {}


def get_session_context(working_dir: Path, max_chars: int = 2000) -> str:
    """Get hierarchical context for session start.

    Args:
        working_dir: Current working directory
        max_chars: Maximum characters for context output

    Returns:
        Formatted context string or empty string on failure
    """
    if resolve_context is None:
        return ""

    try:
        ctx = resolve_context(working_dir)
        if not ctx.layers:
            return ""

        # Get priority sections for session context
        priority_sections = ["boundaries", "conventions", "patterns", "pitfalls"]
        sections = ctx.get_sections(priority_sections)

        # Format as compact output
        parts = []
        for name in priority_sections:
            content = sections.get(name)
            if content:
                # Truncate long sections
                truncated = content[:400] + "..." if len(content) > 400 else content
                parts.append(f"**{name.title()}**: {truncated}")

        result = "\n\n".join(parts)
        return result[:max_chars] if len(result) > max_chars else result

    except Exception as e:
        log_debug(f"Context resolution failed: {e}")
        return ""


def reset_enforcement_counters(agent_id: str | None = None):
    """Reset enforcement counters but preserve workflow state for new conversation.

    Args:
        agent_id: If provided, this is a subagent - inherit phase from orchestrator.
    """
    # Use absolute path to match pre-compacting.py
    state_dir = Path.home() / ".claude/plugins/agent-swarm/.state"
    # DISABLED: Session state file no longer used
    # state_file = state_dir / "session.json"
    compaction_state_file = state_dir / "compaction_state.json"

    try:
        # Check for compaction state (preserved across context compaction)
        compaction_flags = {}
        if compaction_state_file.exists():
            try:
                compaction_data = json.loads(compaction_state_file.read_text())
                compaction_flags = compaction_data.get("flags", {})
                # Delete after reading - one-time use
                compaction_state_file.unlink()
            except (json.JSONDecodeError, IOError) as e:
                log_warning(f"Caught exception: {e}")

        # Initialize fresh session state for counters
        # NOTE: blocked_at and mcp_counts are intentionally NOT included
        # This clears any blocking state from previous sessions
        state = {
            "last_phase": None,
            "last_tool_time": None,
            "signature_change_reminders": [],
            "files_read": [],
            "read_count": 0,
            "files_edited_this_session": [],
            "phase": None,  # Will be set below if subagent
            "search_count": 0,
            "edits_this_response": 0,
            "memory_search_suggested": 1,
            "mcp_counts": {},  # Reset MCP tool counts
            "classification_given": False,  # Reset classification state
            "classification_type": None,
            "workflow_invoked": False,  # Reset workflow state
        }
        # NOTE: blocked_at is NOT set, which clears it

        # Restore flags preserved from compaction
        state.update(compaction_flags)

        # If subagent, inherit phase from orchestrator and set per-agent state
        if agent_id:
            iterate_state = load_iterate_state()
            phase = iterate_state.get("phase")
            if phase:
                state["phase"] = phase
            # Store state keyed by agent_id for subagent-specific queries
            agent_set_state(agent_id, state)

        # Write session state to state server (global session for main agent)
        workflow_set_state("session", state)

        return True
    except Exception as e:
        log_warning(f"Caught Exception: {e}")  # Fail silently, not critical

    return False

def run_inventory():
    """Run inventory.py to discover available capabilities."""
    try:
        inventory_path = Path(__file__).parent.parent / "scripts" / "inventory.py"
        if not inventory_path.exists():
            return None

        result = subprocess.run(
            ["python3", str(inventory_path), "all"],
            capture_output=True,
            text=True,
            timeout=10
        )

        if result.returncode == 0:
            return result.stdout
        return None

    except Exception:
        return None

def list_serena_memories():
    """List available Serena memories for the current project."""
    try:
        memories_dir = Path.home() / ".claude/plugins/agent-swarm/.serena/memories"
        if not memories_dir.exists():
            return []
        return [f.stem for f in memories_dir.glob("*.md")]
    except Exception:
        return []


def find_relevant_memories(query: str, memories: list[str], max_count: int = 3) -> list[str]:
    """Find memories that match query keywords.
    
    Args:
        query: Search query string
        memories: List of memory filenames (without extension)
        max_count: Maximum number of memories to return
        
    Returns:
        List of matching memory names, sorted by relevance
    """
    if not query or not memories:
        return []
    
    # Split query into keywords, normalize
    keywords = [k.lower() for k in query.split() if len(k) > 2]
    if not keywords:
        return []
    
    # Score each memory by keyword matches
    scored = []
    for memory in memories:
        memory_lower = memory.lower()
        score = sum(1 for kw in keywords if kw in memory_lower)
        if score > 0:
            scored.append((memory, score))
    
    # Sort by score descending, take top N
    scored.sort(key=lambda x: x[1], reverse=True)
    return [m[0] for m in scored[:max_count]]


def read_memory_snippets(memory_names: list[str], max_chars_per_memory: int = 500) -> str:
    """Read content snippets from memory files.
    
    Args:
        memory_names: List of memory filenames (without extension)
        max_chars_per_memory: Maximum characters to read per memory
        
    Returns:
        Formatted string with memory snippets
    """
    if not memory_names:
        return ""
    
    memories_dir = Path.home() / ".claude/plugins/agent-swarm/.serena/memories"
    snippets = []
    
    for name in memory_names:
        file_path = memories_dir / f"{name}.md"
        try:
            if not file_path.exists():
                continue
            content = file_path.read_text()[:max_chars_per_memory]
            # Add ellipsis if truncated
            if len(file_path.read_text()) > max_chars_per_memory:
                content += "..."
            snippets.append(f"**{name}**\n> {content.replace(chr(10), chr(10) + '> ')}")
        except Exception:
            continue
    
    return "\n\n".join(snippets)


def search_episodic_memory(query_terms: str, limit: int = 3) -> list:
    """Search episodic memory using the CLI for past conversation snippets.

    Uses --text mode for speed (no embedding model loading required).

    Args:
        query_terms: Search query
        limit: Max number of results (default 3)

    Returns:
        List of dicts with 'date', 'snippet' keys, or empty list on failure
    """
    try:
        # Path to episodic-memory CLI
        episodic_root = Path.home() / ".claude/plugins/cache/superpowers-marketplace/episodic-memory"

        if not episodic_root.exists():
            return []

        # Find the installed version directory
        version_dirs = [d for d in episodic_root.iterdir() if d.is_dir() and d.name[0].isdigit()]
        if not version_dirs:
            return []

        # Use most recent version
        version_dir = sorted(version_dirs, reverse=True)[0]
        search_cli = version_dir / "cli" / "search-conversations.js"

        if not search_cli.exists():
            return []

        # Run search with text mode (faster, no embedding model)
        result = subprocess.run(
            ["node", str(search_cli), "--text", "--limit", str(limit), query_terms],
            capture_output=True,
            text=True,
            timeout=2,  # Must complete in 2 seconds
            cwd=str(version_dir)
        )

        if result.returncode != 0:
            return []

        # Parse output - format is:
        # Found N relevant conversations:
        #
        # 1. [project, DATE] - X% match
        #    "snippet..."
        #    Lines X-Y in /path/to/file.jsonl
        results = []
        lines = result.stdout.strip().split('\n')
        i = 0
        while i < len(lines):
            line = lines[i]
            # Look for numbered results: "1. [project, DATE]..."
            if line and line[0].isdigit() and '. [' in line:
                # Extract date from "[project, DATE]"
                date_match = line.split(', ')
                date = date_match[-1].split(']')[0] if len(date_match) > 1 else "unknown"

                # Next line is the snippet (indented, in quotes)
                if i + 1 < len(lines):
                    snippet_line = lines[i + 1].strip()
                    if snippet_line.startswith('"'):
                        snippet = snippet_line.strip('"')
                        # Truncate long snippets
                        if len(snippet) > 150:
                            snippet = snippet[:147] + "..."
                        results.append({
                            "date": date,
                            "snippet": snippet
                        })
            i += 1

        return results[:limit]

    except subprocess.TimeoutExpired:
        return []
    except Exception:
        return []


def suggest_memory_options(query_terms):
    """Search episodic memory and suggest other memory systems.

    Actually searches episodic memory and returns results, with fallback
    to manual search instructions if the search fails.
    """
    serena_memories = list_serena_memories()

    # Actually search episodic memory
    episodic_results = search_episodic_memory(query_terms)

    messages = []

    # Episodic memory results (if found) - show first
    if episodic_results:
        results_text = []
        for i, r in enumerate(episodic_results, 1):
            results_text.append(f"   {i}. [{r['date']}] {r['snippet']}")
        messages.append(
            "Relevant past conversations:\n" + "\n".join(results_text) +
            f"\n   For more: mcp__plugin_episodic-memory_episodic-memory__search(query='{query_terms}')"
        )
    else:
        # Fallback: suggest manual search
        messages.append(
            "Episodic Memory:\n"
            f"   mcp__plugin_episodic-memory_episodic-memory__search(query='{query_terms}')"
        )

    # Auto-read relevant Serena memories
    if serena_memories:
        relevant = find_relevant_memories(query_terms, serena_memories, max_count=2)
        if relevant:
            snippets = read_memory_snippets(relevant, max_chars_per_memory=500)
            if snippets:
                matched_keywords = [k for k in query_terms.lower().split()
                                   if any(k in m.lower() for m in relevant)]
                match_info = f" (matched: {', '.join(matched_keywords[:3])})" if matched_keywords else ""
                messages.append(
                    f"Relevant Memories Found{match_info}:\n\n{snippets}\n\n"
                    f"For more: mcp__router__serena__read_memory(memory_file_name='...')"
                )

        # Still list other available memories
        other_memories = [m for m in serena_memories if m not in relevant][:3]
        if other_memories:
            memory_list = ", ".join(other_memories)
            messages.append(
                f"Other Serena Memories: {memory_list}"
            )

    # Knowledge graph (structured facts/relations)
    messages.append(
        "Knowledge Graph:\n"
        "   mcp__memory__search_nodes(query='<topic>')"
    )

    return {
        "found": bool(episodic_results),
        "conversations": episodic_results,
        "message": "\n\n".join(messages),
        "serena_memories": serena_memories
    }

def main():
    """Session start hook entry point."""

    # Read session data from stdin first (need agentId for reset)
    try:
        input_data = json.loads(sys.stdin.read())
    except json.JSONDecodeError:
        input_data = {}

    # Check if this is a subagent (has agentId)
    agent_id = input_data.get("agentId")

    # Reset enforcement counters - pass agent_id to inherit phase if subagent
    reset_enforcement_counters(agent_id)

    # Clean up stale output files (only for main agent, not subagents)
    cleanup_message = None
    if not agent_id:
        try:
            from output_cleanup import cleanup_stale_outputs
            result = cleanup_stale_outputs(max_age_hours=48, dry_run=False)
            if result["files_deleted"] > 0:
                space_mb = result["space_reclaimed"] / (1024 * 1024)
                cleanup_message = f"🧹 Cleaned {result['files_deleted']} stale output files ({space_mb:.1f} MB)"
        except Exception:
            pass  # Fail silently - cleanup shouldn't break session start

    # Run inventory to discover capabilities
    inventory_output = run_inventory()

    # Get any initial context from the session
    initial_messages = input_data.get("messages", [])

    # Extract potential search terms from first user message
    query_terms = "agent-swarm workflow automation"
    if initial_messages:
        first_msg = initial_messages[0].get("content", "")
        # Simple heuristic: use first few words
        words = first_msg.split()[:5]
        if words:
            query_terms = " ".join(words)

    # Suggest memory options
    results = suggest_memory_options(query_terms)

    # Build output message
    messages = []

    # Add hierarchical context (only for main agent, not subagents)
    if not agent_id:
        context_summary = get_session_context(Path.cwd())
        if context_summary:
            messages.append(f"Project Context:\n{context_summary}")

    # Add cleanup message if files were cleaned
    if cleanup_message:
        messages.append(cleanup_message)

    # Add inventory if available
    if inventory_output:
        messages.append("📦 Capability Inventory:\n" + inventory_output[:1000])  # Limit size

    # Add memory suggestions (always show the message, which now includes auto-read snippets)
    messages.append(results.get("message", ""))

    # Return result with suggestion
    output = {
        "systemMessage": "\n\n".join(messages) if messages else ""
    }

    print(json.dumps(output))

if __name__ == "__main__":
    main()
