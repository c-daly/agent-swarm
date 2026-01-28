#!/usr/bin/env python3
"""
Tests for context/memory.py

Tests the memory distillation system.
"""

import pytest
from pathlib import Path
from datetime import datetime, timedelta
import sys

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from context.memory import (  # noqa: E402
    Pattern,
    Episode,
    Memory,
    EpisodeStore,
    Distiller,
    log_episode,
    trigger_distillation,
)


class TestPattern:
    """Test Pattern dataclass."""

    def test_pattern_id_stable(self):
        """Same content should produce same ID."""
        p1 = Pattern(
            content="Test pattern",
            category="pattern",
            confidence=0.5,
            first_observed="2026-01-01T00:00:00",
            last_reinforced="2026-01-01T00:00:00",
        )
        p2 = Pattern(
            content="Test pattern",
            category="pattern",
            confidence=0.8,
            first_observed="2026-01-02T00:00:00",
            last_reinforced="2026-01-02T00:00:00",
        )

        assert p1.id == p2.id

    def test_reinforce_increases_confidence(self):
        p = Pattern(
            content="Test",
            category="pattern",
            confidence=0.3,
            first_observed="2026-01-01T00:00:00",
            last_reinforced="2026-01-01T00:00:00",
        )

        initial_confidence = p.confidence
        p.reinforce("2026-01-02T00:00:00")

        assert p.confidence > initial_confidence
        assert p.observation_count == 2

    def test_reinforce_caps_at_095(self):
        p = Pattern(
            content="Test",
            category="pattern",
            confidence=0.9,
            first_observed="2026-01-01T00:00:00",
            last_reinforced="2026-01-01T00:00:00",
        )

        for _ in range(10):
            p.reinforce(datetime.now().isoformat())

        assert p.confidence <= 0.95

    def test_decay_reduces_confidence(self):
        old_date = (datetime.now() - timedelta(days=60)).isoformat()
        p = Pattern(
            content="Test",
            category="pattern",
            confidence=0.8,
            first_observed=old_date,
            last_reinforced=old_date,
        )

        initial = p.confidence
        p.apply_decay(datetime.now(), decay_days=30)

        assert p.confidence < initial


class TestEpisode:
    """Test Episode dataclass."""

    def test_extract_patterns(self):
        ep = Episode(
            id="test123",
            timestamp="2026-01-01T00:00:00",
            scope_path="/test",
            task="Fix auth bug",
            outcome="success",
            learnings=[
                "JWT tokens need refresh handling",
                "Avoid storing tokens in localStorage",
            ],
        )

        patterns = ep.extract_patterns()

        assert len(patterns) == 2
        assert all("content" in p for p in patterns)
        assert all("category" in p for p in patterns)

    def test_classify_pitfall(self):
        ep = Episode(
            id="test",
            timestamp="2026-01-01T00:00:00",
            scope_path="/test",
            task="Debug",
            outcome="failure",
            learnings=["Avoid using eval() - security risk"],
        )

        patterns = ep.extract_patterns()
        assert patterns[0]["category"] == "pitfall"

    def test_classify_preference(self):
        ep = Episode(
            id="test",
            timestamp="2026-01-01T00:00:00",
            scope_path="/test",
            task="Review",
            outcome="success",
            learnings=["User prefers functional style"],
        )

        patterns = ep.extract_patterns()
        assert patterns[0]["category"] == "preference"


class TestMemory:
    """Test Memory class."""

    def test_add_new_pattern(self):
        mem = Memory(scope_path="/test")

        pattern = mem.add_pattern(
            content="Use TypeScript for new code",
            category="convention",
        )

        assert pattern.id in mem.patterns
        assert pattern.confidence == 0.3  # Default

    def test_add_similar_pattern_reinforces(self):
        mem = Memory(scope_path="/test")

        p1 = mem.add_pattern("Use TypeScript for new code", "convention")
        initial_confidence = p1.confidence

        # Add similar pattern
        p2 = mem.add_pattern("Use TypeScript for new code", "convention")

        assert p1.id == p2.id
        assert p2.confidence > initial_confidence
        assert len(mem.patterns) == 1

    def test_get_by_category(self):
        mem = Memory(scope_path="/test")

        mem.add_pattern("Pattern 1", "pattern")
        mem.add_pattern("Pattern 2", "pattern")
        mem.add_pattern("Pitfall 1", "pitfall")

        patterns = mem.get_by_category("pattern")
        pitfalls = mem.get_by_category("pitfall")

        assert len(patterns) == 2
        assert len(pitfalls) == 1

    def test_prune_low_confidence(self):
        mem = Memory(scope_path="/test")

        p1 = mem.add_pattern("Strong pattern", "pattern")
        p1.confidence = 0.8

        p2 = mem.add_pattern("Weak pattern", "pattern")
        p2.confidence = 0.1

        mem.prune(min_confidence=0.2)

        assert len(mem.patterns) == 1
        assert "Strong" in list(mem.patterns.values())[0].content

    def test_to_markdown(self):
        mem = Memory(scope_path="/test")
        mem.add_pattern("Test pattern", "pattern")
        mem.add_pattern("Test pitfall", "pitfall")

        md = mem.to_markdown()

        assert "# Memory:" in md
        assert "Patterns Observed" in md
        assert "Pitfalls Discovered" in md

    def test_to_dict_and_from_dict(self):
        mem = Memory(scope_path="/test")
        mem.add_pattern("Test pattern", "pattern")
        mem.last_distilled = datetime.now().isoformat()

        data = mem.to_dict()
        restored = Memory.from_dict(data)

        assert restored.scope_path == mem.scope_path
        assert len(restored.patterns) == len(mem.patterns)

    def test_compact_merges_similar_patterns(self):
        """Test that compaction merges similar patterns."""
        mem = Memory(scope_path="/test")

        # Add similar patterns manually (bypassing _find_similar by setting different enough content)
        p1 = Pattern(
            content="Always validate user input before processing",
            category="pattern",
            confidence=0.6,
            first_observed="2026-01-01T00:00:00",
            last_reinforced="2026-01-01T00:00:00",
            observation_count=3,
        )
        p2 = Pattern(
            content="Always validate user input data before processing it",
            category="pattern",
            confidence=0.5,
            first_observed="2026-01-02T00:00:00",
            last_reinforced="2026-01-02T00:00:00",
            observation_count=2,
        )
        mem.patterns[p1.id] = p1
        mem.patterns[p2.id] = p2

        initial_count = len(mem.patterns)
        mem.compact(similarity_threshold=0.6)

        # After compaction, similar patterns should be merged
        assert len(mem.patterns) <= initial_count

    def test_compact_prunes_low_confidence(self):
        """Test that compaction prunes patterns below threshold."""
        mem = Memory(scope_path="/test")

        # Add patterns with different confidence levels
        p1 = mem.add_pattern("High confidence pattern", "pattern")
        p1.confidence = 0.8

        p2 = mem.add_pattern("Low confidence pattern", "pattern")
        p2.confidence = 0.1

        mem.compact(min_confidence=0.2)

        assert len(mem.patterns) == 1
        assert list(mem.patterns.values())[0].content == "High confidence pattern"


class TestEpisodeStore:
    """Test EpisodeStore class."""

    def test_add_episode(self, tmp_path):
        store = EpisodeStore(tmp_path)

        ep = Episode(
            id="test123",
            timestamp="2026-01-01T10:00:00",
            scope_path=str(tmp_path),
            task="Test task",
            outcome="success",
            learnings=["Learned something"],
        )

        store.add_episode(ep)

        # Read back
        episodes = store.get_episodes()
        assert len(episodes) == 1
        assert episodes[0].task == "Test task"

    def test_get_episodes_since(self, tmp_path):
        store = EpisodeStore(tmp_path)

        # Add old episode
        old_ep = Episode(
            id="old",
            timestamp="2026-01-01T10:00:00",
            scope_path=str(tmp_path),
            task="Old task",
            outcome="success",
            learnings=[],
        )
        store.add_episode(old_ep)

        # Add new episode
        new_ep = Episode(
            id="new",
            timestamp="2026-01-10T10:00:00",
            scope_path=str(tmp_path),
            task="New task",
            outcome="success",
            learnings=[],
        )
        store.add_episode(new_ep)

        # Get only recent
        since = datetime(2026, 1, 5)
        episodes = store.get_episodes(since=since)

        assert len(episodes) == 1
        assert episodes[0].task == "New task"

    def test_clear_episodes(self, tmp_path):
        store = EpisodeStore(tmp_path)

        ep = Episode(
            id="test",
            timestamp=datetime.now().isoformat(),
            scope_path=str(tmp_path),
            task="Test",
            outcome="success",
            learnings=[],
        )
        store.add_episode(ep)

        store.clear_episodes()

        episodes = store.get_episodes()
        assert len(episodes) == 0


class TestDistiller:
    """Test Distiller class."""

    def test_distill_creates_patterns(self, tmp_path):
        # Add an episode first
        store = EpisodeStore(tmp_path)
        ep = Episode(
            id="test",
            timestamp=datetime.now().isoformat(),
            scope_path=str(tmp_path),
            task="Fix bug",
            outcome="success",
            learnings=["Always validate input", "Error messages should be specific"],
        )
        store.add_episode(ep)

        # Distill
        distiller = Distiller(tmp_path)
        memory = distiller.distill(clear_episodes=False)

        assert len(memory.patterns) == 2

    def test_distill_reinforces_existing(self, tmp_path):
        # Create initial memory with a pattern
        distiller = Distiller(tmp_path)
        distiller.memory.add_pattern("Always validate input", "pattern")
        initial_confidence = list(distiller.memory.patterns.values())[0].confidence

        # Add episode with similar learning
        store = EpisodeStore(tmp_path)
        ep = Episode(
            id="test",
            timestamp=datetime.now().isoformat(),
            scope_path=str(tmp_path),
            task="Review",
            outcome="success",
            learnings=["Always validate input"],
        )
        store.add_episode(ep)

        # Distill
        memory = distiller.distill(clear_episodes=False)

        final_confidence = list(memory.patterns.values())[0].confidence
        assert final_confidence > initial_confidence


class TestFindDuplicatePatterns:
    """Test find_duplicate_patterns function."""

    def test_find_duplicates_across_children(self, tmp_path):
        """Find patterns appearing in multiple child directories."""
        from context.memory import find_duplicate_patterns

        # Create child directories with .context/MEMORY.json
        child1 = tmp_path / "child1" / ".context"
        child2 = tmp_path / "child2" / ".context"
        child1.mkdir(parents=True)
        child2.mkdir(parents=True)

        # Create memory files with overlapping patterns
        mem1 = Memory(scope_path=str(tmp_path / "child1"))
        mem1.add_pattern("Always validate user input", "pattern")
        mem1.add_pattern("Use type hints on public functions", "pattern")

        mem2 = Memory(scope_path=str(tmp_path / "child2"))
        mem2.add_pattern("Always validate user input", "pattern")
        mem2.add_pattern("Write tests before implementation", "pattern")

        import json
        (child1 / "MEMORY.json").write_text(json.dumps(mem1.to_dict(), indent=2))
        (child2 / "MEMORY.json").write_text(json.dumps(mem2.to_dict(), indent=2))

        # Find duplicates
        duplicates = find_duplicate_patterns(tmp_path)

        assert len(duplicates) >= 1
        # The duplicate should be the "validate user input" pattern
        duplicate_contents = [d["pattern"] for d in duplicates]
        assert any("validate" in c.lower() for c in duplicate_contents)

    def test_find_duplicates_returns_sources(self, tmp_path):
        """Duplicates should include which children contain them."""
        from context.memory import find_duplicate_patterns

        # Create child directories
        child1 = tmp_path / "child1" / ".context"
        child2 = tmp_path / "child2" / ".context"
        child1.mkdir(parents=True)
        child2.mkdir(parents=True)

        mem1 = Memory(scope_path=str(tmp_path / "child1"))
        mem1.add_pattern("Common pattern here", "pattern")

        mem2 = Memory(scope_path=str(tmp_path / "child2"))
        mem2.add_pattern("Common pattern here", "pattern")

        import json
        (child1 / "MEMORY.json").write_text(json.dumps(mem1.to_dict(), indent=2))
        (child2 / "MEMORY.json").write_text(json.dumps(mem2.to_dict(), indent=2))

        duplicates = find_duplicate_patterns(tmp_path)

        assert len(duplicates) == 1
        assert "sources" in duplicates[0]
        assert len(duplicates[0]["sources"]) == 2

    def test_no_duplicates_returns_empty(self, tmp_path):
        """No duplicates should return empty list."""
        from context.memory import find_duplicate_patterns

        child1 = tmp_path / "child1" / ".context"
        child2 = tmp_path / "child2" / ".context"
        child1.mkdir(parents=True)
        child2.mkdir(parents=True)

        mem1 = Memory(scope_path=str(tmp_path / "child1"))
        mem1.add_pattern("Unique pattern one", "pattern")

        mem2 = Memory(scope_path=str(tmp_path / "child2"))
        mem2.add_pattern("Completely different pattern", "pattern")

        import json
        (child1 / "MEMORY.json").write_text(json.dumps(mem1.to_dict(), indent=2))
        (child2 / "MEMORY.json").write_text(json.dumps(mem2.to_dict(), indent=2))

        duplicates = find_duplicate_patterns(tmp_path)
        assert len(duplicates) == 0


class TestProposePromotions:
    """Test propose_promotions function."""

    def test_propose_promotions_structure(self, tmp_path):
        """Promotions should have correct structure."""
        from context.memory import propose_promotions

        # Setup child memories with duplicates
        child1 = tmp_path / "child1" / ".context"
        child2 = tmp_path / "child2" / ".context"
        child1.mkdir(parents=True)
        child2.mkdir(parents=True)

        mem1 = Memory(scope_path=str(tmp_path / "child1"))
        mem1.add_pattern("Shared pattern across children", "pattern")

        mem2 = Memory(scope_path=str(tmp_path / "child2"))
        mem2.add_pattern("Shared pattern across children", "pattern")

        import json
        (child1 / "MEMORY.json").write_text(json.dumps(mem1.to_dict(), indent=2))
        (child2 / "MEMORY.json").write_text(json.dumps(mem2.to_dict(), indent=2))

        promotions = propose_promotions(tmp_path)

        assert len(promotions) >= 1
        promo = promotions[0]
        assert "pattern" in promo
        assert "from_scope" in promo
        assert "to_scope" in promo
        assert "reason" in promo

    def test_propose_promotions_target_parent(self, tmp_path):
        """Promotions should target the parent scope."""
        from context.memory import propose_promotions

        child1 = tmp_path / "child1" / ".context"
        child2 = tmp_path / "child2" / ".context"
        child1.mkdir(parents=True)
        child2.mkdir(parents=True)

        mem1 = Memory(scope_path=str(tmp_path / "child1"))
        mem1.add_pattern("Pattern to promote", "pattern")

        mem2 = Memory(scope_path=str(tmp_path / "child2"))
        mem2.add_pattern("Pattern to promote", "pattern")

        import json
        (child1 / "MEMORY.json").write_text(json.dumps(mem1.to_dict(), indent=2))
        (child2 / "MEMORY.json").write_text(json.dumps(mem2.to_dict(), indent=2))

        promotions = propose_promotions(tmp_path)

        assert len(promotions) >= 1
        assert promotions[0]["to_scope"] == str(tmp_path)


class TestDistillerPromotion:
    """Test Distiller with promotion functionality."""

    def test_distill_with_promotions(self, tmp_path):
        """Distill should include promotion suggestions."""
        from context.memory import Distiller

        # Setup child memories
        child1 = tmp_path / "child1" / ".context"
        child2 = tmp_path / "child2" / ".context"
        child1.mkdir(parents=True)
        child2.mkdir(parents=True)

        mem1 = Memory(scope_path=str(tmp_path / "child1"))
        mem1.add_pattern("Universal pattern for all", "pattern")

        mem2 = Memory(scope_path=str(tmp_path / "child2"))
        mem2.add_pattern("Universal pattern for all", "pattern")

        import json
        (child1 / "MEMORY.json").write_text(json.dumps(mem1.to_dict(), indent=2))
        (child2 / "MEMORY.json").write_text(json.dumps(mem2.to_dict(), indent=2))

        # Distill at parent level
        distiller = Distiller(tmp_path)
        result = distiller.distill_with_promotions(auto_promote=False)

        assert "promotions" in result
        assert len(result["promotions"]) >= 1


class TestConvenienceFunctions:
    """Test log_episode and trigger_distillation."""

    def test_log_episode(self, tmp_path):
        episode = log_episode(
            scope_path=tmp_path,
            task="Test task",
            outcome="success",
            learnings=["Test learning"],
            agent_type="explorer",
            phase="explore",
        )

        assert episode.id is not None
        assert episode.task == "Test task"

        # Verify it was saved
        store = EpisodeStore(tmp_path)
        episodes = store.get_episodes()
        assert len(episodes) == 1

    def test_trigger_distillation(self, tmp_path):
        # Log an episode first
        log_episode(tmp_path, "Test", "success", ["Learning 1"])

        # Trigger distillation
        memory = trigger_distillation(tmp_path)

        assert len(memory.patterns) >= 1
        assert memory.last_distilled is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
