"""Tests for shell command normalization to prevent security bypasses."""

import sys
from pathlib import Path

# Add hooks to path for import
sys.path.insert(0, str(Path(__file__).parent.parent / "hooks"))

from importlib import import_module


def get_normalize_function():
    """Import the normalization function from combined_enforcement."""
    # Import as module to avoid filename issues
    spec = __import__("importlib.util", fromlist=["spec_from_file_location", "module_from_spec"])
    module_path = Path(__file__).parent.parent / "hooks" / "combined_enforcement.py"
    spec = spec.spec_from_file_location("combined_enforcement", module_path)
    module = spec.loader.create_module(spec)
    if module is None:
        module = type(sys)("combined_enforcement")
    spec.loader.exec_module(module)
    return module._normalize_shell_command


class TestNormalizeShellCommand:
    """Test shell command normalization for security bypasses."""

    def setup_method(self):
        """Get the normalization function."""
        self.normalize = get_normalize_function()

    def test_empty_string_quotes_removed(self):
        """Empty quotes should be removed to detect .sta""te bypasses."""
        assert ".state" in self.normalize('echo "test" > .sta""te/file')
        assert ".state" in self.normalize("echo test > .sta''te/file")

    def test_backslash_escapes_normalized(self):
        """Backslash escapes should be normalized."""
        assert ".state" in self.normalize(r"echo test > .\state/file")
        assert "session.json" in self.normalize(r"cat > ses\sion.json")

    def test_ansi_c_quoting_removed(self):
        """$'' ANSI-C quoting should be stripped."""
        assert ".state" in self.normalize("cat $'.state'/file")
        assert "session" in self.normalize("echo $'session'.json")

    def test_backtick_empty_removed(self):
        """Empty backtick commands should be removed."""
        assert ".state" in self.normalize("cat .sta``te/file")

    def test_normal_commands_unchanged(self):
        """Normal commands without obfuscation should work."""
        assert ".state" in self.normalize("cat .state/session.json")
        assert "session.json" in self.normalize("ls -la session.json")

    def test_whitespace_collapsed(self):
        """Multiple spaces should be collapsed."""
        result = self.normalize("echo   test    >   .state/file")
        assert "  " not in result
        assert ".state" in result

    def test_preserves_valid_escapes(self):
        """Valid escape sequences like \\n should be preserved."""
        result = self.normalize(r"echo -e 'line1\nline2'")
        assert r"\n" in result

    def test_combined_obfuscation(self):
        """Multiple obfuscation techniques combined."""
        # .sta""te with backticks
        assert ".state" in self.normalize('.sta""te``/file')
        # $'' with empty quotes
        assert ".state" in self.normalize("$'.sta''te'")
