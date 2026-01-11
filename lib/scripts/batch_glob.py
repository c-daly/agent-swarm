#!/usr/bin/env python3
from pathlib import Path
"""
Batch glob utility - find files matching multiple patterns.

Usage:
    python3 batch_glob.py '*.py' '*.md' '*.json' [--path /dir]
"""

import sys
import argparse
sys.path.insert(0, str(Path(__file__).parent.parent))  # Add lib/ to path
from mcp_bridge import native_glob

def main():
    parser = argparse.ArgumentParser(description='Batch glob multiple patterns')
    parser.add_argument('patterns', nargs='+', help='Glob patterns')
    parser.add_argument('--path', default='.', help='Directory to search in')
    parser.add_argument('--count-only', action='store_true', help='Only show counts')

    args = parser.parse_args()

    all_files = set()
    results = {}

    for pattern in args.patterns:
        files = native_glob(pattern, args.path)
        results[pattern] = files
        all_files.update(files)

    # Print summary
    if args.count_only:
        for pattern, files in results.items():
            print(f"{pattern}: {len(files)} files")
        print(f"\nTotal unique files: {len(all_files)}")
    else:
        print(f"Found {len(all_files)} unique files matching {len(args.patterns)} patterns")
        print()
        for pattern, files in results.items():
            print(f"\n{pattern} ({len(files)} files):")
            for f in files[:10]:
                print(f"  - {f}")
            if len(files) > 10:
                print(f"  ... and {len(files) - 10} more")

if __name__ == '__main__':
    main()
