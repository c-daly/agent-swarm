#!/usr/bin/env python3
"""Minimal test: spawn a subagent via Claude Agent SDK."""

import anyio
from claude_agent_sdk import query, AssistantMessage, TextBlock, ResultMessage


async def main():
    print("Spawning subagent...")
    
    async for message in query(prompt="Say exactly: 'hello from subagent'"):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    print(f"Subagent: {block.text}")
        elif isinstance(message, ResultMessage):
            print(f"Done. Turns: {message.num_turns}")


if __name__ == "__main__":
    anyio.run(main)
