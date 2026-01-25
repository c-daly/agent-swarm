# lib/test_audit/cli.py
"""Command-line interface for test audit."""
import argparse
from pathlib import Path

from lib.test_audit.decision_engine import process_decisions
from lib.test_audit.optimizer import find_minimum_covering_set, map_test_coverage
from lib.test_audit.test_parser import parse_test_file


def main():
    """Run the test audit CLI."""
    parser = argparse.ArgumentParser(description="Audit test files for quality")
    parser.add_argument("--path", type=Path, required=True, help="Path to test directory")
    parser.add_argument(
        "--confidence",
        type=float,
        default=0.75,
        help="Confidence threshold for automatic decisions",
    )
    args = parser.parse_args()

    # Find and parse all test files
    test_files = list(args.path.glob("**/test_*.py"))
    all_tests = []

    for test_file in test_files:
        code = test_file.read_text()
        tests = parse_test_file(code, str(test_file))
        all_tests.extend(tests)

    if not all_tests:
        print("No tests found.")
        return

    # Calculate coverage and minimum set
    coverage = map_test_coverage(all_tests)
    all_functions = set()
    for targets in coverage.values():
        all_functions |= targets

    minimum_set = find_minimum_covering_set(coverage, all_functions)

    # Process decisions
    result = process_decisions(all_tests, minimum_set, args.confidence)

    # Output summary
    print("\nTest Audit Summary")
    print("==================")
    print(f"Total tests: {len(all_tests)}")
    print(f"Functions covered: {len(all_functions)}")
    print()
    print(f"KEEP ({len(result.keeps)}):")
    for name in sorted(result.keeps):
        score = result.scores[name]
        print(f"  {name} - {score.reason}")

    print(f"\nDELETE ({len(result.deletes)}):")
    for name in sorted(result.deletes):
        score = result.scores[name]
        print(f"  {name} - {score.reason}")

    print(f"\nREVIEW ({len(result.needs_review)}):")
    for name in sorted(result.needs_review):
        score = result.scores[name]
        print(f"  {name} - {score.reason}")


if __name__ == "__main__":
    main()
