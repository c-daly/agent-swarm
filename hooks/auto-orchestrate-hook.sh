#!/bin/bash
# Auto-orchestrate hook for UserPromptSubmit
# Detects complex tasks and suggests workflow activation

# Read input from stdin
INPUT=$(cat)

# Extract the prompt
PROMPT=$(echo "$INPUT" | jq -r '.prompt // .message // empty' 2>/dev/null)

# For now, just allow - the CLAUDE.md classification system handles this
echo '{"hookSpecificOutput": {"permissionDecision": "allow"}}'
