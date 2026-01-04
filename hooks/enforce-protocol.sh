#!/bin/bash
# General protocol enforcement hook
# Validates tool usage against CLAUDE.md guidelines

# Read input from stdin
INPUT=$(cat)

# Extract tool name
TOOL_NAME=$(echo "$INPUT" | jq -r '.tool_name // empty' 2>/dev/null)

# Allow by default - specific enforcement is in combined-enforcement.py
echo '{"hookSpecificOutput": {"permissionDecision": "allow"}}'
