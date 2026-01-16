#!/usr/bin/env python3
"""Generate Claude MCP settings from backends config.

Outputs mcpServers config with router as the entry point.
"""

import json
from pathlib import Path

ROOT = Path(__file__).parent.parent
BACKENDS_FILE = ROOT / "config" / "backends.json"
ROUTER_BIN = ROOT / "bin" / "mcp-router"
CLAUDE_SETTINGS = Path.home() / ".claude" / "settings.json"


def generate():
    """Generate mcpServers config."""
    mcp_servers = {
        "router": {
            "command": str(ROUTER_BIN),
        }
    }

    # Load backends to show what's available
    if BACKENDS_FILE.exists():
        backends = json.loads(BACKENDS_FILE.read_text())
        print(f"Router will handle {len(backends)} backend(s): {', '.join(backends.keys())}")

    return {"mcpServers": mcp_servers}


def merge_settings(new_mcp: dict) -> dict:
    """Merge new mcpServers into existing settings."""
    if CLAUDE_SETTINGS.exists():
        settings = json.loads(CLAUDE_SETTINGS.read_text())
    else:
        settings = {}

    existing_mcp = settings.get("mcpServers", {})
    existing_mcp.update(new_mcp["mcpServers"])
    settings["mcpServers"] = existing_mcp
    return settings


if __name__ == "__main__":
    new_config = generate()
    merged = merge_settings(new_config)

    print(f"\nWriting to {CLAUDE_SETTINGS}:")
    print(json.dumps(merged["mcpServers"], indent=2))

    CLAUDE_SETTINGS.write_text(json.dumps(merged, indent=2))
    print("\nDone.")
