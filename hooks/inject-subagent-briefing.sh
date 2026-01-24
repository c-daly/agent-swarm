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
{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": "[BRIEFING_REQUIRED] Task prompt must include subagent briefing.\n\nAssemble the prompt:\n1. Read: cat ~/.claude/plugins/agent-swarm/hooks/subagent-briefing.md\n2. Prepend to your task with header: # SUBAGENT OPERATING PROTOCOL\n3. Add phase restrictions if in iterate workflow\n4. Re-call Task with assembled prompt\n\nSubagent Tools (allowed_tools to include):\n- Shell: mcp-call pytest, mcp-call ruff, mcp-call git, etc.\n- Files: mcp-call native__read_file, mcp-call native__write_file\n- Search: mcp-call native__glob, mcp-call native__grep\n- Serena: mcp-call serena__find_symbol, etc.\n\nSee 'Subagent Prompt Assembly' in iterate skill for details."}}
EOF
