#!/bin/bash
# Enforces that Task prompts include the subagent briefing
# Hook: PreToolUse for Task tool
#
# Instead of injecting briefing (which doesn't work for Task),
# this hook ENFORCES that the orchestrator assembled the prompt correctly.

# Read input from stdin
INPUT=$(cat)

# Extract the prompt from the tool input
PROMPT=$(echo "$INPUT" | jq -r '.tool_input.prompt // empty')

if [ -z "$PROMPT" ]; then
    # No prompt provided - allow (Task tool will handle error)
    echo '{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow"}}'
    exit 0
fi

# Check if prompt contains the briefing marker
if echo "$PROMPT" | grep -q "SUBAGENT OPERATING PROTOCOL"; then
    # Briefing is present - allow
    echo '{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow"}}'
    exit 0
fi

# Briefing is missing - deny with instructions
# NOTE: "block" is IGNORED for Task tool, must use "deny"
# NOTE: Must use "permissionDecisionReason" not "message"
cat << 'EOF'
{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": "[BRIEFING_REQUIRED] Prepend hooks/subagent-briefing.md to Task prompt as '# SUBAGENT OPERATING PROTOCOL'. Re-call with run_in_background=true."}}
EOF
