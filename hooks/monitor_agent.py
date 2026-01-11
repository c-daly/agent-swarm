#!/usr/bin/env python3
"""
Monitor Agent - Contextual enforcement using Haiku API.

Provides lightweight contextual validation for scenarios where regex/rules are insufficient.
Used for: commit message validation, classification appropriateness, context understanding.
"""

import os
import json
import re
from typing import Dict, Optional, Any

# Try to import anthropic, gracefully degrade if not available
try:
    import anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False


def needs_monitoring(tool_name: str, tool_input: dict, state: dict) -> bool:
    """
    Decide if this tool invocation needs monitor agent review.

    Criteria for monitoring:
    - Git commits (validate message content)
    - First file edit with SIMPLE classification (validate appropriateness)
    - COMPLEX tasks without workflow invocation

    Returns: True if monitor should be called
    """
    # Only monitor if API is available
    if not ANTHROPIC_AVAILABLE:
        return False

    # Monitor git commits for message violations
    if tool_name == "Bash" and "git commit" in tool_input.get("command", ""):
        return True

    # Monitor first file edit to validate SIMPLE classification
    if tool_name in {"Write", "Edit", "mcp__plugin_serena_serena__replace_symbol_body",
                     "mcp__plugin_serena_serena__create_text_file",
                     "mcp__plugin_serena_serena__replace_content"}:
        classification = state.get("classification_type")
        files_edited = state.get("files_edited_this_session", [])

        # Check on first edit if classified as SIMPLE
        if classification == "SIMPLE" and len(files_edited) == 0:
            return True

    return False


def call_monitor_agent(tool_name: str, tool_input: dict, state: dict) -> Optional[Dict[str, Any]]:
    """
    Call Haiku API to make contextual enforcement decision.

    Returns: Decision dict with structure:
        {
            "allowed": bool,
            "reason": str,
            "confidence": float  # 0.0-1.0
        }
    Or None if API call fails or is unavailable.
    """
    if not ANTHROPIC_AVAILABLE:
        return None

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None

    try:
        client = anthropic.Anthropic(api_key=api_key)

        # Build context-specific prompt based on tool
        prompt = _build_monitor_prompt(tool_name, tool_input, state)

        # Call Haiku for fast, cheap decision
        response = client.messages.create(
            model="claude-3-5-haiku-20241022",
            max_tokens=200,
            temperature=0,
            messages=[{
                "role": "user",
                "content": prompt
            }]
        )

        # Parse response
        decision_text = response.content[0].text.strip()
        return _parse_decision(decision_text)

    except Exception as e:
        # Log error but don't block - fail open for availability
        import sys
        print(f"Monitor agent error: {e}", file=sys.stderr)
        return None


def _build_monitor_prompt(tool_name: str, tool_input: dict, state: dict) -> str:
    """Build prompt for monitor agent based on context."""

    # Git commit validation
    if tool_name == "Bash" and "git commit" in tool_input.get("command", ""):
        command = tool_input["command"]

        # Extract commit message
        message = _extract_commit_message(command)

        return f"""You are validating a git commit message against project standards.

STANDARDS (from CLAUDE.md):
- NEVER add attributions, emoji, or decorations to commit messages
- Follow existing repository conventions
- Focus on the "why" rather than the "what"
- Keep messages concise (1-2 sentences)

COMMIT MESSAGE TO VALIDATE:
{message}

VIOLATIONS TO CHECK:
1. Attribution text like "Generated with Claude" or "Co-Authored-By: Claude"
2. Emoji (any Unicode emoji characters)
3. Robot emoji 🤖 or similar decorations
4. Marketing/branding language

Respond EXACTLY in this format:
ALLOWED: yes/no
REASON: (one sentence explanation)
CONFIDENCE: (0.0-1.0)

If the message violates standards, respond: "ALLOWED: no"
If the message is clean, respond: "ALLOWED: yes"
"""

    # Classification validation for SIMPLE tasks
    if tool_name in {"Write", "Edit"}:
        file_path = tool_input.get("file_path", "unknown")
        classification = state.get("classification_type", "unknown")

        # Get recent conversation context if available
        # For now, just validate based on state

        return f"""You are validating task classification for workflow enforcement.

TASK CLASSIFICATION: {classification}
FILE BEING EDITED: {file_path}
FILES EDITED SO FAR: {len(state.get("files_edited_this_session", []))}

CLASSIFICATION RULES (from CLAUDE.md):
- SIMPLE: Single file, <50 lines, clear requirements
- COMPLEX: Multiple files OR unclear scope OR architectural decisions

Red flags that mean COMPLEX, not SIMPLE:
- Multiple files need changes
- Unsure where code should go
- Requirements have ambiguity
- Architectural decisions involved

Based on the context, is SIMPLE classification appropriate?

Respond EXACTLY in this format:
ALLOWED: yes/no
REASON: (one sentence explanation)
CONFIDENCE: (0.0-1.0)

If SIMPLE is appropriate, respond: "ALLOWED: yes"
If should be COMPLEX, respond: "ALLOWED: no"
"""

    return ""


def _extract_commit_message(command: str) -> str:
    """Extract commit message from git command."""
    # Handle heredoc format
    heredoc_match = re.search(r'<<["\']?EOF["\']?\s*(.*?)\s*EOF', command, re.DOTALL)
    if heredoc_match:
        return heredoc_match.group(1)

    # Handle -m flag
    msg_match = re.search(r'-m\s+["\'](.+?)["\']', command, re.DOTALL)
    if msg_match:
        return msg_match.group(1)

    # Handle -m "$(cat <<'EOF' ... EOF)" format
    cat_match = re.search(r'-m\s+"\$\(cat\s+<<["\']?EOF["\']?\s*(.*?)\s*EOF', command, re.DOTALL)
    if cat_match:
        return cat_match.group(1)

    return "(unable to extract message)"


def _parse_decision(text: str) -> Optional[Dict[str, Any]]:
    """Parse monitor agent response into decision dict."""
    try:
        # Extract components using regex
        allowed_match = re.search(r'ALLOWED:\s*(yes|no)', text, re.IGNORECASE)
        reason_match = re.search(r'REASON:\s*(.+?)(?:\n|$)', text, re.DOTALL)
        confidence_match = re.search(r'CONFIDENCE:\s*([\d.]+)', text)

        if not allowed_match:
            return None

        return {
            "allowed": allowed_match.group(1).lower() == "yes",
            "reason": reason_match.group(1).strip() if reason_match else "No reason provided",
            "confidence": float(confidence_match.group(1)) if confidence_match else 0.5
        }
    except Exception:
        return None


def format_monitor_result(decision: Dict[str, Any]) -> dict:
    """
    Convert monitor decision to hook result format.

    Args:
        decision: Dict with "allowed", "reason", "confidence" keys

    Returns: Hook result dict ready to return from pre_tool_use hook
    """
    if decision["allowed"]:
        return {
            "allowed": True,
            "message": f"[MONITOR] Approved: {decision['reason']}"
        }
    else:
        return {
            "allowed": False,
            "message": (
                f"[MONITOR AGENT] {decision['reason']}\n"
                f"Confidence: {decision['confidence']:.0%}\n"
                "\n"
                "The monitor agent identified a potential policy violation.\n"
                "Please review and correct before proceeding."
            )
        }


def detect_batch_need(tool_name: str, tool_input: dict, state: dict, recent_messages: list) -> dict | None:
    """
    Detect patterns in conversation indicating batch operations needed.
    
    Returns block decision if batch operation clearly needed, None otherwise.
    """
    import re
    
    # Only check on first few searches/reads
    search_count = state.get("search_count", 0)
    read_count = state.get("read_count", 0)
    
    # Only intervene early (before limit hit)
    if search_count > 2 or read_count > 2:
        return None
    
    # Get last 3 messages (user + assistant turns)
    recent_text = " ".join([
        msg.get("content", "") 
        for msg in recent_messages[-3:]
    ]).lower()
    
    # Patterns indicating batch operations
    batch_indicators = [
        (r'\b(\d+)\s+(files?|patterns?|searches?)', 'files/patterns'),
        (r'check\s+all', 'all checks'),
        (r'find\s+all\s+.*\s+that', 'find all pattern'),
        (r'across\s+(multiple|many)', 'multiple targets'),
        (r'throughout\s+the\s+codebase', 'codebase-wide'),
        (r'every\s+\w+\s+in', 'iteration pattern'),
    ]
    
    for pattern, description in batch_indicators:
        match = re.search(pattern, recent_text)
        if match:
            # Extract number if present
            num = None
            try:
                if match.lastindex and match.lastindex >= 1:
                    num = int(match.group(1))
            except (ValueError, IndexError):
                pass
            
            # If explicit number > 5, or qualitative indicator ("all", "every", etc.)
            if num and num > 5:
                return {
                    "allowed": False,
                    "message": (
                        f"[PROACTIVE BLOCK] Detected intent to process {num} items ({description}).\n\n"
                        f"REQUIRED: Use batch approach BEFORE starting:\n\n"
                        f"✓ OPTION 1: Spawn Explorer subagent\n"
                        f"  Task(subagent_type='Explore', prompt='...')\n\n"
                        f"✓ OPTION 2: Write batch script\n"
                        f"  Write(file_path='/tmp/batch_search.py', content='''...''')\n\n"
                        f"Don't start direct tool calls when you know you'll hit limits."
                    )
                }
            elif not num and description in ['all checks', 'find all pattern', 'codebase-wide']:
                return {
                    "allowed": False,
                    "message": (
                        f"[PROACTIVE BLOCK] Detected codebase-wide operation ({description}).\n\n"
                        f"Use Explorer subagent for codebase exploration:\n"
                        f"  Task(subagent_type='Explore', prompt='Find all {description}...')"
                    )
                }
    
    return None
