# lib/test_audit/coverage_based.py
"""Coverage-based redundancy detection using actual pytest coverage data."""
import sqlite3
import subprocess
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Set, Tuple


@dataclass
class CoverageAnalysis:
    """Results of coverage-based redundancy analysis."""
    total_tests: int
    total_lines: int
    minimum_set: Set[str]
    truly_redundant: Set[str]
    adds_unique_coverage: Set[str]
    test_coverage: Dict[str, Set[Tuple[str, int]]]


def collect_per_test_coverage(
    test_path: str = "tests/",
    source_path: str = "lib",
    project_root: Path | None = None,
) -> Dict[str, Set[Tuple[str, int]]]:
    """Run pytest with per-test coverage and return coverage per test.

    Args:
        test_path: Path to test directory
        source_path: Path to source code to measure coverage
        project_root: Project root directory (defaults to parent of lib/)

    Returns:
        Dict mapping test name -> set of (file, line_number) tuples covered
    """
    if project_root is None:
        project_root = Path(__file__).parent.parent.parent

    # Run pytest with coverage context tracking
    # Note: We intentionally don't use check=True because we want coverage data
    # even if some tests fail - failed tests still produce coverage information
    print("Running pytest with per-test coverage tracking...")
    result = subprocess.run(
        [
            "python", "-m", "pytest", test_path,
            f"--cov={source_path}",
            "--cov-context=test",
            "--cov-report=",  # Suppress report, we'll read the db
            "-q", "--tb=no",
        ],
        capture_output=True,
        text=True,
        cwd=project_root,
        timeout=600,
    )

    if result.returncode != 0:
        # Extract summary line from pytest output (e.g., "5 failed, 10 passed")
        summary = ""
        for line in result.stdout.splitlines()[-5:]:
            if "passed" in line or "failed" in line:
                summary = line.strip()
                break
        print(f"Warning: pytest exited with code {result.returncode}")
        if summary:
            print(f"  {summary}")
        print("  Continuing with coverage analysis of executed tests...")

    return _parse_coverage_database(project_root / ".coverage")


def _parse_coverage_database(
    coverage_db: Path,
) -> Dict[str, Set[Tuple[str, int]]]:
    """Parse .coverage SQLite database to extract per-test coverage."""
    if not coverage_db.exists():
        raise FileNotFoundError(
            f"Coverage database not found at {coverage_db}. "
            "Run pytest with --cov first."
        )

    conn = sqlite3.connect(str(coverage_db))
    cursor = conn.cursor()

    # Get contexts (test names) - exclude empty context
    cursor.execute("SELECT id, context FROM context WHERE context != ''")
    contexts = {row[0]: row[1] for row in cursor.fetchall()}

    # Get file mappings
    cursor.execute("SELECT id, path FROM file")
    files = {row[0]: row[1] for row in cursor.fetchall()}

    # Build coverage per test from line_bits table
    test_coverage: Dict[str, Set[Tuple[str, int]]] = defaultdict(set)

    cursor.execute("""
        SELECT context_id, file_id, numbits FROM line_bits
        WHERE context_id IN (SELECT id FROM context WHERE context != '')
    """)

    for context_id, file_id, numbits in cursor.fetchall():
        if context_id not in contexts:
            continue

        context = contexts[context_id]
        test_name = _parse_test_name(context)
        if not test_name:
            continue

        file_path = files.get(file_id, "unknown")

        # Decode numbits blob to line numbers
        for line_no in _decode_numbits(numbits):
            test_coverage[test_name].add((file_path, line_no))

    conn.close()
    return dict(test_coverage)


def _parse_test_name(context: str) -> str | None:
    """Extract full test identifier from coverage context string.

    Context format examples:
    - "test_file.py::TestClass::test_method|run"
    - "test_file.py::test_function|run"

    Returns full path (file::class::test) to avoid name collisions.
    """
    if "|" in context:
        context = context.split("|")[0]
    if "::" in context:
        return context  # Return full identifier, not just test name
    return None


def _decode_numbits(numbits: bytes) -> Set[int]:
    """Decode coverage.py's numbits blob to set of line numbers.

    The numbits format is a bitmap where each bit represents a line.
    Byte 0, bit 0 = line 0; byte 0, bit 7 = line 7; byte 1, bit 0 = line 8, etc.
    """
    lines = set()
    for byte_idx, byte in enumerate(numbits):
        for bit_idx in range(8):
            if byte & (1 << bit_idx):
                lines.add(byte_idx * 8 + bit_idx)
    return lines


def find_minimum_covering_set(
    coverage: Dict[str, Set[Tuple[str, int]]],
) -> Set[str]:
    """Find minimum set of tests that covers all lines.

    Uses greedy set cover algorithm: repeatedly pick the test that
    covers the most uncovered lines until all lines are covered.
    """
    # Collect all unique lines
    all_lines: Set[Tuple[str, int]] = set()
    for lines in coverage.values():
        all_lines |= lines

    selected: Set[str] = set()
    uncovered = all_lines.copy()

    while uncovered:
        best_test = None
        best_count = 0

        for test_name, lines in coverage.items():
            if test_name in selected:
                continue
            count = len(lines & uncovered)
            if count > best_count:
                best_count = count
                best_test = test_name

        if best_test is None or best_count == 0:
            break

        selected.add(best_test)
        uncovered -= coverage[best_test]

    return selected


def find_truly_redundant_tests(
    coverage: Dict[str, Set[Tuple[str, int]]],
    minimum_set: Set[str],
) -> Tuple[Set[str], Set[str]]:
    """Classify tests not in minimum set by whether they add unique coverage.

    Args:
        coverage: Per-test coverage data
        minimum_set: Tests selected by minimum covering set algorithm

    Returns:
        Tuple of (truly_redundant, adds_unique_coverage) test sets
    """
    # Calculate lines covered by minimum set
    minimum_coverage: Set[Tuple[str, int]] = set()
    for test_name in minimum_set:
        if test_name in coverage:
            minimum_coverage |= coverage[test_name]

    truly_redundant: Set[str] = set()
    adds_unique: Set[str] = set()

    for test_name, lines in coverage.items():
        if test_name in minimum_set:
            continue

        # Check if this test adds any lines not covered by minimum set
        unique_lines = lines - minimum_coverage
        if unique_lines:
            adds_unique.add(test_name)
        else:
            truly_redundant.add(test_name)

    return truly_redundant, adds_unique


def analyze_test_redundancy(
    test_path: str = "tests/",
    source_path: str = "lib",
    project_root: Path | None = None,
) -> CoverageAnalysis:
    """Main analysis: find truly redundant tests using actual coverage data.

    Args:
        test_path: Path to test directory
        source_path: Path to source code
        project_root: Project root directory

    Returns:
        CoverageAnalysis with results
    """
    # Collect per-test coverage
    coverage = collect_per_test_coverage(test_path, source_path, project_root)
    print(f"Collected coverage for {len(coverage)} tests")

    # Calculate total lines
    all_lines: Set[Tuple[str, int]] = set()
    for lines in coverage.values():
        all_lines |= lines
    print(f"Total unique lines covered: {len(all_lines)}")

    # Find minimum covering set
    minimum_set = find_minimum_covering_set(coverage)
    print(f"Minimum covering set: {len(minimum_set)} tests")

    # Classify remaining tests
    truly_redundant, adds_unique = find_truly_redundant_tests(coverage, minimum_set)
    print(f"Truly redundant (0 unique lines): {len(truly_redundant)}")
    print(f"Add unique coverage: {len(adds_unique)}")

    return CoverageAnalysis(
        total_tests=len(coverage),
        total_lines=len(all_lines),
        minimum_set=minimum_set,
        truly_redundant=truly_redundant,
        adds_unique_coverage=adds_unique,
        test_coverage=coverage,
    )


def compare_with_static_analysis(
    coverage_analysis: CoverageAnalysis,
    static_deletes: Set[str],
) -> dict:
    """Compare coverage-based results with static analysis results.

    Args:
        coverage_analysis: Results from coverage-based analysis
        static_deletes: Tests flagged for deletion by static analysis

    Returns:
        Dict with comparison metrics
    """
    # Tests static analysis wants to delete that actually add coverage
    false_positives = static_deletes & coverage_analysis.adds_unique_coverage

    # Tests static analysis wants to delete that are truly redundant
    true_positives = static_deletes & coverage_analysis.truly_redundant

    # Tests in minimum set that static analysis wants to delete
    critical_errors = static_deletes & coverage_analysis.minimum_set

    return {
        "static_delete_count": len(static_deletes),
        "truly_redundant_count": len(coverage_analysis.truly_redundant),
        "false_positives": len(false_positives),
        "true_positives": len(true_positives),
        "critical_errors": len(critical_errors),
        "false_positive_tests": sorted(false_positives)[:20],  # Sample
        "critical_error_tests": sorted(critical_errors)[:20],  # Sample
    }


if __name__ == "__main__":
    results = analyze_test_redundancy()

    print("\n" + "=" * 60)
    print("COVERAGE-BASED REDUNDANCY ANALYSIS")
    print("=" * 60)
    print(f"Total tests analyzed: {results.total_tests}")
    print(f"Total lines covered: {results.total_lines}")
    print(f"Minimum set needed: {len(results.minimum_set)}")
    print(f"Truly redundant: {len(results.truly_redundant)}")
    print(f"Add unique coverage: {len(results.adds_unique_coverage)}")

    print("\n" + "=" * 60)
    print("COMPARISON WITH STATIC ANALYSIS (~1242 flagged)")
    print("=" * 60)
    print(f"Coverage-based truly redundant: {len(results.truly_redundant)}")
    print(f"Difference: ~{1242 - len(results.truly_redundant)} tests incorrectly flagged")
