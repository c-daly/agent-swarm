#!/bin/bash
# Injects subagent briefing AND hierarchical context into Task tool prompts
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

# Get plugin root and working directory
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$HOME/.claude/plugins/agent-swarm}"
WORKING_DIR=$(echo "$INPUT" | jq -r '.cwd // "."')
AGENT_TYPE=$(echo "$INPUT" | jq -r '.tool_input.subagent_type // "general-purpose"')

# Read current phase from session state and get tool restrictions
STATE_FILE="$PLUGIN_ROOT/.state/session.json"
PHASE_RESTRICTIONS=""
if [ -f "$STATE_FILE" ]; then
    CURRENT_PHASE=$(jq -r '.phase // .iterate_phase // ""' "$STATE_FILE" 2>/dev/null)
    if [ -n "$CURRENT_PHASE" ] && [ "$CURRENT_PHASE" != "null" ]; then
        # Get phase restrictions via Python helper
        PHASE_RESTRICTIONS=$(python3 -c "
import sys
sys.path.insert(0, '$PLUGIN_ROOT/lib')
try:
    from phase_model import get_phase_info, TOOL_CATEGORIES, ToolCategory
    phase = get_phase_info('$CURRENT_PHASE')
    if phase:
        blocked = list(phase.blocked_tools)
        # Add tools not in allowed categories
        for tool, cat in TOOL_CATEGORIES.items():
            if cat and cat not in phase.allowed_categories:
                if tool not in blocked:
                    blocked.append(tool)
        if blocked:
            print('## PHASE RESTRICTIONS')
            print(f'Current phase: {phase.name}')
            print('**BLOCKED TOOLS (DO NOT USE):**')
            for t in sorted(set(blocked))[:15]:  # Top 15
                print(f'- {t}')
            print()
            print('If you need a blocked tool, STOP and report to orchestrator.')
except Exception as e:
    pass
" 2>/dev/null)
    fi
fi

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

$PHASE_RESTRICTIONS

---

$HIERARCHICAL_CONTEXT

---

# YOUR TASK

$ORIGINAL_PROMPT"
elif [ -n "$BRIEFING" ]; then
    MODIFIED_PROMPT="# SUBAGENT OPERATING PROTOCOL

$BRIEFING

$PHASE_RESTRICTIONS

---

# YOUR TASK

$ORIGINAL_PROMPT"
else
    MODIFIED_PROMPT="$ORIGINAL_PROMPT"
fi

# Escape the modified prompt for JSON
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
