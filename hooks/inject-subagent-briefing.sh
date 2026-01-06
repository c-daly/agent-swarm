#!/bin/bash
# Injects subagent briefing into Task tool prompts
# Hook: PreToolUse for Task tool

# Read input from stdin
INPUT=$(cat)

# Extract the original prompt from the tool input
ORIGINAL_PROMPT=$(echo "$INPUT" | jq -r '.tool_input.prompt // empty')

if [ -z "$ORIGINAL_PROMPT" ]; then
    # No prompt, just allow
    echo '{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow"}}'
    exit 0
fi

# Read the briefing from the plugin directory (not ~/.claude/hooks)
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$HOME/.claude/plugins/agent-swarm}"
BRIEFING_FILE="$PLUGIN_ROOT/hooks/subagent-briefing.md"

if [ ! -f "$BRIEFING_FILE" ]; then
    # Briefing doesn't exist, just allow without modification
    echo '{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow"}}'
    exit 0
fi

BRIEFING=$(cat "$BRIEFING_FILE")

# Create modified prompt with briefing prepended
MODIFIED_PROMPT="# SUBAGENT OPERATING PROTOCOL

$BRIEFING

---

# YOUR TASK

$ORIGINAL_PROMPT"

# Escape the modified prompt for JSON (escape quotes and newlines)
ESCAPED_PROMPT=$(echo "$MODIFIED_PROMPT" | jq -Rs .)

# Output modified tool input
echo "$INPUT" | jq --argjson prompt "$ESCAPED_PROMPT" '.tool_input.prompt = $prompt' | \
  jq '{
    hookSpecificOutput: {
      hookEventName: "PreToolUse",
      permissionDecision: "allow",
      modifiedToolInput: .tool_input
    }
  }'
