"""Eval tests for the MacroGrid component.

Validates structural correctness of the component implementation.
Since vitest requires the webapp scaffold (a separate dependency),
these tests verify file existence, exports, imports, and test coverage
presence rather than running the component.
"""

import os
import re

import pytest

# Resolve paths relative to the repo root.
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", ".."))
COMPONENT_FILE = os.path.join(REPO_ROOT, "webapp", "src", "components", "MacroGrid.tsx")
TEST_FILE = os.path.join(REPO_ROOT, "webapp", "src", "components", "MacroGrid.test.tsx")

EXPECTED_SERIES = ["GDP", "CPIAUCSL", "UNRATE", "FEDFUNDS"]


class TestComponentExists:
    """The component file must exist at the expected path."""

    def test_component_file_exists(self):
        assert os.path.isfile(COMPONENT_FILE), (
            f"MacroGrid.tsx not found at {COMPONENT_FILE}"
        )

    def test_test_file_exists(self):
        assert os.path.isfile(TEST_FILE), (
            f"MacroGrid.test.tsx not found at {TEST_FILE}"
        )


class TestComponentExports:
    """The component must export the expected symbol."""

    def test_exports_macro_grid(self):
        if not os.path.isfile(COMPONENT_FILE):
            pytest.skip("Component file does not exist yet")
        content = open(COMPONENT_FILE).read()
        assert re.search(
            r"export\s+(default\s+)?function\s+MacroGrid|export\s+(default\s+)?const\s+MacroGrid|export\s+\{[^}]*MacroGrid",
            content,
        ), "MacroGrid must be exported from the component file"


class TestComponentImports:
    """The component must import from the expected API types / libraries."""

    def test_imports_react(self):
        if not os.path.isfile(COMPONENT_FILE):
            pytest.skip("Component file does not exist yet")
        content = open(COMPONENT_FILE).read()
        assert "from 'react'" in content or 'from "react"' in content, (
            "Component must import from react"
        )

    def test_imports_recharts(self):
        if not os.path.isfile(COMPONENT_FILE):
            pytest.skip("Component file does not exist yet")
        content = open(COMPONENT_FILE).read()
        assert "from 'recharts'" in content or 'from "recharts"' in content, (
            "Component must import from recharts for sparklines"
        )

    def test_references_api_fred(self):
        if not os.path.isfile(COMPONENT_FILE):
            pytest.skip("Component file does not exist yet")
        content = open(COMPONENT_FILE).read()
        assert re.search(r"/api/fred|api/fred|fetchFred|useFred", content), (
            "Component must reference the /api/fred endpoint or a fetch wrapper for it"
        )


class TestSeriesConfiguration:
    """The component should reference the expected FRED series IDs."""

    def test_references_expected_series(self):
        if not os.path.isfile(COMPONENT_FILE):
            pytest.skip("Component file does not exist yet")
        content = open(COMPONENT_FILE).read()
        missing = [s for s in EXPECTED_SERIES if s not in content]
        assert not missing, (
            f"Component is missing references to series: {missing}"
        )


class TestTestFileContent:
    """The test file must contain meaningful test cases."""

    def test_test_file_has_tests(self):
        if not os.path.isfile(TEST_FILE):
            pytest.skip("Test file does not exist yet")
        content = open(TEST_FILE).read()
        assert re.search(r"(it|test)\s*\(", content), (
            "Test file must contain at least one test case (it/test block)"
        )

    def test_test_file_renders_component(self):
        if not os.path.isfile(TEST_FILE):
            pytest.skip("Test file does not exist yet")
        content = open(TEST_FILE).read()
        assert "MacroGrid" in content, (
            "Test file must reference the MacroGrid component"
        )
