# Handoff: Subagent Briefing Enforcement

## Key Discoveries

### PreToolUse hooks and Task tool

1. **Cannot modify Task input** - `updatedInput`/`modifiedToolInput` are ignored
2. **Can deny Task** - BUT must use correct field:
   - `"permissionDecision": "block"` → **IGNORED** 
   - `"permissionDecision": "deny"` → **WORKS**
3. **Message field** - Use `permissionDecisionReason` not `message`

### Working deny response format:
```json
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": "Error message here"
  }
}
```

## Solution

1. **Iterate skill** - "Subagent Prompt Assembly" section tells orchestrators to assemble prompts with briefing
2. **Hook enforcement** - `inject-subagent-briefing.sh` denies Task without `SUBAGENT OPERATING PROTOCOL` in prompt

## Files
- `skills/iterate/SKILL.md` - Assembly instructions
- `hooks/inject-subagent-briefing.sh` - Enforcement (uses "deny" not "block")

## Testing
- Without marker → Denied ✓
- With marker → Allowed ✓
