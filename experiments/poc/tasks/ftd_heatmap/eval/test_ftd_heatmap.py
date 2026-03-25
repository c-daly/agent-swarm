"""Eval tests for the FtdHeatmap component.

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
COMPONENT_FILE = os.path.join(REPO_ROOT, "webapp", "src", "components", "FtdHeatmap.tsx")
TEST_FILE = os.path.join(REPO_ROOT, "webapp", "src", "components", "FtdHeatmap.test.tsx")


class TestComponentExists:
    """The component file must exist at the expected path."""

    def test_component_file_exists(self):
        assert os.path.isfile(COMPONENT_FILE), (
            f"FtdHeatmap.tsx not found at {COMPONENT_FILE}"
        )

    def test_test_file_exists(self):
        assert os.path.isfile(TEST_FILE), (
            f"FtdHeatmap.test.tsx not found at {TEST_FILE}"
        )


class TestComponentExports:
    """The component must export the expected symbol."""

    def test_exports_ftd_heatmap(self):
        if not os.path.isfile(COMPONENT_FILE):
            pytest.skip("Component file does not exist yet")
        content = open(COMPONENT_FILE).read()
        assert re.search(
            r"export\s+(default\s+)?function\s+FtdHeatmap|export\s+(default\s+)?const\s+FtdHeatmap|export\s+\{[^}]*FtdHeatmap",
            content,
        ), "FtdHeatmap must be exported from the component file"


class TestComponentImports:
    """The component must import from the expected API types / libraries."""

    def test_imports_react(self):
        if not os.path.isfile(COMPONENT_FILE):
            pytest.skip("Component file does not exist yet")
        content = open(COMPONENT_FILE).read()
        assert "from 'react'" in content or 'from "react"' in content, (
            "Component must import from react"
        )

    def test_references_api_ftd(self):
        if not os.path.isfile(COMPONENT_FILE):
            pytest.skip("Component file does not exist yet")
        content = open(COMPONENT_FILE).read()
        assert re.search(r"/api/ftd|api/ftd|fetchFtd|useFtd", content), (
            "Component must reference the /api/ftd endpoint or a fetch wrapper for it"
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
        assert "FtdHeatmap" in content, (
            "Test file must reference the FtdHeatmap component"
        )
