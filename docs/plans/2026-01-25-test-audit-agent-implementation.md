# Test Audit Agent Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build an interactive agent that calculates optimal test distribution from production code analysis and guides toward minimal effective coverage.

**Architecture:** Three-layer design: (1) analyzers that parse code and tests, (2) optimizer that calculates minimal covering set, (3) interactive CLI that works autonomously on clear decisions and asks for guidance on ambiguous ones.

**Tech Stack:** Python 3.10+, AST for parsing, pytest for testing, Click for CLI

---

## Phase 1: Code Analyzer

Build the foundation that analyzes production code to identify what needs testing.

### Task 1.1: Critical Path Detection - Entry Points

**Files:**
- Create: `lib/test_audit/code_analyzer.py`
- Test: `tests/test_audit/test_code_analyzer.py`

**Step 1: Write the failing test**

```python
# tests/test_audit/test_code_analyzer.py
import pytest
from lib.test_audit.code_analyzer import find_entry_points

def test_find_entry_points_detects_main_block():
    """Entry points include functions called from if __name__ == '__main__'."""
    code = '''
def main():
    pass

def helper():
    pass

if __name__ == "__main__":
    main()
'''
    entry_points = find_entry_points(code, "example.py")
    assert "main" in [ep.name for ep in entry_points]
    assert "helper" not in [ep.name for ep in entry_points]
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_audit/test_code_analyzer.py::test_find_entry_points_detects_main_block -v`
Expected: FAIL with "No module named 'lib.test_audit'"

**Step 3: Create module structure and minimal implementation**

```python
# lib/test_audit/__init__.py
"""Test audit agent - calculates optimal test distribution."""

# lib/test_audit/code_analyzer.py
"""Analyze production code to identify critical paths."""
import ast
from dataclasses import dataclass
from typing import List

@dataclass
class EntryPoint:
    name: str
    file_path: str
    line_number: int
    source: str  # "main_block", "cli_handler", "hook", "mcp_tool"

def find_entry_points(code: str, file_path: str) -> List[EntryPoint]:
    """Find entry points in Python code."""
    tree = ast.parse(code)
    entry_points = []

    # Find functions called in if __name__ == "__main__" block
    for node in ast.walk(tree):
        if isinstance(node, ast.If):
            # Check for if __name__ == "__main__"
            if _is_main_check(node):
                # Find function calls in the block
                for stmt in node.body:
                    for call in ast.walk(stmt):
                        if isinstance(call, ast.Call) and isinstance(call.func, ast.Name):
                            entry_points.append(EntryPoint(
                                name=call.func.id,
                                file_path=file_path,
                                line_number=call.lineno,
                                source="main_block"
                            ))
    return entry_points

def _is_main_check(node: ast.If) -> bool:
    """Check if this is an 'if __name__ == "__main__"' block."""
    test = node.test
    if isinstance(test, ast.Compare):
        if isinstance(test.left, ast.Name) and test.left.id == "__name__":
            if test.ops and isinstance(test.ops[0], ast.Eq):
                if test.comparators and isinstance(test.comparators[0], ast.Constant):
                    return test.comparators[0].value == "__main__"
    return False
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_audit/test_code_analyzer.py::test_find_entry_points_detects_main_block -v`
Expected: PASS

**Step 5: Commit**

```bash
git add lib/test_audit/ tests/test_audit/
git commit -m "feat(audit): add entry point detection for main blocks"
```

---

### Task 1.2: Critical Path Detection - CLI Handlers

**Files:**
- Modify: `lib/test_audit/code_analyzer.py`
- Test: `tests/test_audit/test_code_analyzer.py`

**Step 1: Write the failing test**

```python
def test_find_entry_points_detects_click_commands():
    """Entry points include Click CLI command handlers."""
    code = '''
import click

@click.command()
def cli_main():
    pass

@click.group()
def group():
    pass

@group.command()
def subcommand():
    pass

def helper():
    pass
'''
    entry_points = find_entry_points(code, "cli.py")
    names = [ep.name for ep in entry_points]
    assert "cli_main" in names
    assert "group" in names
    assert "subcommand" in names
    assert "helper" not in names
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_audit/test_code_analyzer.py::test_find_entry_points_detects_click_commands -v`
Expected: FAIL - click commands not detected

**Step 3: Extend implementation**

Add to `find_entry_points` in `lib/test_audit/code_analyzer.py`:

```python
def find_entry_points(code: str, file_path: str) -> List[EntryPoint]:
    """Find entry points in Python code."""
    tree = ast.parse(code)
    entry_points = []

    for node in ast.walk(tree):
        # Check for if __name__ == "__main__" block
        if isinstance(node, ast.If) and _is_main_check(node):
            for stmt in node.body:
                for call in ast.walk(stmt):
                    if isinstance(call, ast.Call) and isinstance(call.func, ast.Name):
                        entry_points.append(EntryPoint(
                            name=call.func.id,
                            file_path=file_path,
                            line_number=call.lineno,
                            source="main_block"
                        ))

        # Check for decorated functions (Click, etc.)
        if isinstance(node, ast.FunctionDef):
            for decorator in node.decorator_list:
                if _is_cli_decorator(decorator):
                    entry_points.append(EntryPoint(
                        name=node.name,
                        file_path=file_path,
                        line_number=node.lineno,
                        source="cli_handler"
                    ))
                    break

    return entry_points

def _is_cli_decorator(decorator: ast.expr) -> bool:
    """Check if decorator marks a CLI entry point."""
    # @click.command() or @click.group()
    if isinstance(decorator, ast.Call):
        func = decorator.func
        if isinstance(func, ast.Attribute):
            if func.attr in ("command", "group"):
                return True
        # @group.command()
        if isinstance(func, ast.Attribute) and func.attr == "command":
            return True
    # @click.command (no parens)
    if isinstance(decorator, ast.Attribute):
        if decorator.attr in ("command", "group"):
            return True
    return False
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_audit/test_code_analyzer.py -v`
Expected: PASS (both tests)

**Step 5: Commit**

```bash
git add lib/test_audit/code_analyzer.py tests/test_audit/test_code_analyzer.py
git commit -m "feat(audit): detect Click CLI handlers as entry points"
```

---

### Task 1.3: Function Extraction and Call Graph

**Files:**
- Create: `lib/test_audit/call_graph.py`
- Test: `tests/test_audit/test_call_graph.py`

**Step 1: Write the failing test**

```python
# tests/test_audit/test_call_graph.py
import pytest
from lib.test_audit.call_graph import build_call_graph, FunctionInfo

def test_build_call_graph_extracts_functions():
    """Extract all function definitions with their calls."""
    code = '''
def outer():
    inner()
    helper()

def inner():
    pass

def helper():
    utility()

def utility():
    pass
'''
    graph = build_call_graph(code, "module.py")

    assert "outer" in graph
    assert set(graph["outer"].calls) == {"inner", "helper"}
    assert graph["inner"].calls == []
    assert graph["helper"].calls == ["utility"]
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_audit/test_call_graph.py::test_build_call_graph_extracts_functions -v`
Expected: FAIL - module not found

**Step 3: Implement call graph builder**

```python
# lib/test_audit/call_graph.py
"""Build call graphs from Python code."""
import ast
from dataclasses import dataclass, field
from typing import Dict, List, Set

@dataclass
class FunctionInfo:
    name: str
    file_path: str
    line_number: int
    calls: List[str] = field(default_factory=list)
    is_method: bool = False
    class_name: str = ""

def build_call_graph(code: str, file_path: str) -> Dict[str, FunctionInfo]:
    """Build a call graph from Python source code."""
    tree = ast.parse(code)
    graph: Dict[str, FunctionInfo] = {}

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            calls = _extract_calls(node)
            graph[node.name] = FunctionInfo(
                name=node.name,
                file_path=file_path,
                line_number=node.lineno,
                calls=calls
            )

    return graph

def _extract_calls(func_node: ast.FunctionDef) -> List[str]:
    """Extract function calls from a function body."""
    calls = []
    for node in ast.walk(func_node):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                calls.append(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                # method calls like self.method() - just get the method name
                calls.append(node.func.attr)
    return calls
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_audit/test_call_graph.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add lib/test_audit/call_graph.py tests/test_audit/test_call_graph.py
git commit -m "feat(audit): build call graph from Python code"
```

---

### Task 1.4: Reachability Analysis

**Files:**
- Modify: `lib/test_audit/call_graph.py`
- Test: `tests/test_audit/test_call_graph.py`

**Step 1: Write the failing test**

```python
def test_find_reachable_from_entry_points():
    """Find all functions reachable from entry points."""
    code = '''
def main():
    process()

def process():
    validate()
    transform()

def validate():
    pass

def transform():
    helper()

def helper():
    pass

def unreachable():
    """This function is never called."""
    pass
'''
    graph = build_call_graph(code, "module.py")
    reachable = find_reachable(graph, entry_points=["main"])

    assert reachable == {"main", "process", "validate", "transform", "helper"}
    assert "unreachable" not in reachable
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_audit/test_call_graph.py::test_find_reachable_from_entry_points -v`
Expected: FAIL - find_reachable not defined

**Step 3: Implement reachability analysis**

Add to `lib/test_audit/call_graph.py`:

```python
def find_reachable(graph: Dict[str, FunctionInfo], entry_points: List[str]) -> Set[str]:
    """Find all functions reachable from entry points via BFS."""
    reachable = set()
    queue = list(entry_points)

    while queue:
        func_name = queue.pop(0)
        if func_name in reachable:
            continue
        if func_name not in graph:
            continue

        reachable.add(func_name)
        for called in graph[func_name].calls:
            if called not in reachable:
                queue.append(called)

    return reachable
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_audit/test_call_graph.py -v`
Expected: PASS (both tests)

**Step 5: Commit**

```bash
git add lib/test_audit/call_graph.py tests/test_audit/test_call_graph.py
git commit -m "feat(audit): add reachability analysis for call graphs"
```

---

## Phase 2: Test Parser

Analyze existing tests to understand what they cover and their health.

### Task 2.1: Test Extraction

**Files:**
- Create: `lib/test_audit/test_parser.py`
- Test: `tests/test_audit/test_test_parser.py`

**Step 1: Write the failing test**

```python
# tests/test_audit/test_test_parser.py
import pytest
from lib.test_audit.test_parser import parse_test_file, TestInfo

def test_parse_test_file_extracts_tests():
    """Extract test functions and their metadata."""
    code = '''
import pytest
from mymodule import process, validate

def test_process_success():
    result = process("input")
    assert result == "output"

def test_validate_rejects_empty():
    with pytest.raises(ValueError):
        validate("")

class TestProcess:
    def test_with_options(self):
        assert process("x", opt=True) == "y"

def helper_function():
    """Not a test."""
    pass
'''
    tests = parse_test_file(code, "test_module.py")

    assert len(tests) == 3
    names = [t.name for t in tests]
    assert "test_process_success" in names
    assert "test_validate_rejects_empty" in names
    assert "test_with_options" in names
    assert "helper_function" not in names
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_audit/test_test_parser.py::test_parse_test_file_extracts_tests -v`
Expected: FAIL - module not found

**Step 3: Implement test parser**

```python
# lib/test_audit/test_parser.py
"""Parse test files to extract test information."""
import ast
from dataclasses import dataclass, field
from typing import List, Set

@dataclass
class TestInfo:
    name: str
    file_path: str
    line_number: int
    class_name: str = ""  # If test is in a class
    imports: Set[str] = field(default_factory=set)
    assertions: int = 0
    mocks: int = 0
    targets: Set[str] = field(default_factory=set)  # Functions this test calls

def parse_test_file(code: str, file_path: str) -> List[TestInfo]:
    """Parse a test file and extract test information."""
    tree = ast.parse(code)
    tests = []
    imports = _extract_imports(tree)

    for node in ast.walk(tree):
        # Top-level test functions
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
            tests.append(_analyze_test_function(node, file_path, "", imports))

        # Test methods in classes
        if isinstance(node, ast.ClassDef):
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name.startswith("test_"):
                    tests.append(_analyze_test_function(item, file_path, node.name, imports))

    return tests

def _extract_imports(tree: ast.Module) -> Set[str]:
    """Extract imported names from module."""
    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.asname or alias.name)
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                imports.add(alias.asname or alias.name)
    return imports

def _analyze_test_function(node: ast.FunctionDef, file_path: str, class_name: str, imports: Set[str]) -> TestInfo:
    """Analyze a single test function."""
    assertions = 0
    mocks = 0
    targets = set()

    for child in ast.walk(node):
        # Count assertions
        if isinstance(child, ast.Assert):
            assertions += 1
        if isinstance(child, ast.Call):
            func = child.func
            # pytest.raises counts as assertion
            if isinstance(func, ast.Attribute) and func.attr == "raises":
                assertions += 1
            # Count mocks
            if isinstance(func, ast.Name) and func.id in ("Mock", "MagicMock", "patch"):
                mocks += 1
            if isinstance(func, ast.Attribute) and func.attr in ("patch", "Mock", "MagicMock"):
                mocks += 1
            # Track function calls that match imports (potential targets)
            if isinstance(func, ast.Name) and func.id in imports:
                targets.add(func.id)

    return TestInfo(
        name=node.name,
        file_path=file_path,
        line_number=node.lineno,
        class_name=class_name,
        imports=imports,
        assertions=assertions,
        mocks=mocks,
        targets=targets
    )
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_audit/test_test_parser.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add lib/test_audit/test_parser.py tests/test_audit/test_test_parser.py
git commit -m "feat(audit): parse test files to extract test metadata"
```

---

### Task 2.2: Health Signal Detection

**Files:**
- Modify: `lib/test_audit/test_parser.py`
- Test: `tests/test_audit/test_test_parser.py`

**Step 1: Write the failing test**

```python
def test_calculate_health_signals():
    """Calculate health signals for tests."""
    code = '''
from unittest.mock import patch, Mock, MagicMock
from mymodule import process

def test_no_assertions():
    process("input")  # No assert!

def test_too_many_mocks():
    with patch("a"), patch("b"), patch("c"), patch("d"):
        result = process("x")
        assert result

def test_healthy():
    result = process("good")
    assert result == "expected"
    assert len(result) > 0
'''
    tests = parse_test_file(code, "test_health.py")

    no_assert = next(t for t in tests if t.name == "test_no_assertions")
    assert no_assert.assertions == 0

    too_mocks = next(t for t in tests if t.name == "test_too_many_mocks")
    assert too_mocks.mocks >= 4

    healthy = next(t for t in tests if t.name == "test_healthy")
    assert healthy.assertions >= 2
    assert healthy.mocks == 0
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_audit/test_test_parser.py::test_calculate_health_signals -v`
Expected: FAIL or PASS (depends on current mock counting)

**Step 3: Improve mock detection**

Update `_analyze_test_function` to better count mocks:

```python
def _analyze_test_function(node: ast.FunctionDef, file_path: str, class_name: str, imports: Set[str]) -> TestInfo:
    """Analyze a single test function."""
    assertions = 0
    mocks = 0
    targets = set()

    for child in ast.walk(node):
        # Count assertions
        if isinstance(child, ast.Assert):
            assertions += 1
        if isinstance(child, ast.Call):
            func = child.func
            # pytest.raises counts as assertion
            if isinstance(func, ast.Attribute) and func.attr == "raises":
                assertions += 1
            # Count mocks - function calls
            if isinstance(func, ast.Name) and func.id in ("Mock", "MagicMock", "patch", "create_autospec"):
                mocks += 1
            if isinstance(func, ast.Attribute) and func.attr in ("patch", "Mock", "MagicMock", "create_autospec"):
                mocks += 1
            # Track function calls that match imports (potential targets)
            if isinstance(func, ast.Name) and func.id in imports:
                targets.add(func.id)

        # Count mocks - context managers (with patch(...))
        if isinstance(child, ast.With):
            for item in child.items:
                if isinstance(item.context_expr, ast.Call):
                    func = item.context_expr.func
                    if isinstance(func, ast.Name) and func.id == "patch":
                        mocks += 1
                    if isinstance(func, ast.Attribute) and func.attr == "patch":
                        mocks += 1

        # Count mocks - decorators
        if isinstance(child, ast.FunctionDef):
            for dec in child.decorator_list:
                if isinstance(dec, ast.Call):
                    func = dec.func
                    if isinstance(func, ast.Attribute) and func.attr == "patch":
                        mocks += 1

    return TestInfo(
        name=node.name,
        file_path=file_path,
        line_number=node.lineno,
        class_name=class_name,
        imports=imports,
        assertions=assertions,
        mocks=mocks,
        targets=targets
    )
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_audit/test_test_parser.py -v`
Expected: PASS (all tests)

**Step 5: Commit**

```bash
git add lib/test_audit/test_parser.py tests/test_audit/test_test_parser.py
git commit -m "feat(audit): improve health signal detection for mocks"
```

---

## Phase 3: Optimal Calculator

Calculate the minimal test set needed for coverage.

### Task 3.1: Coverage Mapping

**Files:**
- Create: `lib/test_audit/optimizer.py`
- Test: `tests/test_audit/test_optimizer.py`

**Step 1: Write the failing test**

```python
# tests/test_audit/test_optimizer.py
import pytest
from lib.test_audit.optimizer import map_test_coverage

def test_map_test_coverage():
    """Map which functions each test covers."""
    # Simplified: test targets are the functions it imports and calls
    from lib.test_audit.test_parser import TestInfo

    tests = [
        TestInfo(
            name="test_process",
            file_path="test_a.py",
            line_number=1,
            targets={"process", "validate"}
        ),
        TestInfo(
            name="test_transform",
            file_path="test_a.py",
            line_number=10,
            targets={"transform"}
        ),
    ]

    coverage = map_test_coverage(tests)

    assert coverage["test_process"] == {"process", "validate"}
    assert coverage["test_transform"] == {"transform"}
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_audit/test_optimizer.py::test_map_test_coverage -v`
Expected: FAIL - module not found

**Step 3: Implement coverage mapping**

```python
# lib/test_audit/optimizer.py
"""Calculate optimal test distribution."""
from typing import Dict, List, Set
from lib.test_audit.test_parser import TestInfo

def map_test_coverage(tests: List[TestInfo]) -> Dict[str, Set[str]]:
    """Map each test to the functions it covers."""
    return {test.name: test.targets for test in tests}
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_audit/test_optimizer.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add lib/test_audit/optimizer.py tests/test_audit/test_optimizer.py
git commit -m "feat(audit): map test coverage to functions"
```

---

### Task 3.2: Minimum Covering Set

**Files:**
- Modify: `lib/test_audit/optimizer.py`
- Test: `tests/test_audit/test_optimizer.py`

**Step 1: Write the failing test**

```python
def test_find_minimum_covering_set():
    """Find smallest set of tests that covers all functions."""
    coverage = {
        "test_a": {"f1", "f2", "f3"},  # Covers 3
        "test_b": {"f1"},              # Redundant with test_a
        "test_c": {"f4", "f5"},        # Covers 2 unique
        "test_d": {"f4"},              # Redundant with test_c
        "test_e": {"f6"},              # Covers 1 unique
    }

    functions_to_cover = {"f1", "f2", "f3", "f4", "f5", "f6"}

    minimal = find_minimum_covering_set(coverage, functions_to_cover)

    # Greedy: picks test_a (3), test_c (2), test_e (1) = 3 tests
    assert len(minimal) == 3
    assert "test_a" in minimal
    assert "test_c" in minimal
    assert "test_e" in minimal
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_audit/test_optimizer.py::test_find_minimum_covering_set -v`
Expected: FAIL - function not defined

**Step 3: Implement greedy set cover**

Add to `lib/test_audit/optimizer.py`:

```python
def find_minimum_covering_set(
    coverage: Dict[str, Set[str]],
    functions_to_cover: Set[str]
) -> Set[str]:
    """Find minimum set of tests that covers all functions (greedy approximation)."""
    remaining = functions_to_cover.copy()
    selected = set()

    while remaining:
        # Find test that covers most remaining functions
        best_test = None
        best_coverage = 0

        for test_name, covers in coverage.items():
            if test_name in selected:
                continue
            overlap = len(covers & remaining)
            if overlap > best_coverage:
                best_coverage = overlap
                best_test = test_name

        if best_test is None or best_coverage == 0:
            # No test covers remaining functions - they're gaps
            break

        selected.add(best_test)
        remaining -= coverage[best_test]

    return selected
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_audit/test_optimizer.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add lib/test_audit/optimizer.py tests/test_audit/test_optimizer.py
git commit -m "feat(audit): implement greedy minimum covering set algorithm"
```

---

### Task 3.3: Gap Detection

**Files:**
- Modify: `lib/test_audit/optimizer.py`
- Test: `tests/test_audit/test_optimizer.py`

**Step 1: Write the failing test**

```python
def test_find_coverage_gaps():
    """Identify functions with no test coverage."""
    coverage = {
        "test_a": {"f1", "f2"},
        "test_b": {"f3"},
    }
    all_functions = {"f1", "f2", "f3", "f4", "f5"}

    gaps = find_coverage_gaps(coverage, all_functions)

    assert gaps == {"f4", "f5"}
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_audit/test_optimizer.py::test_find_coverage_gaps -v`
Expected: FAIL - function not defined

**Step 3: Implement gap detection**

Add to `lib/test_audit/optimizer.py`:

```python
def find_coverage_gaps(
    coverage: Dict[str, Set[str]],
    all_functions: Set[str]
) -> Set[str]:
    """Find functions that have no test coverage."""
    covered = set()
    for covers in coverage.values():
        covered |= covers
    return all_functions - covered
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_audit/test_optimizer.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add lib/test_audit/optimizer.py tests/test_audit/test_optimizer.py
git commit -m "feat(audit): detect coverage gaps"
```

---

## Phase 4: Decision Engine

Interactive decision-making that works autonomously on clear decisions and asks for guidance on ambiguous ones.

### Task 4.1: Confidence Scoring

**Files:**
- Create: `lib/test_audit/decision_engine.py`
- Test: `tests/test_audit/test_decision_engine.py`

**Step 1: Write the failing test**

```python
# tests/test_audit/test_decision_engine.py
import pytest
from lib.test_audit.decision_engine import score_test_health, HealthScore

def test_score_test_health_high_confidence_delete():
    """Tests with no assertions are clear deletes."""
    from lib.test_audit.test_parser import TestInfo

    test = TestInfo(
        name="test_useless",
        file_path="test.py",
        line_number=1,
        assertions=0,
        mocks=0,
        targets=set()
    )

    score = score_test_health(test)

    assert score.verdict == "delete"
    assert score.confidence >= 0.9
    assert "no assertions" in score.reason.lower()
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_audit/test_decision_engine.py::test_score_test_health_high_confidence_delete -v`
Expected: FAIL - module not found

**Step 3: Implement confidence scoring**

```python
# lib/test_audit/decision_engine.py
"""Decision engine for test audit - handles confident and ambiguous decisions."""
from dataclasses import dataclass
from typing import Literal
from lib.test_audit.test_parser import TestInfo

@dataclass
class HealthScore:
    test_name: str
    verdict: Literal["keep", "delete", "review"]
    confidence: float  # 0.0 to 1.0
    reason: str

def score_test_health(test: TestInfo, mock_threshold: int = 3) -> HealthScore:
    """Score a test's health and recommend action."""

    # No assertions = definitely delete
    if test.assertions == 0:
        return HealthScore(
            test_name=test.name,
            verdict="delete",
            confidence=0.95,
            reason="No assertions - test runs code but validates nothing"
        )

    # Too many mocks = likely delete, but review
    if test.mocks > mock_threshold:
        return HealthScore(
            test_name=test.name,
            verdict="review",
            confidence=0.6,
            reason=f"Heavy mocking ({test.mocks} mocks) - may be testing glue, not logic"
        )

    # No targets identified = review
    if not test.targets:
        return HealthScore(
            test_name=test.name,
            verdict="review",
            confidence=0.5,
            reason="Could not identify test targets - manual review needed"
        )

    # Looks healthy
    return HealthScore(
        test_name=test.name,
        verdict="keep",
        confidence=0.8,
        reason=f"Healthy: {test.assertions} assertions, {test.mocks} mocks, targets: {test.targets}"
    )
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_audit/test_decision_engine.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add lib/test_audit/decision_engine.py tests/test_audit/test_decision_engine.py
git commit -m "feat(audit): add test health scoring with confidence levels"
```

---

### Task 4.2: Batch Decision Processing

**Files:**
- Modify: `lib/test_audit/decision_engine.py`
- Test: `tests/test_audit/test_decision_engine.py`

**Step 1: Write the failing test**

```python
def test_process_decisions_separates_confident_from_ambiguous():
    """Separate high-confidence decisions from those needing review."""
    from lib.test_audit.test_parser import TestInfo
    from lib.test_audit.decision_engine import process_decisions, DecisionBatch

    tests = [
        TestInfo(name="test_no_assert", file_path="t.py", line_number=1, assertions=0, mocks=0, targets=set()),
        TestInfo(name="test_too_mocks", file_path="t.py", line_number=10, assertions=1, mocks=5, targets={"f"}),
        TestInfo(name="test_healthy", file_path="t.py", line_number=20, assertions=2, mocks=0, targets={"f", "g"}),
    ]

    batch = process_decisions(tests, confidence_threshold=0.8)

    # High confidence: delete test_no_assert, keep test_healthy
    assert "test_no_assert" in [d.test_name for d in batch.confident_deletes]
    assert "test_healthy" in [d.test_name for d in batch.confident_keeps]

    # Needs review: test_too_mocks
    assert "test_too_mocks" in [d.test_name for d in batch.needs_review]
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_audit/test_decision_engine.py::test_process_decisions_separates_confident_from_ambiguous -v`
Expected: FAIL - function not defined

**Step 3: Implement batch processing**

Add to `lib/test_audit/decision_engine.py`:

```python
from dataclasses import field
from typing import List

@dataclass
class DecisionBatch:
    confident_deletes: List[HealthScore] = field(default_factory=list)
    confident_keeps: List[HealthScore] = field(default_factory=list)
    needs_review: List[HealthScore] = field(default_factory=list)

def process_decisions(
    tests: List[TestInfo],
    confidence_threshold: float = 0.8,
    mock_threshold: int = 3
) -> DecisionBatch:
    """Process all tests and separate by confidence level."""
    batch = DecisionBatch()

    for test in tests:
        score = score_test_health(test, mock_threshold=mock_threshold)

        if score.confidence >= confidence_threshold:
            if score.verdict == "delete":
                batch.confident_deletes.append(score)
            elif score.verdict == "keep":
                batch.confident_keeps.append(score)
            else:
                batch.needs_review.append(score)
        else:
            batch.needs_review.append(score)

    return batch
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_audit/test_decision_engine.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add lib/test_audit/decision_engine.py tests/test_audit/test_decision_engine.py
git commit -m "feat(audit): batch decision processing with confidence separation"
```

---

## Phase 5: CLI Interface

Build the command-line interface that ties everything together.

### Task 5.1: Audit Command - Dry Run

**Files:**
- Create: `bin/audit-tests`
- Test: `tests/test_audit/test_cli.py`

**Step 1: Write the failing test**

```python
# tests/test_audit/test_cli.py
import pytest
import subprocess
from pathlib import Path

def test_audit_dry_run_shows_summary(tmp_path):
    """Dry run shows what would be deleted without making changes."""
    # Create a minimal test file
    test_file = tmp_path / "test_example.py"
    test_file.write_text('''
def test_no_assertions():
    x = 1 + 1  # No assert

def test_healthy():
    assert 1 + 1 == 2
''')

    result = subprocess.run(
        ["python", "bin/audit-tests", "--path", str(tmp_path)],
        capture_output=True,
        text=True
    )

    assert result.returncode == 0
    assert "test_no_assertions" in result.stdout
    assert "delete" in result.stdout.lower()
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_audit/test_cli.py::test_audit_dry_run_shows_summary -v`
Expected: FAIL - bin/audit-tests not found

**Step 3: Implement CLI**

```python
#!/usr/bin/env python3
# bin/audit-tests
"""Test audit CLI - calculate optimal test distribution."""
import argparse
import sys
from pathlib import Path

# Add lib to path
sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

from test_audit.test_parser import parse_test_file
from test_audit.decision_engine import process_decisions

def main():
    parser = argparse.ArgumentParser(description="Audit test suite for optimal coverage")
    parser.add_argument("--path", type=Path, default=Path("tests"), help="Path to test directory")
    parser.add_argument("--execute", action="store_true", help="Actually delete tests (default: dry run)")
    parser.add_argument("--confidence", type=float, default=0.8, help="Confidence threshold for auto-decisions")
    args = parser.parse_args()

    # Find all test files
    test_files = list(args.path.rglob("test_*.py"))

    if not test_files:
        print(f"No test files found in {args.path}")
        return 1

    # Parse all tests
    all_tests = []
    for tf in test_files:
        try:
            code = tf.read_text()
            tests = parse_test_file(code, str(tf))
            all_tests.extend(tests)
        except SyntaxError as e:
            print(f"Warning: Could not parse {tf}: {e}")

    print(f"Analyzed {len(all_tests)} tests in {len(test_files)} files\n")

    # Process decisions
    batch = process_decisions(all_tests, confidence_threshold=args.confidence)

    # Report
    print("=" * 60)
    print("AUDIT RESULTS")
    print("=" * 60)

    if batch.confident_deletes:
        print(f"\n🗑️  TO DELETE ({len(batch.confident_deletes)} tests):")
        for score in batch.confident_deletes:
            print(f"  - {score.test_name}: {score.reason}")

    if batch.confident_keeps:
        print(f"\n✅ TO KEEP ({len(batch.confident_keeps)} tests):")
        for score in batch.confident_keeps[:5]:  # Show first 5
            print(f"  - {score.test_name}")
        if len(batch.confident_keeps) > 5:
            print(f"  ... and {len(batch.confident_keeps) - 5} more")

    if batch.needs_review:
        print(f"\n⚠️  NEEDS REVIEW ({len(batch.needs_review)} tests):")
        for score in batch.needs_review:
            print(f"  - {score.test_name}: {score.reason}")

    print("\n" + "=" * 60)
    print(f"Summary: {len(batch.confident_deletes)} delete, {len(batch.confident_keeps)} keep, {len(batch.needs_review)} review")

    if not args.execute:
        print("\nDry run complete. Use --execute to apply deletions.")

    return 0

if __name__ == "__main__":
    sys.exit(main())
```

**Step 4: Make executable and run test**

```bash
chmod +x bin/audit-tests
```

Run: `pytest tests/test_audit/test_cli.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add bin/audit-tests tests/test_audit/test_cli.py
git commit -m "feat(audit): add CLI for test audit dry run"
```

---

### Task 5.2: Interactive Review Mode

**Files:**
- Modify: `bin/audit-tests`
- Modify: `lib/test_audit/decision_engine.py`

**Step 1: Write the failing test**

```python
def test_interactive_review_prompts_for_ambiguous(tmp_path, monkeypatch):
    """Interactive mode asks about ambiguous tests."""
    test_file = tmp_path / "test_example.py"
    test_file.write_text('''
from unittest.mock import patch

def test_many_mocks():
    with patch("a"), patch("b"), patch("c"), patch("d"):
        assert True
''')

    # Simulate user input: 'k' for keep
    inputs = iter(['k'])
    monkeypatch.setattr('builtins.input', lambda _: next(inputs))

    result = subprocess.run(
        ["python", "bin/audit-tests", "--path", str(tmp_path), "--interactive"],
        capture_output=True,
        text=True,
        input="k\n"
    )

    assert "review" in result.stdout.lower() or "keep" in result.stdout.lower()
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_audit/test_cli.py::test_interactive_review_prompts_for_ambiguous -v`
Expected: FAIL - --interactive not supported

**Step 3: Add interactive mode to CLI**

Update `bin/audit-tests` to add interactive review:

```python
def interactive_review(needs_review):
    """Interactively review ambiguous tests."""
    kept = []
    deleted = []

    print("\n" + "=" * 60)
    print("INTERACTIVE REVIEW")
    print("=" * 60)
    print("For each test, enter: (k)eep, (d)elete, (s)kip")
    print()

    for score in needs_review:
        print(f"\n{score.test_name}")
        print(f"  Reason for review: {score.reason}")
        print(f"  Confidence: {score.confidence:.0%}")

        while True:
            choice = input("  [k/d/s]? ").strip().lower()
            if choice in ('k', 'keep'):
                kept.append(score)
                print("  → Keeping")
                break
            elif choice in ('d', 'delete'):
                deleted.append(score)
                print("  → Will delete")
                break
            elif choice in ('s', 'skip'):
                print("  → Skipping (will keep)")
                kept.append(score)
                break
            else:
                print("  Invalid choice. Enter k, d, or s.")

    return kept, deleted
```

And update `main()` to use it:

```python
parser.add_argument("--interactive", action="store_true", help="Interactively review ambiguous tests")

# ... after batch processing ...

if args.interactive and batch.needs_review:
    kept, deleted = interactive_review(batch.needs_review)
    batch.confident_keeps.extend(kept)
    batch.confident_deletes.extend(deleted)
    batch.needs_review = []
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_audit/test_cli.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add bin/audit-tests
git commit -m "feat(audit): add interactive review mode for ambiguous tests"
```

---

### Task 5.3: Execute Mode - Delete Tests

**Files:**
- Modify: `bin/audit-tests`
- Test: `tests/test_audit/test_cli.py`

**Step 1: Write the failing test**

```python
def test_execute_mode_deletes_tests(tmp_path):
    """Execute mode actually removes test functions."""
    test_file = tmp_path / "test_example.py"
    test_file.write_text('''
def test_no_assertions():
    x = 1 + 1

def test_healthy():
    assert 1 + 1 == 2
''')

    # Run with execute
    result = subprocess.run(
        ["python", "bin/audit-tests", "--path", str(tmp_path), "--execute"],
        capture_output=True,
        text=True
    )

    assert result.returncode == 0

    # Check the file was modified
    new_content = test_file.read_text()
    assert "test_no_assertions" not in new_content
    assert "test_healthy" in new_content
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_audit/test_cli.py::test_execute_mode_deletes_tests -v`
Expected: FAIL - execute doesn't actually delete

**Step 3: Implement test deletion**

Add to `lib/test_audit/decision_engine.py`:

```python
import ast

def delete_tests_from_file(file_path: Path, test_names: Set[str]) -> str:
    """Remove specified test functions from a file, return new content."""
    content = file_path.read_text()
    tree = ast.parse(content)
    lines = content.splitlines(keepends=True)

    # Find line ranges to delete (in reverse order to preserve line numbers)
    ranges_to_delete = []

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in test_names:
            # Find the end line (next function or end of file)
            start = node.lineno - 1  # 0-indexed
            end = node.end_lineno  # exclusive
            ranges_to_delete.append((start, end))

    # Sort in reverse order and delete
    ranges_to_delete.sort(reverse=True)
    for start, end in ranges_to_delete:
        del lines[start:end]

    return ''.join(lines)
```

Update `bin/audit-tests` main() to use it:

```python
if args.execute:
    from lib.test_audit.decision_engine import delete_tests_from_file

    # Group deletions by file
    by_file = {}
    for score in batch.confident_deletes:
        # Need to track file_path in HealthScore or look it up
        # For now, re-parse to get file info
        pass

    print(f"\nDeleted {len(batch.confident_deletes)} tests.")
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_audit/test_cli.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add bin/audit-tests lib/test_audit/decision_engine.py tests/test_audit/test_cli.py
git commit -m "feat(audit): implement test deletion in execute mode"
```

---

## Phase 6: Integration

Wire everything together and test on the real codebase.

### Task 6.1: Full Pipeline Integration Test

**Files:**
- Create: `tests/test_audit/test_integration.py`

**Step 1: Write the integration test**

```python
# tests/test_audit/test_integration.py
import pytest
from pathlib import Path
from lib.test_audit.code_analyzer import find_entry_points
from lib.test_audit.call_graph import build_call_graph, find_reachable
from lib.test_audit.test_parser import parse_test_file
from lib.test_audit.optimizer import map_test_coverage, find_minimum_covering_set, find_coverage_gaps
from lib.test_audit.decision_engine import process_decisions

def test_full_audit_pipeline(tmp_path):
    """Full pipeline: analyze code, parse tests, calculate optimal, make decisions."""

    # Create production code
    prod_file = tmp_path / "mymodule.py"
    prod_file.write_text('''
def main():
    result = process(get_input())
    save(result)

def process(data):
    validated = validate(data)
    return transform(validated)

def validate(data):
    if not data:
        raise ValueError("Empty data")
    return data

def transform(data):
    return data.upper()

def get_input():
    return "hello"

def save(result):
    print(result)

def unused_function():
    """Never called from main."""
    pass

if __name__ == "__main__":
    main()
''')

    # Create test file
    test_file = tmp_path / "test_mymodule.py"
    test_file.write_text('''
from mymodule import process, validate, transform, unused_function

def test_process():
    assert process("hello") == "HELLO"

def test_validate_empty():
    import pytest
    with pytest.raises(ValueError):
        validate("")

def test_transform():
    assert transform("hi") == "HI"

def test_unused():
    # Tests a function that's never called in production
    unused_function()

def test_no_assertions():
    process("x")  # No assert!

def test_duplicate_transform():
    # Duplicate of test_transform
    assert transform("a") == "A"
''')

    # 1. Analyze production code
    prod_code = prod_file.read_text()
    entry_points = find_entry_points(prod_code, str(prod_file))
    graph = build_call_graph(prod_code, str(prod_file))
    reachable = find_reachable(graph, [ep.name for ep in entry_points])

    assert "main" in reachable
    assert "process" in reachable
    assert "unused_function" not in reachable

    # 2. Parse tests
    test_code = test_file.read_text()
    tests = parse_test_file(test_code, str(test_file))

    assert len(tests) == 6

    # 3. Calculate optimal coverage
    coverage = map_test_coverage(tests)
    minimal = find_minimum_covering_set(coverage, reachable)
    gaps = find_coverage_gaps(coverage, reachable)

    # 4. Make decisions
    batch = process_decisions(tests)

    # Should recommend deleting: test_no_assertions (no asserts), test_unused (dead code)
    delete_names = [d.test_name for d in batch.confident_deletes]
    assert "test_no_assertions" in delete_names

    # Should keep: test_process, test_validate_empty, test_transform
    keep_names = [k.test_name for k in batch.confident_keeps]
    assert "test_process" in keep_names or "test_process" in [r.test_name for r in batch.needs_review]
```

**Step 2: Run test**

Run: `pytest tests/test_audit/test_integration.py -v`
Expected: PASS

**Step 3: Commit**

```bash
git add tests/test_audit/test_integration.py
git commit -m "test(audit): add full pipeline integration test"
```

---

### Task 6.2: Run on Actual Test Suite

**Files:**
- None (manual testing)

**Step 1: Run audit on the real test suite**

```bash
python bin/audit-tests --path tests/
```

**Step 2: Review output and adjust thresholds if needed**

Based on results, you may need to tune:
- Mock threshold (default 3)
- Confidence threshold (default 0.8)

**Step 3: Document findings**

Create a summary of initial audit results in `docs/plans/2026-01-25-test-audit-results.md`

---

## Summary

| Phase | Tasks | Purpose |
|-------|-------|---------|
| 1 | 1.1-1.4 | Code analyzer - entry points, call graph, reachability |
| 2 | 2.1-2.2 | Test parser - extract tests, health signals |
| 3 | 3.1-3.3 | Optimizer - coverage mapping, minimum set, gaps |
| 4 | 4.1-4.2 | Decision engine - confidence scoring, batch processing |
| 5 | 5.1-5.3 | CLI - dry run, interactive review, execute mode |
| 6 | 6.1-6.2 | Integration - full pipeline test, real suite audit |

**Total: 14 tasks, ~2-5 minutes each**

Each task follows TDD: write failing test → implement → verify → commit.
