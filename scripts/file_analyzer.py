#!/usr/bin/env python3
"""
File analyzer - reads multiple files and returns structured summary.
Avoids flooding context with full file contents.

Usage:
    python3 file_analyzer.py '{"files": ["file1.py", "file2.py"], "mode": "summary|functions|imports"}'
"""

import json
import sys
import re
from pathlib import Path


def extract_functions(content: str, ext: str) -> list[dict]:
    """Extract function/method definitions."""
    functions = []

    patterns = {
        ".py": r"^(?:async\s+)?def\s+(\w+)\s*\([^)]*\)",
        ".ts": r"^(?:export\s+)?(?:async\s+)?function\s+(\w+)|(\w+)\s*[=:]\s*(?:async\s+)?\([^)]*\)\s*=>",
        ".js": r"^(?:export\s+)?(?:async\s+)?function\s+(\w+)|(\w+)\s*[=:]\s*(?:async\s+)?\([^)]*\)\s*=>",
        ".go": r"^func\s+(?:\([^)]+\)\s+)?(\w+)",
        ".rs": r"^(?:pub\s+)?(?:async\s+)?fn\s+(\w+)",
    }

    pattern = patterns.get(ext, patterns[".py"])

    for i, line in enumerate(content.split("\n"), 1):
        match = re.match(pattern, line.strip())
        if match:
            name = match.group(1) or (match.group(2) if match.lastindex >= 2 else None)
            if name:
                functions.append({"name": name, "line": i})

    return functions


def extract_imports(content: str, ext: str) -> list[str]:
    """Extract import statements."""
    imports = []

    patterns = {
        ".py": r"^(?:from\s+(\S+)\s+)?import\s+(.+)",
        ".ts": r'^import\s+.*from\s+[\'"]([^\'"]+)[\'"]',
        ".js": r'^import\s+.*from\s+[\'"]([^\'"]+)[\'"]|require\([\'"]([^\'"]+)[\'"]\)',
        ".go": r'^import\s+(?:\(\s*)?["\']([^"\']+)["\']',
        ".rs": r"^use\s+([^;]+)",
    }

    pattern = patterns.get(ext, patterns[".py"])

    for line in content.split("\n"):
        match = re.match(pattern, line.strip())
        if match:
            imp = (
                match.group(1) or match.group(2)
                if match.lastindex >= 2
                else match.group(1)
            )
            if imp:
                imports.append(imp)

    return imports[:20]  # Limit


def extract_classes(content: str, ext: str) -> list[dict]:
    """Extract class definitions."""
    classes = []

    patterns = {
        ".py": r"^class\s+(\w+)",
        ".ts": r"^(?:export\s+)?class\s+(\w+)",
        ".js": r"^class\s+(\w+)",
        ".go": r"^type\s+(\w+)\s+struct",
        ".rs": r"^(?:pub\s+)?struct\s+(\w+)",
    }

    pattern = patterns.get(ext, patterns[".py"])

    for i, line in enumerate(content.split("\n"), 1):
        match = re.match(pattern, line.strip())
        if match:
            classes.append({"name": match.group(1), "line": i})

    return classes


def summarize_file(path: str, mode: str = "summary") -> dict:
    """Analyze a single file."""
    p = Path(path)

    if not p.exists():
        return {"path": path, "error": "File not found"}

    try:
        content = p.read_text()
    except Exception as e:
        return {"path": path, "error": str(e)}

    ext = p.suffix
    lines = len(content.split("\n"))

    result = {
        "path": path,
        "lines": lines,
        "size": len(content),
    }

    if mode in ("summary", "functions"):
        result["functions"] = extract_functions(content, ext)

    if mode in ("summary", "imports"):
        result["imports"] = extract_imports(content, ext)

    if mode == "summary":
        result["classes"] = extract_classes(content, ext)

    return result


def format_output(results: list[dict]) -> str:
    """Format results concisely."""
    lines = []

    for r in results:
        if "error" in r:
            lines.append(f"{r['path']}: ERROR - {r['error']}")
            continue

        lines.append(f"\n{r['path']} ({r['lines']} lines)")

        if r.get("classes"):
            lines.append(f"  Classes: {', '.join(c['name'] for c in r['classes'])}")

        if r.get("functions"):
            funcs = r["functions"][:10]
            lines.append(
                f"  Functions ({len(r['functions'])}): {', '.join(f['name'] for f in funcs)}"
            )
            if len(r["functions"]) > 10:
                lines.append(f"    ... and {len(r['functions']) - 10} more")

        if r.get("imports"):
            lines.append(f"  Imports: {', '.join(r['imports'][:5])}")
            if len(r["imports"]) > 5:
                lines.append(f"    ... and {len(r['imports']) - 5} more")

    return "\n".join(lines)


def main():
    if len(sys.argv) < 2:
        print(
            'Usage: file_analyzer.py \'{"files": [...], "mode": "summary|functions|imports"}\''
        )
        sys.exit(1)

    try:
        config = json.loads(sys.argv[1])
    except json.JSONDecodeError:
        print("Error: Invalid JSON input")
        sys.exit(1)

    files = config.get("files", [])
    mode = config.get("mode", "summary")

    results = [summarize_file(f, mode) for f in files]
    print(format_output(results))


if __name__ == "__main__":
    main()
