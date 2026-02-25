#!/usr/bin/env python3
from pathlib import Path
"""
Batch search utility - search multiple patterns efficiently.

Usage:
    python3 batch_search.py pattern1 pattern2 pattern3 [--path /dir]
"""

import sys
import argparse
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from mcp_bridge import native_grep  # noqa: E402

def main():
    parser = argparse.ArgumentParser(description='Batch search multiple patterns')
    parser.add_argument('patterns', nargs='+', help='Patterns to search for')
    parser.add_argument('--path', default='.', help='Directory to search in')
    parser.add_argument('--glob', help='Filter files by glob pattern')
    parser.add_argument('--case-insensitive', '-i', action='store_true', help='Case insensitive')

    args = parser.parse_args()

    results = {}
    for pattern in args.patterns:
        result = native_grep(
            pattern,
            args.path,
            output_mode="files_with_matches",
            case_sensitive=not args.case_insensitive,
            glob=args.glob
        )
        results[pattern] = result.get('files', [])

    # Print summary
    print(f"Searched {len(args.patterns)} patterns in {args.path}")
    print()
    for pattern, files in results.items():
        print(f"{pattern}: {len(files)} files")
        for f in files[:5]:  # Show first 5
            print(f"  - {f}")
        if len(files) > 5:
            print(f"  ... and {len(files) - 5} more")

if __name__ == '__main__':
    main()
