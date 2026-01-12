#!/bin/bash
# Injects subagent briefing AND hierarchical context into Task tool prompts
# Hook: PreToolUse for Task tool

# Hook logging
LOG_FILE="$HOME/.claude/plugins/agent-swarm/.state/hooks.log"
mkdir -p "$(dirname "$LOG_FILE")"
log_hook() {
    echo "[$(date +%H:%M:%S.%3N)] PreToolUse    | inject-subagent-briefing  | $1" >> "$LOG_FILE"
}

# Read input from stdin
INPUT=$(cat)
log_hook "checking Task tool"

# Extract the original prompt from the tool input
ORIGINAL_PROMPT=$(echo "$INPUT" | jq -r '.tool_input.prompt // empty')

if [ -z "$ORIGINAL_PROMPT" ]; then
    # No prompt, just allow
    echo '{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow"}}'
    exit 0
fi

# Get plugin root and working directory
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$HOME/.claude/plugins/agent-swarm}"
WORKING_DIR=$(echo "$INPUT" | jq -r '.cwd // "."')
AGENT_TYPE=$(echo "$INPUT" | jq -r '.tool_input.subagent_type // "general-purpose"')

# Read the briefing
BRIEFING_FILE="$PLUGIN_ROOT/hooks/subagent-briefing.md"
if [ -f "$BRIEFING_FILE" ]; then
    BRIEFING=$(cat "$BRIEFING_FILE")
else
    BRIEFING=""
fi

# Get hierarchical context via Python
CONTEXT_SCRIPT="$PLUGIN_ROOT/hooks/context-injection.py"
if [ -f "$CONTEXT_SCRIPT" ]; then
    # Map subagent_type to agent type for context filtering
    case "$AGENT_TYPE" in
        "Explore") CONTEXT_AGENT="explorer" ;;
        "Plan") CONTEXT_AGENT="architect" ;;
        "general-purpose") CONTEXT_AGENT="implementer" ;;
        *) CONTEXT_AGENT="$AGENT_TYPE" ;;
    esac

    HIERARCHICAL_CONTEXT=$(python3 "$CONTEXT_SCRIPT" inject "$CONTEXT_AGENT" "$WORKING_DIR" 2>/dev/null)
else
    HIERARCHICAL_CONTEXT=""
fi

# Build the modified prompt
if [ -n "$HIERARCHICAL_CONTEXT" ] && [ -n "$BRIEFING" ]; then
    MODIFIED_PROMPT="# SUBAGENT OPERATING PROTOCOL

$BRIEFING

---

$HIERARCHICAL_CONTEXT

---

# YOUR TASK

$ORIGINAL_PROMPT"
elif [ -n "$BRIEFING" ]; then
    MODIFIED_PROMPT="# SUBAGENT OPERATING PROTOCOL

$BRIEFING

---

# YOUR TASK

$ORIGINAL_PROMPT"
else
    MODIFIED_PROMPT="$ORIGINAL_PROMPT"
fi

# Escape the modified prompt for JSON
ESCAPED_PROMPT=$(echo "$MODIFIED_PROMPT" | jq -Rs .)

# Output modified tool input
log_hook "INJECTED briefing for $AGENT_TYPE"
echo "$INPUT" | jq --argjson prompt "$ESCAPED_PROMPT" '.tool_input.prompt = $prompt' | \
  jq '{
    hookSpecificOutput: {
      hookEventName: "PreToolUse",
      permissionDecision: "allow",
      modifiedToolInput: .tool_input
    }
  }'
