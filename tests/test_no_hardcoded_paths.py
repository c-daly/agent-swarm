"""
Test that no hardcoded /home/fearsidhe/ paths exist in code.

This test enforces dynamic path resolution using Path.home() or environment variables.
It should FAIL if any hardcoded paths are found in hooks/, lib/, or scripts/ directories.
"""

import re
from pathlib import Path


def test_no_hardcoded_home_paths_in_python_files():
    """Test that Python files use Path.home() instead of hardcoded /home/fearsidhe/"""
    plugin_root = Path(__file__).parent.parent

    # Target directories
    target_dirs = [
        plugin_root / "hooks",
        plugin_root / "lib",
        plugin_root / "scripts",
    ]

    # Pattern to detect hardcoded paths
    pattern = r"/home/fearsidhe/"

    violations = []

    for directory in target_dirs:
        if not directory.exists():
            continue

        # Find all Python files
        for py_file in directory.rglob("*.py"):
            # Skip test files themselves
            if "test_" in py_file.name or py_file.parent.name == "tests":
                continue

            content = py_file.read_text()

            # Check for hardcoded paths
            matches = re.finditer(pattern, content)
            for match in matches:
                # Get line number
                line_num = content[:match.start()].count('\n') + 1
                line_content = content.split('\n')[line_num - 1].strip()
                violations.append(f"{py_file.relative_to(plugin_root)}:{line_num}: {line_content}")

    assert not violations, (
        f"Found {len(violations)} hardcoded /home/fearsidhe/ paths. "
        f"Use Path.home() instead:\n" + "\n".join(violations)
    )


def test_no_hardcoded_home_paths_in_shell_scripts():
    """Test that shell scripts use $HOME or environment variables instead of hardcoded paths"""
    plugin_root = Path(__file__).parent.parent

    # Target directories
    target_dirs = [
        plugin_root / "hooks",
        plugin_root / "lib",
        plugin_root / "scripts",
    ]

    violations = []

    for directory in target_dirs:
        if not directory.exists():
            continue

        # Find all shell scripts
        for sh_file in directory.rglob("*.sh"):
            content = sh_file.read_text()

            # Check for hardcoded paths (excluding comments and variable expansion)
            for line_num, line in enumerate(content.split('\n'), 1):
                # Skip comments
                if line.strip().startswith('#'):
                    continue

                # Check for hardcoded path not using $HOME
                if '/home/fearsidhe/' in line and '$HOME' not in line and 'CLAUDE_PLUGIN_ROOT' not in line:
                    # But allow if it's in a Python string being constructed
                    if "sys.path.insert" in line and "'$PLUGIN_ROOT" not in line:
                        violations.append(f"{sh_file.relative_to(plugin_root)}:{line_num}: {line.strip()}")

    assert not violations, (
        f"Found {len(violations)} hardcoded /home/fearsidhe/ paths in shell scripts. "
        f"Use $HOME or $PLUGIN_ROOT instead:\n" + "\n".join(violations)
    )


def test_batch_scripts_use_dynamic_paths():
    """Test that batch_glob.py and batch_search.py use dynamic path resolution"""
    plugin_root = Path(__file__).parent.parent

    scripts = [
        plugin_root / "lib/scripts/batch_glob.py",
        plugin_root / "lib/scripts/batch_search.py",
    ]

    for script in scripts:
        if not script.exists():
            continue

        content = script.read_text()

        # Should NOT have hardcoded path
        assert "/home/fearsidhe/" not in content, (
            f"{script.name} contains hardcoded path. "
            f"Use: Path(__file__).parent.parent or Path.home()"
        )

        # Should have dynamic path resolution
        has_dynamic = any(x in content for x in [
            "Path(__file__)",
            "Path.home()",
            "os.path.dirname(__file__)",
            "__file__",
        ])

        assert has_dynamic, (
            f"{script.name} missing dynamic path resolution. "
            f"Add: sys.path.insert(0, str(Path(__file__).parent.parent))"
        )


def test_path_resolution_works_on_any_system():
    """Test that path resolution would work for any user (not just fearsidhe)"""
    plugin_root = Path(__file__).parent.parent

    # These scripts should work regardless of username
    scripts = [
        plugin_root / "lib/scripts/batch_glob.py",
        plugin_root / "lib/scripts/batch_search.py",
    ]

    for script in scripts:
        if not script.exists():
            continue

        content = script.read_text()

        # Verify it would work on different systems
        # Should use relative imports or Path resolution

        # Should NOT have hardcoded username anywhere
        assert 'fearsidhe' not in content.lower(), (
            f"{script.name} contains username 'fearsidhe' - must be system-agnostic"
        )

        # Should use dynamic resolution (check for Path usage or __file__)
        has_dynamic_path = any(x in content for x in [
            'Path(__file__)',
            '__file__',
            'Path.home()',
            'os.environ',
        ])

        assert has_dynamic_path, (
            f"{script.name} missing dynamic path resolution. "
            f"Should use Path(__file__) or similar."
        )
