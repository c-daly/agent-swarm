#!/usr/bin/env python3
"""
Capability inventory - discover available tools, MCPs, skills, and resources.
Run at session start or when needing to find the right tool for a job.

Usage:
    python3 inventory.py all           - Full inventory
    python3 inventory.py mcp           - MCP servers only
    python3 inventory.py skills        - Skills only
    python3 inventory.py tools <query> - Find tool for specific need
"""

import json
import sys
from pathlib import Path

CLAUDE_DIR = Path.home() / ".claude"
PLUGINS_DIR = CLAUDE_DIR / "plugins"


def get_mcp_servers() -> dict:
    """Get configured MCP servers from settings."""
    settings_path = CLAUDE_DIR / "settings.json"
    if settings_path.exists():
        settings = json.loads(settings_path.read_text())
        return settings.get("mcpServers", {})
    return {}


def get_enabled_plugins() -> list:
    """Get list of enabled plugins."""
    settings_path = CLAUDE_DIR / "settings.json"
    if settings_path.exists():
        settings = json.loads(settings_path.read_text())
        enabled = settings.get("enabledPlugins", {})
        return [k for k, v in enabled.items() if v]
    return []


def find_skills(plugin_path: Path) -> list:
    """Find skills in a plugin directory."""
    skills = []
    skills_dir = plugin_path / "skills"
    if skills_dir.exists():
        for skill_dir in skills_dir.iterdir():
            if skill_dir.is_dir():
                skill_file = skill_dir / "SKILL.md"
                if skill_file.exists():
                    # Extract name and description from frontmatter
                    content = skill_file.read_text()
                    name = skill_dir.name
                    desc = ""
                    if "---" in content:
                        frontmatter = content.split("---")[1]
                        for line in frontmatter.split("\n"):
                            if line.startswith("description:"):
                                desc = line.replace("description:", "").strip()
                    skills.append({"name": name, "description": desc[:100]})
    return skills


def find_agents(plugin_path: Path) -> list:
    """Find agent definitions in a plugin."""
    agents = []
    agents_dir = plugin_path / "agents"
    if agents_dir.exists():
        for agent_file in agents_dir.glob("*.md"):
            if agent_file.name != "AGENT_RULES.md":
                content = agent_file.read_text()
                model = "unknown"
                if "**Model**:" in content:
                    model_line = [l for l in content.split("\n") if "**Model**:" in l]
                    if model_line:
                        model = model_line[0].split(":")[-1].strip()
                agents.append({"name": agent_file.stem, "model": model})
    return agents


def find_scripts(plugin_path: Path) -> list:
    """Find utility scripts in a plugin."""
    scripts = []
    scripts_dir = plugin_path / "scripts"
    if scripts_dir.exists():
        for script in scripts_dir.glob("*.py"):
            # Get first docstring line
            content = script.read_text()
            desc = ""
            if '"""' in content:
                doc = content.split('"""')[1].split("\n")[0].strip()
                desc = doc[:80]
            scripts.append({"name": script.name, "description": desc})
    return scripts


def get_known_mcp_tools() -> dict:
    """Known MCP tool categories."""
    return {
        "serena": {
            "purpose": "Semantic code analysis",
            "tools": [
                "find_symbol - Locate definitions",
                "find_references - Find usages",
                "get_definition - Get signature/docs",
                "list_dir - Code structure",
            ],
            "use_instead_of": "Read tool for code understanding",
        },
        "context7": {
            "purpose": "Documentation lookup",
            "tools": [
                "resolve-library-id - Get library ID",
                "query-docs - Get specific docs",
            ],
            "use_instead_of": "WebSearch for library docs",
        },
        "filesystem": {
            "purpose": "File operations",
            "tools": [
                "read_text_file - Read file content",
                "write_file - Create/overwrite file",
                "edit_file - Make line edits",
                "directory_tree - Get structure",
            ],
            "use_instead_of": "Bash cat/echo",
        },
        "memory": {
            "purpose": "Knowledge graph",
            "tools": [
                "create_entities - Add nodes",
                "create_relations - Link nodes",
                "search_nodes - Query graph",
            ],
            "use_instead_of": "Repeated context passing",
        },
    }


def format_inventory(
    include_mcp=True, include_skills=True, include_agents=True, include_scripts=True
) -> str:
    """Format full inventory."""
    lines = ["# Capability Inventory\n"]

    if include_mcp:
        lines.append("## MCP Servers\n")
        servers = get_mcp_servers()
        known = get_known_mcp_tools()

        for name, config in servers.items():
            lines.append(f"### {name}")
            if name in known:
                k = known[name]
                lines.append(f"  Purpose: {k['purpose']}")
                lines.append(f"  Use instead of: {k['use_instead_of']}")
                lines.append(f"  Tools: {', '.join(k['tools'][:3])}")
            else:
                lines.append(f"  Config: {json.dumps(config)[:50]}")
            lines.append("")

        # Add known MCPs from plugins
        lines.append("### From Plugins")
        for known_name, info in known.items():
            if known_name not in servers:
                lines.append(f"  {known_name}: {info['purpose']}")

    if include_skills or include_agents or include_scripts:
        lines.append("\n## Plugins\n")
        enabled = get_enabled_plugins()

        for plugin in enabled:
            plugin_name = plugin.split("@")[0]
            # Find plugin path
            for market_dir in (PLUGINS_DIR / "cache").iterdir():
                plugin_path = market_dir / plugin_name
                if plugin_path.exists():
                    # Get latest version
                    versions = list(plugin_path.iterdir())
                    if versions:
                        plugin_path = versions[-1]
                        lines.append(f"### {plugin_name}")

                        if include_skills:
                            skills = find_skills(plugin_path)
                            if skills:
                                lines.append(
                                    f"  Skills: {', '.join(s['name'] for s in skills)}"
                                )

                        if include_agents:
                            agents = find_agents(plugin_path)
                            if agents:
                                agent_strs = [
                                    f"{a['name']}({a['model']})" for a in agents
                                ]
                                lines.append(f"  Agents: {', '.join(agent_strs)}")

                        if include_scripts:
                            scripts = find_scripts(plugin_path)
                            if scripts:
                                lines.append(
                                    f"  Scripts: {', '.join(s['name'] for s in scripts)}"
                                )

                        lines.append("")

    return "\n".join(lines)


def find_tool_for(query: str) -> str:
    """Suggest the right tool for a need."""
    query_lower = query.lower()

    suggestions = []

    # Code analysis
    if any(
        w in query_lower
        for w in [
            "find",
            "symbol",
            "definition",
            "reference",
            "code",
            "function",
            "class",
        ]
    ):
        suggestions.append(
            "→ Use Serena: mcp__plugin_serena_serena__find_symbol / get_definition"
        )

    # Documentation
    if any(
        w in query_lower
        for w in ["docs", "documentation", "api", "how to", "example", "library"]
    ):
        suggestions.append(
            "→ Use Context7: mcp__context7__query-docs (after resolve-library-id)"
        )

    # Search
    if any(w in query_lower for w in ["search", "grep", "find text", "pattern"]):
        suggestions.append(
            "→ Use batch_search.py for multiple patterns, or Grep for single"
        )

    # GitHub
    if any(w in query_lower for w in ["pr", "issue", "github", "pull request"]):
        suggestions.append("→ Use gh_wrapper.py for summarized output")

    # File structure
    if any(w in query_lower for w in ["structure", "tree", "files", "directory"]):
        suggestions.append("→ Use mcp__filesystem__directory_tree or Serena list_dir")

    if not suggestions:
        suggestions.append(
            "No specific suggestion. Check full inventory with: inventory.py all"
        )

    return f"Tool suggestions for '{query}':\n" + "\n".join(suggestions)


def main():
    if len(sys.argv) < 2:
        print(format_inventory())
        return

    cmd = sys.argv[1]

    if cmd == "all":
        print(format_inventory())
    elif cmd == "mcp":
        print(
            format_inventory(
                include_skills=False, include_agents=False, include_scripts=False
            )
        )
    elif cmd == "skills":
        print(
            format_inventory(
                include_mcp=False, include_agents=False, include_scripts=False
            )
        )
    elif cmd == "tools" and len(sys.argv) >= 3:
        print(find_tool_for(" ".join(sys.argv[2:])))
    else:
        print(f"Unknown command: {cmd}")


if __name__ == "__main__":
    main()
