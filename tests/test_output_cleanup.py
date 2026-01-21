"""Tests for output cleanup system."""
import pytest
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import os


class TestFindStaleOutputs:
    """Tests for finding stale output files."""

    def test_find_stale_outputs_finds_old_files(self):
        """find_stale_outputs should find files older than threshold."""
        from lib.output_cleanup import find_stale_outputs

        with TemporaryDirectory() as tmpdir:
            # Create test directory structure
            tasks_dir = Path(tmpdir) / "claude" / "session1" / "tasks"
            tasks_dir.mkdir(parents=True)

            # Create an old file
            old_file = tasks_dir / "agent1.output"
            old_file.write_text("old data")
            
            # Set modification time to 48 hours ago
            old_time = time.time() - (48 * 3600)
            os.utime(old_file, (old_time, old_time))

            # Find stale files (older than 24 hours)
            # Override search path to use tmpdir
            stale_files = find_stale_outputs(max_age_hours=24, base_path=tmpdir)

            assert len(stale_files) == 1
            assert old_file in stale_files

    def test_find_stale_outputs_ignores_recent_files(self):
        """find_stale_outputs should not return files within threshold."""
        from lib.output_cleanup import find_stale_outputs

        with TemporaryDirectory() as tmpdir:
            tasks_dir = Path(tmpdir) / "claude" / "session1" / "tasks"
            tasks_dir.mkdir(parents=True)

            # Create a recent file
            recent_file = tasks_dir / "agent2.output"
            recent_file.write_text("recent data")

            # Find stale files (older than 24 hours)
            stale_files = find_stale_outputs(max_age_hours=24, base_path=tmpdir)

            assert len(stale_files) == 0

    def test_find_stale_outputs_handles_missing_directory(self):
        """find_stale_outputs should handle missing directories gracefully."""
        from lib.output_cleanup import find_stale_outputs

        # Use a non-existent path
        stale_files = find_stale_outputs(max_age_hours=24, base_path="/nonexistent/path")

        assert stale_files == []

    def test_find_stale_outputs_only_finds_output_files(self):
        """find_stale_outputs should only find .output files, not other files."""
        from lib.output_cleanup import find_stale_outputs

        with TemporaryDirectory() as tmpdir:
            tasks_dir = Path(tmpdir) / "claude" / "session1" / "tasks"
            tasks_dir.mkdir(parents=True)

            # Create old .output file
            output_file = tasks_dir / "agent1.output"
            output_file.write_text("output data")

            # Create old non-.output file
            other_file = tasks_dir / "agent1.log"
            other_file.write_text("log data")

            # Make both old
            old_time = time.time() - (48 * 3600)
            os.utime(output_file, (old_time, old_time))
            os.utime(other_file, (old_time, old_time))

            stale_files = find_stale_outputs(max_age_hours=24, base_path=tmpdir)

            assert len(stale_files) == 1
            assert output_file in stale_files
            assert other_file not in stale_files

    def test_find_stale_outputs_avoids_state_directory(self):
        """find_stale_outputs should never look in .state directories."""
        from lib.output_cleanup import find_stale_outputs

        with TemporaryDirectory() as tmpdir:
            # Create .state directory with old file
            state_dir = Path(tmpdir) / ".state"
            state_dir.mkdir(parents=True)
            state_file = state_dir / "something.output"
            state_file.write_text("state data")

            old_time = time.time() - (48 * 3600)
            os.utime(state_file, (old_time, old_time))

            # Should not find files in .state
            stale_files = find_stale_outputs(max_age_hours=24, base_path=tmpdir)

            assert len(stale_files) == 0


class TestCleanupStaleOutputs:
    """Tests for cleanup function."""

    def test_cleanup_stale_outputs_deletes_old_files(self):
        """cleanup_stale_outputs should delete old files."""
        from lib.output_cleanup import cleanup_stale_outputs

        with TemporaryDirectory() as tmpdir:
            tasks_dir = Path(tmpdir) / "claude" / "session1" / "tasks"
            tasks_dir.mkdir(parents=True)

            # Create old file
            old_file = tasks_dir / "agent1.output"
            old_file.write_text("old data")

            old_time = time.time() - (48 * 3600)
            os.utime(old_file, (old_time, old_time))

            # Clean up
            result = cleanup_stale_outputs(max_age_hours=24, dry_run=False, base_path=tmpdir)

            assert result["files_deleted"] == 1
            assert result["space_reclaimed"] > 0
            assert not old_file.exists()

    def test_cleanup_stale_outputs_preserves_recent_files(self):
        """cleanup_stale_outputs should not delete recent files."""
        from lib.output_cleanup import cleanup_stale_outputs

        with TemporaryDirectory() as tmpdir:
            tasks_dir = Path(tmpdir) / "claude" / "session1" / "tasks"
            tasks_dir.mkdir(parents=True)

            # Create recent file
            recent_file = tasks_dir / "agent2.output"
            recent_file.write_text("recent data")

            # Clean up
            result = cleanup_stale_outputs(max_age_hours=24, dry_run=False, base_path=tmpdir)

            assert result["files_deleted"] == 0
            assert result["space_reclaimed"] == 0
            assert recent_file.exists()

    def test_cleanup_stale_outputs_dry_run_does_not_delete(self):
        """cleanup_stale_outputs in dry_run mode should not delete files."""
        from lib.output_cleanup import cleanup_stale_outputs

        with TemporaryDirectory() as tmpdir:
            tasks_dir = Path(tmpdir) / "claude" / "session1" / "tasks"
            tasks_dir.mkdir(parents=True)

            # Create old file
            old_file = tasks_dir / "agent1.output"
            old_file.write_text("old data")

            old_time = time.time() - (48 * 3600)
            os.utime(old_file, (old_time, old_time))

            # Dry run
            result = cleanup_stale_outputs(max_age_hours=24, dry_run=True, base_path=tmpdir)

            assert result["files_deleted"] == 1
            assert result["space_reclaimed"] > 0
            assert old_file.exists()  # Should still exist

    def test_cleanup_stale_outputs_handles_deletion_errors(self):
        """cleanup_stale_outputs should continue even if some deletions fail."""
        from lib.output_cleanup import cleanup_stale_outputs

        with TemporaryDirectory() as tmpdir:
            tasks_dir = Path(tmpdir) / "claude" / "session1" / "tasks"
            tasks_dir.mkdir(parents=True)

            # Create two old files
            old_file1 = tasks_dir / "agent1.output"
            old_file1.write_text("old data 1")
            old_file2 = tasks_dir / "agent2.output"
            old_file2.write_text("old data 2")

            old_time = time.time() - (48 * 3600)
            os.utime(old_file1, (old_time, old_time))
            os.utime(old_file2, (old_time, old_time))

            # Make first file read-only to cause deletion error
            old_file1.chmod(0o444)
            tasks_dir.chmod(0o555)

            # Try cleanup - should handle error gracefully
            try:
                result = cleanup_stale_outputs(max_age_hours=24, dry_run=False, base_path=tmpdir)
                # Should have attempted both files but may not have deleted the protected one
                assert isinstance(result["files_deleted"], int)
                assert isinstance(result["space_reclaimed"], int)
            finally:
                # Restore permissions for cleanup
                tasks_dir.chmod(0o755)
                old_file1.chmod(0o644)


class TestOutputSizeStats:
    """Tests for size statistics."""

    def test_get_output_size_stats_calculates_total_size(self):
        """get_output_size_stats should calculate total size of all output files."""
        from lib.output_cleanup import get_output_size_stats

        with TemporaryDirectory() as tmpdir:
            tasks_dir = Path(tmpdir) / "claude" / "session1" / "tasks"
            tasks_dir.mkdir(parents=True)

            # Create files with known sizes
            file1 = tasks_dir / "agent1.output"
            file1.write_text("a" * 1000)  # 1000 bytes

            file2 = tasks_dir / "agent2.output"
            file2.write_text("b" * 2000)  # 2000 bytes

            stats = get_output_size_stats(base_path=tmpdir)

            assert stats["total_files"] == 2
            assert stats["total_size_bytes"] == 3000
            assert stats["total_size_mb"] == pytest.approx(3000 / (1024 * 1024), rel=0.01)

    def test_get_output_size_stats_handles_empty_directory(self):
        """get_output_size_stats should handle empty directories."""
        from lib.output_cleanup import get_output_size_stats

        with TemporaryDirectory() as tmpdir:
            tasks_dir = Path(tmpdir) / "claude" / "session1" / "tasks"
            tasks_dir.mkdir(parents=True)

            stats = get_output_size_stats(base_path=tmpdir)

            assert stats["total_files"] == 0
            assert stats["total_size_bytes"] == 0
            assert stats["total_size_mb"] == 0.0

    def test_get_output_size_stats_handles_missing_directory(self):
        """get_output_size_stats should handle missing directories gracefully."""
        from lib.output_cleanup import get_output_size_stats

        stats = get_output_size_stats(base_path="/nonexistent/path")

        assert stats["total_files"] == 0
        assert stats["total_size_bytes"] == 0
        assert stats["total_size_mb"] == 0.0

    def test_get_output_size_stats_only_counts_output_files(self):
        """get_output_size_stats should only count .output files."""
        from lib.output_cleanup import get_output_size_stats

        with TemporaryDirectory() as tmpdir:
            tasks_dir = Path(tmpdir) / "claude" / "session1" / "tasks"
            tasks_dir.mkdir(parents=True)

            # Create .output file
            output_file = tasks_dir / "agent1.output"
            output_file.write_text("a" * 1000)

            # Create non-.output file
            other_file = tasks_dir / "agent1.log"
            other_file.write_text("b" * 2000)

            stats = get_output_size_stats(base_path=tmpdir)

            assert stats["total_files"] == 1
            assert stats["total_size_bytes"] == 1000
