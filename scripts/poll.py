#!/usr/bin/env python3
"""
Poll At Interval - Controlled polling for async operations.

Usage:
    python3 poll.py <interval> <tool> <condition_field> <expected_value> [tool_params_json]

Examples:
    python3 poll.py 30 greptile:get_code_review codeReview.status COMPLETED '{"codeReviewId": "123"}'
    python3 poll.py 60 greptile:list_code_reviews codeReviews.0.status COMPLETED '{"prNumber": 147}'
"""

import sys
import time
import json
from pathlib import Path

# Add lib to path for mcp_bridge
sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

try:
    from mcp_bridge import call_mcp
except ImportError:
    print("Error: mcp_bridge not found. Ensure lib/mcp_bridge.py exists.")
    sys.exit(1)

# State file for tracking poll skill active status
STATE_FILE = Path(__file__).parent.parent / ".state" / "session.json"


def set_poll_active(active: bool):
    """Set poll_skill_active flag in state."""
    state = {}
    if STATE_FILE.exists():
        try:
            state = json.loads(STATE_FILE.read_text())
        except json.JSONDecodeError:
            pass

    state["poll_skill_active"] = active
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))


def extract_field(data: dict, field_path: str):
    """Extract a nested field from dict using dot notation.

    Supports array indexing: 'codeReviews.0.status'
    """
    value = data
    for key in field_path.split('.'):
        if value is None:
            return None
        if isinstance(value, list):
            try:
                value = value[int(key)]
            except (ValueError, IndexError):
                return None
        elif isinstance(value, dict):
            value = value.get(key)
        else:
            return None
    return value


def map_tool_name(short_name: str) -> str:
    """Map short tool names to full MCP tool names."""
    mappings = {
        "greptile:get_code_review": "mcp__plugin_greptile_greptile__get_code_review",
        "greptile:list_code_reviews": "mcp__plugin_greptile_greptile__list_code_reviews",
        "greptile:get_merge_request": "mcp__plugin_greptile_greptile__get_merge_request",
    }
    return mappings.get(short_name, short_name)


def poll_until(tool_name: str, tool_params: dict, condition_field: str,
               expected_value: str, interval: int = 30, max_iterations: int = 20):
    """Poll a tool until condition is met."""

    full_tool_name = map_tool_name(tool_name)

    print(f"[POLL] Starting: {tool_name}")
    print(f"[POLL] Condition: {condition_field} == {expected_value}")
    print(f"[POLL] Interval: {interval}s, Max iterations: {max_iterations}")
    print()

    set_poll_active(True)
    current_value = None

    try:
        for i in range(max_iterations):
            iteration = i + 1
            print(f"[POLL] Iteration {iteration}/{max_iterations}...")

            try:
                result = call_mcp(full_tool_name, tool_params)
            except Exception as e:
                print(f"[POLL] Error calling tool: {e}")
                if i < max_iterations - 1:
                    print(f"[POLL] Waiting {interval}s before retry...")
                    time.sleep(interval)
                continue

            # Extract the condition field
            current_value = extract_field(result, condition_field)
            print(f"[POLL] Current value: {current_value}")

            # Check condition
            if str(current_value) == str(expected_value):
                print(f"[POLL] Condition met after {iteration} iterations")
                return {
                    "success": True,
                    "iterations": iteration,
                    "result": result
                }

            if i < max_iterations - 1:
                print(f"[POLL] Waiting {interval}s...")
                time.sleep(interval)

        print(f"[POLL] Max iterations reached without condition being met")
        return {
            "success": False,
            "iterations": max_iterations,
            "last_value": current_value,
            "expected": expected_value
        }

    finally:
        set_poll_active(False)


def main():
    if len(sys.argv) < 5:
        print(__doc__)
        sys.exit(1)

    interval = int(sys.argv[1])
    tool_name = sys.argv[2]
    condition_field = sys.argv[3]
    expected_value = sys.argv[4]
    tool_params = json.loads(sys.argv[5]) if len(sys.argv) > 5 else {}

    result = poll_until(
        tool_name=tool_name,
        tool_params=tool_params,
        condition_field=condition_field,
        expected_value=expected_value,
        interval=interval
    )

    print()
    print("[POLL] Final result:")
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
