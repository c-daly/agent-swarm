# lib/test_audit/cli.py
"""Command-line interface for test audit."""
import argparse
from pathlib import Path
from typing import Dict, Optional

from lib.test_audit.decision_engine import (
    CoverageInfo,
    DecisionResult,
    delete_tests_from_file,
    process_decisions,
)
from lib.test_audit.optimizer import find_minimum_covering_set, map_test_coverage
from lib.test_audit.test_parser import parse_test_file


def _build_coverage_data(
    test_path: str, source_path: str, project_root: Path
) -> Optional[Dict[str, CoverageInfo]]:
    """Build coverage info dict from actual pytest coverage data.

    Returns:
        Dict mapping test_name -> CoverageInfo, or None if collection fails
    """
    try:
        from lib.test_audit.coverage_based import (
            collect_per_test_coverage,
            find_minimum_covering_set as find_min_set_by_lines,
        )
    except ImportError:
        print("Warning: coverage_based module not available")
        return None

    try:
        # Collect per-test coverage
        coverage = collect_per_test_coverage(test_path, source_path, project_root)
        if not coverage:
            return None

        # Find minimum set by actual line coverage
        minimum_set = find_min_set_by_lines(coverage)

        # Calculate lines covered by minimum set
        min_set_lines = set()
        for test_name in minimum_set:
            min_set_lines |= coverage.get(test_name, set())

        # Build CoverageInfo for each test
        result: Dict[str, CoverageInfo] = {}
        for test_id, lines in coverage.items():
            # Extract just the test function name for matching
            test_name = test_id.split("::")[-1] if "::" in test_id else test_id
            unique_lines = lines - min_set_lines

            result[test_name] = CoverageInfo(
                is_in_minimum_set=test_id in minimum_set,
                is_truly_redundant=len(unique_lines) == 0 and test_id not in minimum_set,
                unique_lines=len(unique_lines),
            )

        return result

    except Exception as e:
        print(f"Warning: Failed to collect coverage data: {e}")
        return None


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
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="Interactively review tests flagged for review",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually delete tests marked for deletion",
    )
    parser.add_argument(
        "--coverage",
        action="store_true",
        help="Use actual pytest coverage data (more accurate, slower)",
    )
    parser.add_argument(
        "--source",
        type=str,
        default="lib",
        help="Source directory for coverage measurement (default: lib)",
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

    # Calculate coverage and minimum set (static analysis)
    coverage = map_test_coverage(all_tests)
    all_functions = set()
    for targets in coverage.values():
        all_functions |= targets

    minimum_set = find_minimum_covering_set(coverage, all_functions)

    # Optionally collect actual coverage data
    coverage_data = None
    if args.coverage:
        print("Collecting actual coverage data (this may take a while)...")
        project_root = args.path.parent if args.path.name == "tests" else args.path
        coverage_data = _build_coverage_data(str(args.path), args.source, project_root)
        if coverage_data:
            print(f"Collected coverage data for {len(coverage_data)} tests")
        else:
            print("Falling back to static analysis")

    # Process decisions
    result = process_decisions(all_tests, minimum_set, args.confidence, coverage_data)

    # Output summary
    print("\nTest Audit Summary")
    print("==================")
    mode = "coverage-based" if coverage_data else "static analysis"
    print(f"Analysis mode: {mode}")
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

    # Interactive review if requested
    if args.interactive and result.needs_review:
        print("\n--- Interactive Review ---")
        result = interactive_review(result)

    # Execute deletions if requested
    if args.execute and result.deletes:
        print("\n--- Executing Deletions ---")
        # Group tests by file
        tests_by_file: dict[Path, set[str]] = {}
        for test in all_tests:
            if test.name in result.deletes:
                file_path = Path(test.file_path)
                if file_path not in tests_by_file:
                    tests_by_file[file_path] = set()
                tests_by_file[file_path].add(test.name)

        for file_path, tests_to_delete in tests_by_file.items():
            code = file_path.read_text()
            new_code = delete_tests_from_file(code, tests_to_delete)
            file_path.write_text(new_code)
            print(f"  Deleted {len(tests_to_delete)} test(s) from {file_path}")


def interactive_review(result: DecisionResult) -> DecisionResult:
    """Interactively review tests marked for review.

    Args:
        result: DecisionResult with needs_review set

    Returns:
        Updated DecisionResult with user decisions applied
    """
    for name in list(result.needs_review):
        score = result.scores[name]
        print(f"\n{name}")
        print(f"  Reason: {score.reason}")
        print(f"  Confidence: {score.confidence:.0%}")

        choice = input("  [k]eep / [d]elete / [s]kip: ").strip().lower()

        if choice == "k":
            result.keeps.add(name)
            result.needs_review.remove(name)
        elif choice == "d":
            result.deletes.add(name)
            result.needs_review.remove(name)
        # 's' or anything else = skip (leave in needs_review)

    return result


if __name__ == "__main__":
    main()
