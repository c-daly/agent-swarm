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

    # Process only top-level statements to avoid double-counting
    for node in tree.body:
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
    imports: Set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.asname or alias.name)
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                imports.add(alias.asname or alias.name)
    return imports


# Common test utilities/framework imports that are NOT production targets
_TEST_UTILITIES = frozenset({
    "Mock", "MagicMock", "patch", "PropertyMock", "AsyncMock",
    "pytest", "unittest", "nose",
    "fixture", "parametrize", "mark",
    "assert_called", "assert_called_once", "assert_called_with",
    "call", "ANY", "sentinel",
    "raises", "warns", "deprecated_call",
    "monkeypatch", "tmp_path", "capsys", "capfd",
})


def _analyze_test_function(
    node: ast.FunctionDef, file_path: str, class_name: str, imports: Set[str]
) -> TestInfo:
    """Analyze a single test function."""
    assertions = 0
    mocks = 0
    targets: Set[str] = set()

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
            # Filter out test utilities to only track production code
            if isinstance(func, ast.Name) and func.id in imports:
                if func.id not in _TEST_UTILITIES:
                    targets.add(func.id)

    return TestInfo(
        name=node.name,
        file_path=file_path,
        line_number=node.lineno,
        class_name=class_name,
        imports=imports,
        assertions=assertions,
        mocks=mocks,
        targets=targets,
    )
