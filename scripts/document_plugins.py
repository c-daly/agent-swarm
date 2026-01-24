#!/usr/bin/env python3
"""
Plugin Auto-Documentation Script

Detects newly installed Claude plugins and generates documentation for them.
Maintains a registry of documented plugins to avoid duplication.
"""

import json
from pathlib import Path
from datetime import datetime

PLUGINS_DIR = Path.home() / ".claude/plugins"
REGISTRY_FILE = PLUGINS_DIR / ".plugin_registry.json"
DOCS_DIR = Path.home() / ".claude/docs/plugins"

def load_registry():
    """Load the plugin registry (tracks documented plugins)"""
    if REGISTRY_FILE.exists():
        return json.loads(REGISTRY_FILE.read_text())
    return {"plugins": {}, "last_updated": None}

def save_registry(registry):
    """Save the plugin registry"""
    registry["last_updated"] = datetime.now().isoformat()
    REGISTRY_FILE.parent.mkdir(parents=True, exist_ok=True)
    REGISTRY_FILE.write_text(json.dumps(registry, indent=2))

def get_installed_plugins():
    """Get list of all installed plugins"""
    if not PLUGINS_DIR.exists():
        return []

    plugins = []
    for plugin_dir in PLUGINS_DIR.iterdir():
        if plugin_dir.is_dir() and not plugin_dir.name.startswith('.'):
            # Check for manifest
            manifest_path = plugin_dir / ".claude-plugin/manifest.json"
            if manifest_path.exists():
                try:
                    manifest = json.loads(manifest_path.read_text())
                    plugins.append({
                        "name": plugin_dir.name,
                        "path": str(plugin_dir),
                        "manifest": manifest
                    })
                except Exception:
                    pass  # Silent exception
    return plugins

def detect_new_plugins():
    """Find plugins not yet documented"""
    registry = load_registry()
    installed = get_installed_plugins()

    new_plugins = []
    for plugin in installed:
        if plugin["name"] not in registry["plugins"]:
            new_plugins.append(plugin)

    return new_plugins

def extract_plugin_features(plugin_dir):
    """Extract skills, hooks, agents, and tools from a plugin"""
    plugin_dir = Path(plugin_dir)
    features = {
        "skills": [],
        "hooks": [],
        "agents": [],
        "tools": []
    }

    # Find skills
    skills_dir = plugin_dir / "skills"
    if skills_dir.exists():
        for skill_path in skills_dir.iterdir():
            if skill_path.is_dir():
                skill_md = skill_path / "SKILL.md"
                if skill_md.exists():
                    # Extract skill metadata from frontmatter
                    content = skill_md.read_text()
                    if content.startswith("---"):
                        lines = content.split('\n')
                        metadata = {}
                        for line in lines[1:20]:
                            if line == "---":
                                break
                            if ": " in line:
                                key, val = line.split(": ", 1)
                                metadata[key.strip()] = val.strip()
                        features["skills"].append({
                            "name": skill_path.name,
                            "metadata": metadata
                        })

    # Find agents
    agents_dir = plugin_dir / "agents"
    if agents_dir.exists():
        for agent_file in agents_dir.glob("*.md"):
            features["agents"].append(agent_file.stem)

    # Extract hooks from manifest
    manifest_path = plugin_dir / ".claude-plugin/manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        hooks = manifest.get("hooks", {})
        features["hooks"] = list(hooks.keys())

    return features

def generate_plugin_docs(plugin):
    """Generate documentation for a plugin"""
    plugin_name = plugin["name"]
    plugin_path = Path(plugin["path"])
    features = extract_plugin_features(plugin_path)

    # Create docs directory for this plugin
    plugin_docs_dir = DOCS_DIR / plugin_name
    plugin_docs_dir.mkdir(parents=True, exist_ok=True)

    # Generate README.md
    readme_content = f"""# {plugin_name} Plugin

**Auto-generated documentation** - Created: {datetime.now().strftime('%Y-%m-%d')}

## Overview

{plugin["manifest"].get("description", "No description available")}

"""

    if features["skills"]:
        readme_content += "## Skills\n\n"
        for skill in features["skills"]:
            skill_name = skill["name"]
            description = skill["metadata"].get("description", "No description")
            readme_content += f"### {skill_name}\n\n"
            readme_content += f"{description}\n\n"
            readme_content += f"**Usage:** `/{plugin_name}:{skill_name}`\n\n"

    if features["agents"]:
        readme_content += "## Agents\n\n"
        for agent in features["agents"]:
            readme_content += f"- {agent}\n"
        readme_content += "\n"

    if features["hooks"]:
        readme_content += "## Hooks\n\n"
        for hook in features["hooks"]:
            readme_content += f"- {hook}\n"
        readme_content += "\n"

    readme_content += f"""
## Installation Location

`{plugin_path}`

## Manifest

```json
{json.dumps(plugin["manifest"], indent=2)}
```
"""

    # Write documentation
    readme_path = plugin_docs_dir / "README.md"
    readme_path.write_text(readme_content)

    return str(readme_path)

def main():
    print("=== PLUGIN AUTO-DOCUMENTATION ===\n")

    # Detect new plugins
    new_plugins = detect_new_plugins()

    if not new_plugins:
        print("✓ No new plugins to document")
        print(f"  Registry: {REGISTRY_FILE}")
        return

    print(f"Found {len(new_plugins)} new plugin(s):\n")

    registry = load_registry()

    for plugin in new_plugins:
        plugin_name = plugin["name"]
        print(f"📦 {plugin_name}")

        # Generate documentation
        doc_path = generate_plugin_docs(plugin)
        print(f"   ✓ Documented: {doc_path}")

        # Update registry
        registry["plugins"][plugin_name] = {
            "documented_at": datetime.now().isoformat(),
            "version": plugin["manifest"].get("version", "unknown"),
            "doc_path": doc_path
        }

    # Save registry
    save_registry(registry)
    print(f"\n✓ Registry updated: {REGISTRY_FILE}")
    print(f"✓ Documentation: {DOCS_DIR}")

if __name__ == "__main__":
    main()
