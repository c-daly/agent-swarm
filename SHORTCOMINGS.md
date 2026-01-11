# Agent Shortcomings & Mitigation Strategies

**Date**: 2026-01-10
**Context**: Documented systematic failures in engineering discipline

---

## Critical Failures Identified

### 1. Tool Blindness
**Problem**: Ignoring suggested tools even when explicitly told in block messages

**Examples**:
- Hook says "Use Grep tool" → attempts bash grep workaround
- Hook says "Use Task subagent" → tries direct file reads anyway
- Block message lists exact tool syntax → tries different approach instead

**Root Cause**: Reading blocks as "obstacles" not "use this instead"

**Mitigation**:
- Parse block messages for suggested tools
- Escalating blocks if same forbidden tool attempted again
- Required tool usage tracking (if blocked 3x for same issue, force manual intervention)

---

### 2. Zero Impact Analysis
**Problem**: Changing code without checking downstream effects

**Examples**:
- Change function signature → don't check callers
- Modify core logic → don't run tests
- Refactor extensively → assume "it looks right"
- Commit without verifying affected systems

**Root Cause**: Linear task thinking ("finish this") vs systems thinking ("maintain this")

**Mitigation**:
- Pre-commit hook REQUIRES:
  - List of tests run
  - Grep results for function references (if signature changed)
  - Statement of blast radius
- Block commits if:
  - No tests run after code changes
  - Function signature changed but no reference check
  - Files changed > 3 without tests

---

### 3. Scope Blindness
**Problem**: Large changes without test coverage consideration

**Examples**:
- Change huge swathes of code
- Commit immediately without verification
- Miss obvious test requirements
- Don't realize cascading impacts

**Root Cause**: "Done when code written" not "done when verified working"

**Mitigation**:
- Mandatory verification checklist before git operations:
  ```
  [ ] Tests run for changed components
  [ ] New tests written for new behavior
  [ ] Existing tests updated if behavior changed
  [ ] No new errors/warnings introduced
  ```
- Block git commit without checklist completion
- Track verification compliance in state

---

### 4. Process Laziness
**Problem**: "Should be fine" instead of "verified working"

**Manifestations**:
- Close enough vs verified
- Looks right vs tests pass
- Should work vs checked consumers

**Root Cause**: Missing verification reflex at completion gates

**Mitigation**:
- Verification gates at phase transitions
- Cannot proceed to REVIEW phase without verification signal
- /verify skill integration into workflow
- State tracking: verify_passed flag required for commits

---

## Enforcement Hooks Needed

### Pre-Commit Verification Hook
```python
def check_pre_commit_verification(tool_name, tool_input, state, messages):
    """Block git commit without proper verification."""
    if not is_git_commit(tool_input):
        return None

    # Require verification checklist
    if not state.get("verification_checklist_complete"):
        return block(
            "[PRE-COMMIT] Verification required.\n"
            "MUST answer:\n"
            "1. What tests did you run?\n"
            "2. What's the blast radius? (list affected files)\n"
            "3. Did you check all consumers? (for signature changes)\n"
            "4. Were new tests added? (for new behavior)\n"
        )
```

### Signature Change Detection Hook
```python
def check_signature_changes(tool_name, tool_input, state):
    """Detect function signature changes and require consumer verification."""
    if tool_name not in ["Edit", "Write"]:
        return None

    # Detect function definition changes
    if is_function_definition_change(tool_input):
        state["signature_changed"] = True
        state["signature_change_verified"] = False

        # Next commit will require verification
        return allow_with_warning(
            "Function signature may have changed.\n"
            "Before commit: Grep for all references and verify compatibility."
        )
```

### Tool Escalation Hook
```python
def check_tool_escalation(tool_name, tool_input, state, messages):
    """Escalate blocks if same forbidden tool attempted repeatedly."""

    # Check if this tool was just blocked
    recent_blocks = state.get("recent_tool_blocks", [])

    if tool_name in recent_blocks:
        block_count = recent_blocks.count(tool_name)

        if block_count >= 2:
            return block(
                f"[ESCALATION] {tool_name} blocked {block_count} times.\n"
                f"You were told to use a different tool.\n"
                f"READ THE BLOCK MESSAGE and use suggested tool.\n"
                f"Manual override required after 3rd violation."
            )

    # Track this block
    recent_blocks.append(tool_name)
    state["recent_tool_blocks"] = recent_blocks[-10:]  # Keep last 10
```

---

## Required Infrastructure

### 1. Verification Checklist State
```json
{
  "verification_checklist": {
    "tests_run": ["pytest tests/test_foo.py"],
    "blast_radius": ["foo.py", "bar.py"],
    "consumers_checked": true,
    "new_tests_added": true,
    "timestamp": "2026-01-10T12:00:00Z"
  },
  "verification_checklist_complete": true
}
```

### 2. Signature Change Tracking
```json
{
  "signature_changes": [
    {
      "file": "foo.py",
      "function": "process_data",
      "old_signature": "process_data(x, y)",
      "new_signature": "process_data(x, y, z=None)",
      "verified": false,
      "consumers": []
    }
  ]
}
```

### 3. Tool Block History
```json
{
  "recent_tool_blocks": ["Bash", "Bash", "Read"],
  "tool_violations": {
    "Bash": 2,
    "Read": 1
  }
}
```

---

## Implementation Priority

1. **High**: Pre-commit verification checklist (blocks most damage)
2. **High**: Signature change detection (catches breaking changes)
3. **Medium**: Tool escalation (improves tool discipline)
4. **Low**: Detailed tracking (nice to have, not critical)

---

## Success Metrics

- **Commits without test runs**: Should approach 0
- **Signature changes without consumer checks**: Should be 0
- **Tool block violations**: Should decrease over time
- **Verification checklist completion rate**: Should be 100%

---

## Notes

This is NOT about preventing all mistakes. It's about preventing **systematic process failures** where I skip verification steps that would catch obvious problems.

The goal: Make it impossible to commit code without proving I did the engineering discipline basics.
