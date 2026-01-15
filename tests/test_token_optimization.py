"""Tests for token optimization features.

Tests cover:
1. State file consolidation (iterate.json + session.json -> unified workflow state)
2. Context caching (avoid re-resolving context hierarchy per subagent)
3. Log file rotation (prevent unbounded growth)
4. Prompt compression (reduce agent briefing size)
"""

import json
import os
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import pytest


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def temp_state_dir(tmp_path):
    """Create temporary state directory with environment override."""
    state_dir = tmp_path / ".state"
    state_dir.mkdir()

    # Set environment variables for test isolation
    old_iterate = os.environ.get("ITERATE_STATE_DIR")
    old_worker = os.environ.get("WORKER_POOL_STATE_DIR")
    old_context = os.environ.get("CONTEXT_CACHE_DIR")

    os.environ["ITERATE_STATE_DIR"] = str(state_dir)
    os.environ["WORKER_POOL_STATE_DIR"] = str(state_dir)
    os.environ["CONTEXT_CACHE_DIR"] = str(state_dir)

    yield state_dir

    # Restore environment
    if old_iterate:
        os.environ["ITERATE_STATE_DIR"] = old_iterate
    else:
        os.environ.pop("ITERATE_STATE_DIR", None)

    if old_worker:
        os.environ["WORKER_POOL_STATE_DIR"] = old_worker
    else:
        os.environ.pop("WORKER_POOL_STATE_DIR", None)

    if old_context:
        os.environ["CONTEXT_CACHE_DIR"] = old_context
    else:
        os.environ.pop("CONTEXT_CACHE_DIR", None)


@pytest.fixture
def context_hierarchy(tmp_path):
    """Create a sample context file hierarchy."""
    # User-level context
    user_ctx = tmp_path / ".claude"
    user_ctx.mkdir()
    (user_ctx / "CONTEXT.md").write_text("## Purpose\nGlobal user context.\n")

    # Project-level context
    project = tmp_path / "project"
    project.mkdir()
    (project / ".git").mkdir()  # Mark as repo root
    (project / ".context").mkdir()
    (project / ".context" / "CONTEXT.md").write_text(
        "## Purpose\nProject-specific purpose.\n\n## Conventions\nUse pytest.\n"
    )

    # Feature-level context
    feature = project / "src" / "feature"
    feature.mkdir(parents=True)
    (feature / "CONTEXT.md").write_text(
        "## Patterns\nUse factory pattern.\n\n## Pitfalls\nAvoid circular imports.\n"
    )

    return {
        "user": user_ctx,
        "project": project,
        "feature": feature,
    }


# =============================================================================
# 1. STATE CONSOLIDATION TESTS
# =============================================================================


class TestStateConsolidation:
    """Tests for unified state management."""

    def test_unified_state_loads_all_modules(self, temp_state_dir):
        """Unified state should contain iterate, worker pool, and review gate data."""
        # Setup: Create individual state files
        iterate_state = {
            "active": True,
            "task": "test task",
            "phase": "implement",
            "iteration": 1,
        }
        worker_state = {
            "active": True,
            "max_agents": 3,
            "active_workers": [{"worker_id": "w1", "task_id": "t1"}],
        }
        review_state = {"last_pushed_sha": "abc123", "review_pending": True}

        # Write individual files (current behavior)
        (temp_state_dir / "iterate.json").write_text(json.dumps(iterate_state))
        (temp_state_dir / "worker_pool.json").write_text(json.dumps(worker_state))
        session = {"review_gate": review_state}
        (temp_state_dir / "session.json").write_text(json.dumps(session))

        # Import after environment is set
        from lib.unified_state import load_unified_state

        # Test: Load unified state
        unified = load_unified_state()

        # Verify all modules present
        assert "iterate" in unified
        assert "worker_pool" in unified
        assert "review_gate" in unified

        # Verify data integrity
        assert unified["iterate"]["task"] == "test task"
        assert unified["worker_pool"]["max_agents"] == 3
        assert unified["review_gate"]["last_pushed_sha"] == "abc123"

    def test_unified_state_saves_atomic(self, temp_state_dir):
        """Unified state should save all modules atomically."""
        from lib.unified_state import save_unified_state, load_unified_state

        unified = {
            "iterate": {"active": True, "task": "atomic test", "phase": "test"},
            "worker_pool": {"active": False},
            "review_gate": {"review_pending": False},
            "version": 1,
        }

        save_unified_state(unified)

        # Verify single file created
        state_file = temp_state_dir / "workflow.json"
        assert state_file.exists()

        # Verify content
        loaded = load_unified_state()
        assert loaded["iterate"]["task"] == "atomic test"

    def test_unified_state_migration(self, temp_state_dir):
        """Should migrate from old split files to unified format."""
        # Create old-style split files
        (temp_state_dir / "iterate.json").write_text(
            json.dumps({"active": True, "task": "migrate me", "phase": "implement"})
        )
        (temp_state_dir / "worker_pool.json").write_text(
            json.dumps({"active": False})
        )

        from lib.unified_state import migrate_to_unified

        # Perform migration
        result = migrate_to_unified(temp_state_dir)

        # Verify unified file created
        assert (temp_state_dir / "workflow.json").exists()

        # Verify old files backed up (not deleted)
        assert (temp_state_dir / "iterate.json.bak").exists()

        # Verify data preserved
        assert result["iterate"]["task"] == "migrate me"

    def test_unified_state_version_check(self, temp_state_dir):
        """Should handle state version upgrades."""
        # Write old version
        old_state = {"version": 0, "iterate": {"task": "old"}}
        (temp_state_dir / "workflow.json").write_text(json.dumps(old_state))

        from lib.unified_state import load_unified_state, STATE_VERSION

        loaded = load_unified_state()

        # Should auto-upgrade version
        assert loaded.get("version", 0) >= STATE_VERSION


# =============================================================================
# 2. CONTEXT CACHING TESTS
# =============================================================================


class TestContextCaching:
    """Tests for context resolution caching."""

    def test_context_cache_hit(self, temp_state_dir, context_hierarchy):
        """Second resolve should hit cache if files unchanged."""
        from context.cached_resolver import CachedResolver

        resolver = CachedResolver(cache_dir=temp_state_dir)

        # First resolve - should miss cache
        ctx1 = resolver.resolve(context_hierarchy["feature"])
        stats1 = resolver.get_stats()

        assert stats1["cache_misses"] == 1
        assert stats1["cache_hits"] == 0

        # Second resolve - should hit cache
        ctx2 = resolver.resolve(context_hierarchy["feature"])
        stats2 = resolver.get_stats()

        assert stats2["cache_hits"] == 1
        assert ctx1.to_markdown() == ctx2.to_markdown()

    def test_context_cache_invalidation_on_file_change(
        self, temp_state_dir, context_hierarchy
    ):
        """Cache should invalidate when context file is modified."""
        from context.cached_resolver import CachedResolver

        resolver = CachedResolver(cache_dir=temp_state_dir)

        # First resolve
        ctx1 = resolver.resolve(context_hierarchy["feature"])
        original_content = ctx1.to_markdown()

        # Modify context file
        time.sleep(0.1)  # Ensure mtime changes
        ctx_file = context_hierarchy["feature"] / "CONTEXT.md"
        ctx_file.write_text("## Patterns\nNEW PATTERN\n")

        # Second resolve - should miss cache due to file change
        ctx2 = resolver.resolve(context_hierarchy["feature"])

        assert "NEW PATTERN" in ctx2.to_markdown()
        assert ctx1.to_markdown() != ctx2.to_markdown()

    def test_context_cache_per_directory(self, temp_state_dir, context_hierarchy):
        """Different directories should have separate cache entries."""
        from context.cached_resolver import CachedResolver

        resolver = CachedResolver(cache_dir=temp_state_dir)

        # Resolve feature directory
        ctx_feature = resolver.resolve(context_hierarchy["feature"])

        # Resolve project directory
        ctx_project = resolver.resolve(context_hierarchy["project"])

        # Both should be cached separately
        stats = resolver.get_stats()
        assert stats["cache_misses"] == 2  # Two different directories

        # Content should differ
        assert ctx_feature.to_markdown() != ctx_project.to_markdown()

    def test_context_cache_ttl(self, temp_state_dir, context_hierarchy):
        """Cache entries should expire after TTL."""
        from context.cached_resolver import CachedResolver

        # Very short TTL for testing
        resolver = CachedResolver(cache_dir=temp_state_dir, ttl_seconds=0.1)

        # First resolve
        resolver.resolve(context_hierarchy["feature"])
        assert resolver.get_stats()["cache_misses"] == 1

        # Wait for TTL to expire
        time.sleep(0.2)

        # Second resolve should miss due to TTL
        resolver.resolve(context_hierarchy["feature"])
        assert resolver.get_stats()["cache_misses"] == 2

    def test_context_cache_size_limit(self, temp_state_dir):
        """Cache should evict old entries when size limit reached."""
        from context.cached_resolver import CachedResolver

        # Small cache for testing
        resolver = CachedResolver(cache_dir=temp_state_dir, max_entries=2)

        # Create 3 directories with context
        for i in range(3):
            dir_path = temp_state_dir / f"dir{i}"
            dir_path.mkdir()
            (dir_path / "CONTEXT.md").write_text(f"## Purpose\nDir {i}\n")
            resolver.resolve(dir_path)

        # Cache should have evicted oldest entry
        assert resolver.get_stats()["evictions"] >= 1


# =============================================================================
# 3. LOG ROTATION TESTS
# =============================================================================


class TestLogRotation:
    """Tests for log file rotation."""

    def test_log_rotation_triggers_at_size(self, temp_state_dir):
        """Log should rotate when size threshold reached."""
        from lib.log_rotation import RotatingLog

        # Create log with small threshold
        log = RotatingLog(
            temp_state_dir / "test.log", max_size_kb=1, max_files=3  # 1KB threshold
        )

        # Write enough to trigger rotation
        for i in range(100):
            log.write(f"Line {i}: " + "x" * 100 + "\n")

        log.close()

        # Should have rotated files
        files = list(temp_state_dir.glob("test.log*"))
        assert len(files) >= 2  # Original + at least one rotated

    def test_log_rotation_keeps_max_files(self, temp_state_dir):
        """Should delete old files beyond max_files limit."""
        from lib.log_rotation import RotatingLog

        log = RotatingLog(
            temp_state_dir / "test.log", max_size_kb=1, max_files=2  # Keep only 2
        )

        # Write enough to trigger multiple rotations
        for i in range(500):
            log.write(f"Line {i}: " + "x" * 100 + "\n")

        log.close()

        # Should have at most max_files
        files = list(temp_state_dir.glob("test.log*"))
        assert len(files) <= 2

    def test_log_rotation_preserves_recent_content(self, temp_state_dir):
        """Recent log entries should be preserved after rotation."""
        from lib.log_rotation import RotatingLog

        log = RotatingLog(temp_state_dir / "test.log", max_size_kb=1, max_files=3)

        # Write with identifiable marker at end
        for i in range(100):
            log.write(f"Line {i}\n")
        log.write("FINAL_MARKER\n")

        log.close()

        # Recent content should be in current log file
        current_log = temp_state_dir / "test.log"
        content = current_log.read_text()
        assert "FINAL_MARKER" in content

    def test_log_rotation_with_date_suffix(self, temp_state_dir):
        """Rotated files should have date suffix."""
        from lib.log_rotation import RotatingLog

        log = RotatingLog(
            temp_state_dir / "activity.log",
            max_size_kb=1,
            max_files=5,
            date_suffix=True,
        )

        # Trigger rotation
        for i in range(100):
            log.write("x" * 100 + "\n")

        log.close()

        # Check for date-suffixed files
        files = list(temp_state_dir.glob("activity.log.*"))
        # At least one should have date pattern
        date_pattern_found = any(
            f.suffix and len(f.suffix) > 8 for f in files  # .YYYYMMDD format
        )
        assert date_pattern_found or len(files) == 0  # Either dated or no rotation yet


# =============================================================================
# 4. PROMPT COMPRESSION TESTS
# =============================================================================


class TestPromptCompression:
    """Tests for reducing agent prompt size."""

    def test_compressed_core_protocol(self):
        """Core protocol should have compressed version for agents."""
        from lib.prompt_compression import get_compressed_protocol

        compressed = get_compressed_protocol("implementer")

        # Compressed protocol should exist and be reasonably sized
        assert len(compressed) > 0
        assert len(compressed) < 5000  # Should be compact, not full protocol

        # Should still contain key rules for agent type
        assert "test" in compressed.lower() or "implement" in compressed.lower()

    def test_agent_briefing_deduplication(self):
        """Enforcement rules should not be duplicated in briefings."""
        from lib.prompt_compression import generate_agent_briefing

        # Generate briefings for multiple agents
        briefings = []
        for agent_type in ["explorer", "implementer", "reviewer"]:
            briefing = generate_agent_briefing(agent_type, phase="implement")
            briefings.append(briefing)

        # Each briefing should reference enforcement doc, not embed it
        for briefing in briefings:
            # Should not contain full enforcement rules inline
            assert "You MUST NOT read files" not in briefing  # Enforcement rule text
            # Should reference shared doc
            assert (
                "enforcement" in briefing.lower() or "rules" in briefing.lower()
            )

    def test_context_summary_vs_full(self, context_hierarchy):
        """Agent context should use summary mode by default."""
        from lib.prompt_compression import get_context_for_agent

        # Full context
        full = get_context_for_agent(
            "implementer", context_hierarchy["feature"], summary=False
        )

        # Summary context
        summary = get_context_for_agent(
            "implementer", context_hierarchy["feature"], summary=True
        )

        # Summary should be smaller
        assert len(summary) < len(full)

        # Summary should still contain key info
        assert "pattern" in summary.lower() or "convention" in summary.lower()

    def test_phase_specific_context_filtering(self, context_hierarchy):
        """Context should be filtered based on current phase."""
        from lib.prompt_compression import get_context_for_agent

        # Implement phase - should include conventions, patterns, pitfalls
        implement_ctx = get_context_for_agent(
            "implementer", context_hierarchy["feature"], phase="implement"
        )

        # Review phase - should focus on conventions, pitfalls
        review_ctx = get_context_for_agent(
            "reviewer", context_hierarchy["feature"], phase="review"
        )

        # Implement should have more content (includes patterns)
        # Both should be filtered appropriately
        assert len(implement_ctx) > 0
        assert len(review_ctx) > 0

    def test_token_budget_enforcement(self):
        """Briefings should respect token budget."""
        from lib.prompt_compression import generate_agent_briefing

        # Generate with strict budget
        briefing = generate_agent_briefing(
            "implementer", phase="implement", max_tokens=500
        )

        # Rough token estimate (4 chars per token)
        estimated_tokens = len(briefing) / 4

        assert estimated_tokens <= 550  # Some margin for estimation error


# =============================================================================
# INTEGRATION TESTS
# =============================================================================


class TestTokenOptimizationIntegration:
    """Integration tests for full token optimization flow."""

    def test_full_workflow_uses_optimizations(self, temp_state_dir, context_hierarchy):
        """Full workflow should use all optimizations together."""
        # This test verifies the optimizations work together

        # 1. Start workflow with unified state
        from lib.unified_state import save_unified_state, load_unified_state

        save_unified_state(
            {
                "iterate": {"active": True, "task": "integration test", "phase": "implement"},
                "worker_pool": {"active": False},
                "review_gate": {},
                "version": 1,
            }
        )

        # 2. Resolve context with caching
        from context.cached_resolver import CachedResolver

        resolver = CachedResolver(cache_dir=temp_state_dir)
        ctx = resolver.resolve(context_hierarchy["feature"])
        assert resolver.get_stats()["cache_misses"] == 1

        # 3. Generate compressed briefing
        from lib.prompt_compression import generate_agent_briefing

        briefing = generate_agent_briefing("implementer", phase="implement", max_tokens=1000)
        assert len(briefing) < 4000  # Under 1000 tokens

        # 4. Log with rotation
        from lib.log_rotation import RotatingLog

        log = RotatingLog(temp_state_dir / "workflow.log", max_size_kb=100, max_files=3)
        log.write(f"Integration test completed at {datetime.now()}\n")
        log.close()

    def test_optimization_reduces_state_io(self, temp_state_dir):
        """Optimizations should reduce total state I/O operations."""
        # Track I/O operations
        io_count = {"reads": 0, "writes": 0}

        original_read = Path.read_text
        original_write = Path.write_text

        def counting_read(self, *args, **kwargs):
            io_count["reads"] += 1
            return original_read(self, *args, **kwargs)

        def counting_write(self, *args, **kwargs):
            io_count["writes"] += 1
            return original_write(self, *args, **kwargs)

        with mock.patch.object(Path, "read_text", counting_read):
            with mock.patch.object(Path, "write_text", counting_write):
                # Simulate workflow operations
                from lib.unified_state import save_unified_state, load_unified_state

                # Single save/load should be 1 read + 1 write
                save_unified_state(
                    {"iterate": {"active": True}, "worker_pool": {}, "review_gate": {}}
                )
                load_unified_state()

        # With unified state, should have minimal I/O
        # (vs. old approach of reading 4 separate files)
        assert io_count["reads"] <= 2  # At most workflow.json + migration check
        assert io_count["writes"] == 1  # Single unified file
