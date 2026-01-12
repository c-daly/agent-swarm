# Poll At Interval

**User-Invocable:** Yes (`/poll <seconds> <tool> <condition>`)

Controlled polling for async operations. Waits for a condition to be met, checking at specified intervals.

## When to Use

- Waiting for Greptile review to complete
- Waiting for CI/CD status changes
- Any async operation that needs status polling
- Avoiding rate limit blocks from repeated tool calls

## Syntax

```
/poll <interval_seconds> <tool_name> <condition_field> <expected_value>
```

**Examples:**
```
/poll 30 greptile:get_code_review status COMPLETED
/poll 60 gh:pr_checks conclusion success
```

## How It Works

1. Executes the specified tool
2. Checks if condition is met
3. If not met, waits `interval_seconds`
4. Repeats until condition met or max iterations (default: 20)
5. Returns final result

## Parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| `interval` | Seconds between checks | Required |
| `tool` | MCP tool to call | Required |
| `condition_field` | JSON path to check | Required |
| `expected_value` | Value that signals completion | Required |
| `max_iterations` | Maximum poll attempts | 20 |
| `tool_params` | Parameters to pass to tool | {} |

## Bypass Hook Limits

This skill is whitelisted in combined-enforcement.py to avoid the 6-call limit.
The hook recognizes polling patterns and allows controlled repetition.

## Implementation

The skill spawns a background task that:
1. Calls the tool with provided params
2. Extracts `condition_field` from response
3. Compares to `expected_value`
4. If match: returns result
5. If no match: sleeps `interval`, repeats

```python
import time
import json

def poll_until(tool_name, tool_params, condition_field, expected_value,
               interval=30, max_iterations=20):
    """Poll a tool until condition is met."""
    for i in range(max_iterations):
        result = call_mcp_tool(tool_name, tool_params)

        # Extract nested field (e.g., "codeReview.status")
        value = result
        for key in condition_field.split('.'):
            value = value.get(key, {})

        if value == expected_value:
            return {"success": True, "iterations": i + 1, "result": result}

        if i < max_iterations - 1:
            time.sleep(interval)

    return {"success": False, "iterations": max_iterations, "last_result": result}
```

## Integration with Hooks

To whitelist polling in `combined-enforcement.py`, add to `check_mcp_script_requirement`:

```python
# Whitelist polling operations (controlled repetition)
POLLING_TOOLS = {
    "mcp__plugin_greptile_greptile__get_code_review",
    "mcp__plugin_greptile_greptile__list_code_reviews",
}

if tool_name in POLLING_TOOLS:
    # Check if this is a poll skill invocation
    if state.get("poll_skill_active"):
        return None  # Allow polling
```
