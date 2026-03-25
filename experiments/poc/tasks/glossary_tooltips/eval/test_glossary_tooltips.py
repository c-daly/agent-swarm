"""Eval tests for the GlossaryTooltip component.

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
COMPONENT_FILE = os.path.join(REPO_ROOT, "webapp", "src", "components", "GlossaryTooltip.tsx")
TEST_FILE = os.path.join(REPO_ROOT, "webapp", "src", "components", "GlossaryTooltip.test.tsx")


class TestComponentExists:
    """The component file must exist at the expected path."""

    def test_component_file_exists(self):
        assert os.path.isfile(COMPONENT_FILE), (
            f"GlossaryTooltip.tsx not found at {COMPONENT_FILE}"
        )

    def test_test_file_exists(self):
        assert os.path.isfile(TEST_FILE), (
            f"GlossaryTooltip.test.tsx not found at {TEST_FILE}"
        )


class TestComponentExports:
    """The component must export the expected symbol."""

    def test_exports_glossary_tooltip(self):
        if not os.path.isfile(COMPONENT_FILE):
            pytest.skip("Component file does not exist yet")
        content = open(COMPONENT_FILE).read()
        assert re.search(
            r"export\s+(default\s+)?function\s+GlossaryTooltip"
            r"|export\s+(default\s+)?const\s+GlossaryTooltip"
            r"|export\s+\{[^}]*GlossaryTooltip",
            content,
        ), "GlossaryTooltip must be exported from the component file"


class TestComponentImports:
    """The component must import from the expected libraries."""

    def test_imports_react(self):
        if not os.path.isfile(COMPONENT_FILE):
            pytest.skip("Component file does not exist yet")
        content = open(COMPONENT_FILE).read()
        assert "from 'react'" in content or 'from "react"' in content, (
            "Component must import from react"
        )

    def test_references_api_glossary(self):
        if not os.path.isfile(COMPONENT_FILE):
            pytest.skip("Component file does not exist yet")
        content = open(COMPONENT_FILE).read()
        assert re.search(r"/api/glossary|api/glossary|fetchGlossary|useGlossary", content), (
            "Component must reference the /api/glossary endpoint or a fetch wrapper"
        )


class TestComponentProps:
    """The component should accept the expected props (term, children)."""

    def test_accepts_term_prop(self):
        if not os.path.isfile(COMPONENT_FILE):
            pytest.skip("Component file does not exist yet")
        content = open(COMPONENT_FILE).read()
        assert "term" in content, (
            "Component must accept a 'term' prop for glossary lookup"
        )

    def test_accepts_children_prop(self):
        if not os.path.isfile(COMPONENT_FILE):
            pytest.skip("Component file does not exist yet")
        content = open(COMPONENT_FILE).read()
        assert "children" in content, (
            "Component must accept a 'children' prop for wrapping content"
        )


class TestCachingBehavior:
    """The component should cache glossary data client-side."""

    def test_caching_pattern_present(self):
        if not os.path.isfile(COMPONENT_FILE):
            pytest.skip("Component file does not exist yet")
        content = open(COMPONENT_FILE).read()
        assert re.search(
            r"createContext|useContext|useMemo|useRef|cache|Cache"
            r"|QueryClient|useSWR|useQuery|useState.*glossary",
            content,
        ), "Component should implement client-side caching for glossary data"


class TestTestFileContent:
    """The test file must contain meaningful test cases."""

    def test_test_file_has_tests(self):
        if not os.path.isfile(TEST_FILE):
            pytest.skip("Test file does not exist yet")
        content = open(TEST_FILE).read()
        assert re.search(r"(it|test)\s*\(", content), (
            "Test file must contain at least one test case"
        )

    def test_test_file_renders_component(self):
        if not os.path.isfile(TEST_FILE):
            pytest.skip("Test file does not exist yet")
        content = open(TEST_FILE).read()
        assert "GlossaryTooltip" in content, (
            "Test file must reference the GlossaryTooltip component"
        )
