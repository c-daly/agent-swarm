import os
import sys
import tempfile
from pathlib import Path

import pytest

# Add directories to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "hooks"))
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

# Create isolated state directory for tests BEFORE importing iterate_workflow
# This prevents tests from destroying production state (WORKFLOW.11 fix)
_test_state_dir = tempfile.mkdtemp(prefix="iterate_test_state_")
os.environ["ITERATE_STATE_DIR"] = _test_state_dir


@pytest.fixture(scope="session", autouse=True)
def cleanup_test_state_dir():
    """Clean up the test state directory after all tests complete."""
    yield
    # Cleanup after all tests
    import shutil
    if os.path.exists(_test_state_dir):
        shutil.rmtree(_test_state_dir, ignore_errors=True)
