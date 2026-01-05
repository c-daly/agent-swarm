#!/bin/bash
# Injects subagent briefing into Task tool prompts
# Hook: PreToolUse for Task tool

# Read input from stdin
INPUT=$(cat)

# Extract the prompt from the tool input
PROMPT=$(echo "$INPUT" | jq -r '.tool_input.prompt // empty')

if [ -n "$PROMPT" ]; then
    # Read the briefing
    BRIEFING=$(cat ~/.claude/hooks/subagent-briefing.md 2>/dev/null || echo "")

    if [ -n "$BRIEFING" ]; then
        # Output continue signal (allow the tool, briefing is injected via CLAUDE.md)
        echo '{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow"}}'
    else
        echo '{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow"}}'
    fi
else
    echo '{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow"}}'
fi
