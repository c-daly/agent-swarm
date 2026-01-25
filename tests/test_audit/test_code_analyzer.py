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
