import sys
from pathlib import Path

# Add directories to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "hooks"))
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
