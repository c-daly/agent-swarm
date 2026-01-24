#!/usr/bin/env python3
"""Tests for auto-distillation trigger in session-end hook."""

import json
import importlib.util
from pathlib import Path
from unittest.mock import patch
import sys

# Add paths BEFORE loading the module (required for imports in session-end.py)
sys.path.insert(0, str(Path(__file__).parent.parent / "context"))
sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

# Load session-end module (has hyphen, can't use normal import)
HOOKS_DIR = Path(__file__).parent.parent / "hooks"
spec = importlib.util.spec_from_file_location("session_end", HOOKS_DIR / "session-end.py")
session_end = importlib.util.module_from_spec(spec)

# Now load the module
spec.loader.exec_module(session_end)

check_and_distill = session_end.check_and_distill


class TestAutoDistillation:
    """Test auto-distillation trigger."""

    def test_check_and_distill_below_threshold(self, tmp_path: Path):
        """Should not distill when episode count is below threshold."""
        # Setup: create episodes file with 5 episodes (below default 10)
        context_dir = tmp_path / ".context"
        context_dir.mkdir()
        episodes_file = context_dir / "EPISODES.md"
        
        episodes_content = "# Episodes: test\n\n"
        for i in range(5):
            episodes_content += f"""## Session: 2026-01-{20+i:02d}T10:00:00
- **Task**: Task {i}
- **Outcome**: success
- **Learnings**:
  - Learning {i}

"""
        episodes_file.write_text(episodes_content)
        
        result = check_and_distill(tmp_path)
        
        assert result["distilled"] is False
        assert result["episode_count"] == 5

    def test_check_and_distill_at_threshold(self, tmp_path: Path):
        """Should distill when episode count equals threshold."""
        # Setup: create episodes file with 10 episodes (equals default threshold)
        context_dir = tmp_path / ".context"
        context_dir.mkdir()
        episodes_file = context_dir / "EPISODES.md"
        
        episodes_content = "# Episodes: test\n\n"
        for i in range(10):
            episodes_content += f"""## Session: 2026-01-{10+i:02d}T10:00:00
- **Task**: Task {i}
- **Outcome**: success
- **Learnings**:
  - Learning {i}

"""
        episodes_file.write_text(episodes_content)
        
        result = check_and_distill(tmp_path)
        
        assert result["distilled"] is True
        assert result["episode_count"] == 10
        assert "pattern_count" in result

    def test_check_and_distill_above_threshold(self, tmp_path: Path):
        """Should distill when episode count exceeds threshold."""
        # Setup: create episodes file with 15 episodes
        context_dir = tmp_path / ".context"
        context_dir.mkdir()
        episodes_file = context_dir / "EPISODES.md"
        
        episodes_content = "# Episodes: test\n\n"
        for i in range(15):
            episodes_content += f"""## Session: 2026-01-{i+1:02d}T10:00:00
- **Task**: Task {i}
- **Outcome**: success
- **Learnings**:
  - Important learning {i}

"""
        episodes_file.write_text(episodes_content)
        
        result = check_and_distill(tmp_path)
        
        assert result["distilled"] is True
        assert result["episode_count"] == 15

    def test_check_and_distill_custom_threshold(self, tmp_path: Path):
        """Should respect custom threshold."""
        # Setup: create 5 episodes
        context_dir = tmp_path / ".context"
        context_dir.mkdir()
        episodes_file = context_dir / "EPISODES.md"
        
        episodes_content = "# Episodes: test\n\n"
        for i in range(5):
            episodes_content += f"""## Session: 2026-01-{20+i:02d}T10:00:00
- **Task**: Task {i}
- **Outcome**: success
- **Learnings**:
  - Learning {i}

"""
        episodes_file.write_text(episodes_content)
        
        # With threshold of 3, should trigger distillation
        result = check_and_distill(tmp_path, threshold=3)
        
        assert result["distilled"] is True
        assert result["episode_count"] == 5

    def test_check_and_distill_no_episodes_file(self, tmp_path: Path):
        """Should handle missing episodes file gracefully."""
        result = check_and_distill(tmp_path)
        
        # When no episodes file, EpisodeStore creates one with 0 episodes
        assert result["distilled"] is False
        assert result["episode_count"] == 0

    def test_check_and_distill_timeout_handling(self, tmp_path: Path):
        """Should handle timeout gracefully."""
        # Setup episodes
        context_dir = tmp_path / ".context"
        context_dir.mkdir()
        episodes_file = context_dir / "EPISODES.md"
        
        episodes_content = "# Episodes: test\n\n"
        for i in range(15):
            episodes_content += f"""## Session: 2026-01-{i+1:02d}T10:00:00
- **Task**: Task {i}
- **Outcome**: success
- **Learnings**:
  - Learning {i}

"""
        episodes_file.write_text(episodes_content)
        
        # Mock trigger_distillation to raise TimeoutError
        with patch.object(session_end, 'trigger_distillation') as mock_distill:
            mock_distill.side_effect = TimeoutError("Distillation timed out")
            
            result = check_and_distill(tmp_path)
            
            assert result["distilled"] is False
            assert "error" in result

    def test_check_and_distill_exception_handling(self, tmp_path: Path):
        """Should handle exceptions gracefully."""
        # Mock EpisodeStore to raise an exception
        with patch.object(session_end, 'EpisodeStore') as mock_store:
            mock_store.side_effect = Exception("Something went wrong")
            
            result = check_and_distill(tmp_path)
            
            assert result["distilled"] is False
            assert "error" in result


class TestSessionEndIntegration:
    """Test session-end hook integration with auto-distillation."""

    def test_main_includes_distillation_message(self, tmp_path: Path, monkeypatch):
        """Should include distillation result in systemMessage."""
        # Setup: create episodes exceeding threshold
        context_dir = tmp_path / ".context"
        context_dir.mkdir()
        episodes_file = context_dir / "EPISODES.md"
        
        episodes_content = "# Episodes: test\n\n"
        for i in range(12):
            episodes_content += f"""## Session: 2026-01-{i+1:02d}T10:00:00
- **Task**: Task {i}
- **Outcome**: success
- **Learnings**:
  - Learning {i}

"""
        episodes_file.write_text(episodes_content)
        
        # Mock other functions that might fail
        with patch.object(session_end, 'generate_dashboard', return_value={"success": True, "message": "Dashboard generated"}):
            with patch.object(session_end, 'compress_old_session_files', return_value={"compressed": 0}):
                with patch.object(session_end, 'check_and_distill', return_value={"distilled": True, "pattern_count": 5, "episode_count": 12}):
                    # Capture output
                    import io
                    captured_output = io.StringIO()
                    monkeypatch.setattr(sys, 'stdout', captured_output)
                    monkeypatch.setattr(sys, 'stdin', io.StringIO('{}'))
                    
                    session_end.main()
                    
                    output = captured_output.getvalue()
                    result = json.loads(output)
                    
                    assert "Distilled 12 episodes into 5 patterns" in result["systemMessage"]
