# tests/test_audit/test_test_parser.py
from lib.test_audit.test_parser import parse_test_file


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
