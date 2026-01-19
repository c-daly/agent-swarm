#!/usr/bin/env python3
"""PostToolUse hook - Summarize large MCP responses with Haiku.

For MCP tool responses over a threshold, generates a concise summary
and injects it into the conversation to save context.
"""

import json
import os
import sys
from pathlib import Path

# Only summarize responses larger than this (chars)
SIZE_THRESHOLD = 2000

# Only summarize MCP tools (not native Claude tools)
MCP_PREFIX = "mcp__"

# Cache to avoid re-summarizing identical responses
CACHE_FILE = Path.home() / ".claude/plugins/agent-swarm/.state/summary_cache.json"
MAX_CACHE_SIZE = 100


def load_cache() -> dict:
    if CACHE_FILE.exists():
        try:
            return json.loads(CACHE_FILE.read_text())
        except:
            pass
    return {}


def save_cache(cache: dict) -> None:
    # Keep only recent entries
    if len(cache) > MAX_CACHE_SIZE:
        items = sorted(cache.items(), key=lambda x: x[1].get("ts", 0))
        cache = dict(items[-MAX_CACHE_SIZE:])
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    CACHE_FILE.write_text(json.dumps(cache, indent=2))


def get_response_hash(content: str) -> str:
    import hashlib
    return hashlib.sha256(content.encode()).hexdigest()[:16]


def log_debug(msg: str) -> None:
    """Log debug message to file."""
    # DISABLED: Debug logging no longer written to file
    return  # Skip file logging
    log_file = Path.home() / ".claude/plugins/agent-swarm/.state/summarizer.log"
    with open(log_file, "a") as f:
        from datetime import datetime
        f.write(f"[{datetime.now().isoformat()}] {msg}\n")


def summarize_with_llm(content: str, tool_name: str) -> str | None:
    """Call Haiku or GPT-4o-mini to summarize the MCP response."""
    # Extract tool base name for context
    base_name = tool_name.split("__")[-1] if "__" in tool_name else tool_name

    prompt = f"""Summarize this {base_name} tool response concisely. Focus on:
- Key findings/results
- Important names, paths, or identifiers
- Any errors or warnings
- Count of items if it's a list

Keep it under 200 words. Be direct, no preamble.

Response to summarize:
{content[:8000]}"""

    # Try Anthropic first
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    if anthropic_key:
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=anthropic_key)
            response = client.messages.create(
                model="claude-haiku-3-5-20241022",
                max_tokens=500,
                messages=[{"role": "user", "content": prompt}]
            )
            log_debug(f"Summarized {len(content)} chars with Haiku")
            return response.content[0].text
        except Exception as e:
            log_debug(f"Anthropic failed: {e}")

    # Try OpenAI as fallback
    openai_key = os.environ.get("OPENAI_API_KEY")
    if openai_key:
        try:
            import openai
            client = openai.OpenAI(api_key=openai_key)
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                max_tokens=500,
                messages=[{"role": "user", "content": prompt}]
            )
            log_debug(f"Summarized {len(content)} chars with GPT-4o-mini")
            return response.choices[0].message.content
        except Exception as e:
            log_debug(f"OpenAI failed: {e}")

    log_debug(f"No API key available (ANTHROPIC_API_KEY={bool(anthropic_key)}, OPENAI_API_KEY={bool(openai_key)})")
    return None


def main():
    try:
        raw_input = sys.stdin.read()
        input_data = json.loads(raw_input)
    except json.JSONDecodeError:
        print(json.dumps({}))
        return

    tool_name = input_data.get("tool_name", "")
    tool_response = input_data.get("tool_response", "")

    # Only process MCP tools
    if not tool_name.startswith(MCP_PREFIX):
        print(json.dumps({}))
        return

    # Get the response content
    content = str(tool_response) if tool_response else ""

    # Check size threshold
    if len(content) < SIZE_THRESHOLD:
        print(json.dumps({}))
        return

    # Check cache
    content_hash = get_response_hash(content)
    cache = load_cache()

    if content_hash in cache:
        summary = cache[content_hash].get("summary", "")
        log_debug(f"Cache hit for {tool_name}")
    else:
        # Generate summary
        log_debug(f"Summarizing {tool_name} response ({len(content)} chars)")
        summary = summarize_with_llm(content, tool_name)
        if summary:
            import time
            cache[content_hash] = {"summary": summary, "ts": time.time(), "tool": tool_name}
            save_cache(cache)

    if not summary:
        # Empty JSON = no action
        print(json.dumps({}))
        return

    # Output via additionalContext (shows as system-reminder)
    summary_text = f"📋 MCP Summary ({len(content):,}→{len(summary)} chars): {summary}"
    output = {
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": summary_text
        }
    }
    print(json.dumps(output))


if __name__ == "__main__":
    main()
