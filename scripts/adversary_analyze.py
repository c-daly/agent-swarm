#!/usr/bin/env python3
"""
Adversary coverage analysis helper.

Collects coverage data and formats it for Greptile queries.

Usage:
    python3 adversary_analyze.py --scope commit
    python3 adversary_analyze.py --scope pr --base main
    python3 adversary_analyze.py --scope codebase
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Optional


def get_changed_files(scope: str, base_branch: str = "main") -> list[str]:
    """Get list of changed files based on scope."""
    try:
        if scope == "commit":
            result = subprocess.run(
                ["git", "diff", "--name-only", "HEAD~1"],
                capture_output=True, text=True, check=True
            )
        elif scope == "pr":
            # Get merge base
            merge_base = subprocess.run(
                ["git", "merge-base", "HEAD", base_branch],
                capture_output=True, text=True, check=True
            ).stdout.strip()
            result = subprocess.run(
                ["git", "diff", "--name-only", f"{merge_base}..HEAD"],
                capture_output=True, text=True, check=True
            )
        elif scope == "codebase":
            # Return empty list - will analyze all covered files
            return []
        else:
            raise ValueError(f"Unknown scope: {scope}")
        
        files = [f for f in result.stdout.strip().split("\n") if f]
        # Filter to Python files only
        return [f for f in files if f.endswith(".py")]
    except subprocess.CalledProcessError as e:
        print(f"Error getting changed files: {e}", file=sys.stderr)
        return []


def run_coverage(source_dirs: Optional[list[str]] = None) -> dict:
    """Run pytest with coverage and return JSON report."""
    cmd = ["pytest", "--cov", "--cov-report=json", "-q"]
    
    if source_dirs:
        for src in source_dirs:
            cmd.extend(["--cov", src])
    
    try:
        subprocess.run(cmd, capture_output=True, text=True, check=False)
        
        # Read coverage.json
        cov_file = Path("coverage.json")
        if cov_file.exists():
            return json.loads(cov_file.read_text())
        else:
            return {"error": "coverage.json not found"}
    except Exception as e:
        return {"error": str(e)}


def parse_coverage(cov_data: dict, files: Optional[list[str]] = None) -> dict:
    """Parse coverage data and extract relevant metrics."""
    if "error" in cov_data:
        return cov_data
    
    totals = cov_data.get("totals", {})
    file_data = cov_data.get("files", {})
    
    result = {
        "overall_coverage": totals.get("percent_covered", 0),
        "total_statements": totals.get("num_statements", 0),
        "covered_statements": totals.get("covered_lines", 0),
        "missing_statements": totals.get("missing_lines", 0),
        "files": {}
    }
    
    # Filter to specific files if provided
    target_files = files if files else list(file_data.keys())
    
    for filepath in target_files:
        if filepath in file_data:
            fdata = file_data[filepath]
            result["files"][filepath] = {
                "coverage": fdata.get("summary", {}).get("percent_covered", 0),
                "missing_lines": fdata.get("missing_lines", []),
                "excluded_lines": fdata.get("excluded_lines", []),
            }
    
    # Calculate scope-specific coverage
    if files:
        scope_covered = 0
        scope_total = 0
        for filepath in files:
            if filepath in file_data:
                fdata = file_data[filepath]
                scope_covered += fdata.get("summary", {}).get("covered_lines", 0)
                scope_total += fdata.get("summary", {}).get("num_statements", 0)
        
        result["scope_coverage"] = (scope_covered / scope_total * 100) if scope_total > 0 else 0
    
    return result


def format_for_greptile(coverage: dict, scope: str, files: list[str]) -> str:
    """Format coverage data as a Greptile query."""
    if "error" in coverage:
        return f"Error collecting coverage: {coverage['error']}"
    
    overall = coverage.get("overall_coverage", 0)
    scope_cov = coverage.get("scope_coverage", overall)
    
    lines = [
        f"Review the tests for the following {scope} scope.",
        "",
        f"Overall coverage: {overall:.1f}%",
        f"Scope coverage: {scope_cov:.1f}%",
        "",
        "Files in scope:",
    ]
    
    for filepath in files[:20]:  # Limit to 20 files
        if filepath in coverage.get("files", {}):
            fdata = coverage["files"][filepath]
            missing = fdata.get("missing_lines", [])
            lines.append(f"  - {filepath}: {fdata['coverage']:.1f}% (missing lines: {missing[:10]})")
        else:
            lines.append(f"  - {filepath}: no coverage data")
    
    lines.extend([
        "",
        "Should passing tests give confidence this code is strong?",
        "What important code paths aren't being tested?",
        "What edge cases or error conditions are missing tests?",
    ])
    
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Adversary coverage analysis")
    parser.add_argument("--scope", choices=["commit", "pr", "codebase"], default="commit",
                       help="Scope of analysis")
    parser.add_argument("--base", default="main", help="Base branch for PR scope")
    parser.add_argument("--json", action="store_true", help="Output raw JSON")
    parser.add_argument("--greptile", action="store_true", help="Format for Greptile query")
    parser.add_argument("--run-coverage", action="store_true", help="Run pytest --cov first")
    
    args = parser.parse_args()
    
    # Get changed files
    files = get_changed_files(args.scope, args.base)
    
    if args.scope != "codebase" and not files:
        print(f"No Python files changed in {args.scope} scope", file=sys.stderr)
        sys.exit(1)
    
    # Run coverage if requested
    if args.run_coverage:
        cov_data = run_coverage()
    else:
        # Read existing coverage.json
        cov_file = Path("coverage.json")
        if cov_file.exists():
            cov_data = json.loads(cov_file.read_text())
        else:
            print("No coverage.json found. Run with --run-coverage", file=sys.stderr)
            sys.exit(1)
    
    # Parse coverage
    coverage = parse_coverage(cov_data, files if files else None)
    
    # Output
    if args.json:
        print(json.dumps(coverage, indent=2))
    elif args.greptile:
        print(format_for_greptile(coverage, args.scope, files))
    else:
        # Human readable summary
        print(f"Scope: {args.scope}")
        print(f"Files: {len(files)}")
        print(f"Overall coverage: {coverage.get('overall_coverage', 0):.1f}%")
        if "scope_coverage" in coverage:
            print(f"Scope coverage: {coverage['scope_coverage']:.1f}%")
        print()
        for filepath, fdata in list(coverage.get("files", {}).items())[:10]:
            missing = fdata.get("missing_lines", [])
            print(f"  {filepath}: {fdata['coverage']:.1f}% ({len(missing)} lines missing)")


if __name__ == "__main__":
    main()
