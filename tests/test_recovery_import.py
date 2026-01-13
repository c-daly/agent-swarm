"""Test that recovery_mode.py can be imported without sys.path manipulation."""
import subprocess
import sys


def test_recovery_mode_import_isolated():
    """Test recovery_mode can import agent_state when lib/ not in sys.path."""
    # Simulate clean environment where lib/ is NOT in sys.path
    code = """
import sys
# Remove any agent-swarm paths
sys.path = [p for p in sys.path if 'agent-swarm' not in p or 'site-packages' in p]
# Add only lib/ itself (not parent)
sys.path.insert(0, '/home/fearsidhe/.claude/plugins/agent-swarm/lib')
# This should work now
import recovery_mode
print('SUCCESS')
"""
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True
    )

    assert result.returncode == 0, f"Import failed: {result.stderr}"
    assert "SUCCESS" in result.stdout, f"Did not see SUCCESS output: {result.stdout}"
