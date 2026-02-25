---
name: poll
description: Controlled polling for async operations at specified intervals
user_invocable: true
---

## Usage
```
/poll <interval_seconds> <tool_name> <condition_field> <expected_value>
```

Examples:
```
/poll 30 greptile:get_code_review status COMPLETED
/poll 60 gh:pr_checks conclusion success
```

## Parameters

| Param | Description | Default |
|-------|-------------|---------|
| interval | Seconds between checks | Required |
| tool | MCP tool to call | Required |
| condition_field | JSON path to check | Required |
| expected_value | Completion signal | Required |
| max_iterations | Max poll attempts | 20 |

## Behavior
1. Call tool -> check condition_field == expected_value
2. If not met, sleep interval seconds
3. Repeat until met or max_iterations reached

Whitelisted in enforcement hooks to avoid call limits.
