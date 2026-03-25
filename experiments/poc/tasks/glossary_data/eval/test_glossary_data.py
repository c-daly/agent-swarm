"""Eval tests for the glossary data YAML file."""

import os
from pathlib import Path

import pytest
import yaml


GLOSSARY_PATH = Path(__file__).resolve().parents[4] / "agora" / "glossary" / "terms.yaml"

REQUIRED_FIELDS = {"term", "description", "interpretation", "caveats"}

REQUIRED_TERMS = [
    "yield_curve",
    "inversion",
    "spread",
    "ftd",
    "short_interest",
    "short_volume_ratio",
    "gdp",
    "cpi",
    "unemployment_rate",
    "federal_funds_rate",
    "treasury_yields",
    "maturity",
]

MINIMUM_TERM_COUNT = 15


@pytest.fixture(scope="module")
def glossary():
    """Load the glossary YAML file."""
    assert GLOSSARY_PATH.exists(), f"Glossary file not found at {GLOSSARY_PATH}"
    with open(GLOSSARY_PATH) as f:
        data = yaml.safe_load(f)
    assert data is not None, "Glossary file is empty"
    return data


class TestGlossaryStructure:
    """The glossary file has the expected top-level structure."""

    def test_is_mapping(self, glossary):
        assert isinstance(glossary, dict), "Glossary must be a YAML mapping"

    def test_minimum_term_count(self, glossary):
        assert len(glossary) >= MINIMUM_TERM_COUNT, (
            f"Expected at least {MINIMUM_TERM_COUNT} terms, got {len(glossary)}"
        )

    def test_keys_are_strings(self, glossary):
        for key in glossary:
            assert isinstance(key, str), f"Key {key!r} is not a string"


class TestRequiredTerms:
    """All required terms are present."""

    @pytest.mark.parametrize("term_key", REQUIRED_TERMS)
    def test_required_term_exists(self, glossary, term_key):
        assert term_key in glossary, f"Required term '{term_key}' is missing"


class TestEntrySchema:
    """Each glossary entry has all required fields with non-empty values."""

    def test_all_entries_have_required_fields(self, glossary):
        for key, entry in glossary.items():
            assert isinstance(entry, dict), f"Entry '{key}' is not a mapping"
            for field in REQUIRED_FIELDS:
                assert field in entry, f"Entry '{key}' missing field '{field}'"

    def test_no_empty_descriptions(self, glossary):
        for key, entry in glossary.items():
            desc = entry.get("description", "")
            assert isinstance(desc, str) and len(desc.strip()) > 0, (
                f"Entry '{key}' has empty description"
            )

    def test_no_empty_interpretations(self, glossary):
        for key, entry in glossary.items():
            interp = entry.get("interpretation", "")
            assert isinstance(interp, str) and len(interp.strip()) > 0, (
                f"Entry '{key}' has empty interpretation"
            )

    def test_no_empty_caveats(self, glossary):
        for key, entry in glossary.items():
            cav = entry.get("caveats", "")
            assert isinstance(cav, str) and len(cav.strip()) > 0, (
                f"Entry '{key}' has empty caveats"
            )

    def test_term_display_names_are_nonempty(self, glossary):
        for key, entry in glossary.items():
            term = entry.get("term", "")
            assert isinstance(term, str) and len(term.strip()) > 0, (
                f"Entry '{key}' has empty term display name"
            )
