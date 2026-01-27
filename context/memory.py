#!/usr/bin/env python3
"""
Memory Distillation System

Transforms episodic memories (session logs) into semantic memories (patterns).
Implements confidence scoring, decay, and pruning for memory maintenance.
"""

import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional
import hashlib


@dataclass
class Pattern:
    """A learned pattern or observation."""

    content: str
    category: str  # 'pattern', 'pitfall', 'preference', 'approach'
    confidence: float  # 0.0 to 1.0
    first_observed: str  # ISO timestamp
    last_reinforced: str  # ISO timestamp
    observation_count: int = 1
    source_episodes: list[str] = field(default_factory=list)

    @property
    def id(self) -> str:
        """Generate stable ID from content."""
        return hashlib.md5(self.content.encode()).hexdigest()[:12]

    def reinforce(self, timestamp: str, episode_id: Optional[str] = None):
        """Reinforce this pattern with a new observation."""
        self.observation_count += 1
        self.last_reinforced = timestamp

        # Confidence increases with observations, asymptotically approaching 1.0
        self.confidence = min(0.95, self.confidence + (1 - self.confidence) * 0.2)

        if episode_id and episode_id not in self.source_episodes:
            self.source_episodes.append(episode_id)
            # Keep only recent episode references
            self.source_episodes = self.source_episodes[-10:]

    def apply_decay(self, current_time: datetime, decay_days: int = 30):
        """Apply time-based confidence decay."""
        last_reinforced = datetime.fromisoformat(self.last_reinforced)
        days_since = (current_time - last_reinforced).days

        if days_since > decay_days:
            decay_factor = 0.9 ** ((days_since - decay_days) / 7)  # Decay weekly
            self.confidence *= decay_factor


@dataclass
class Episode:
    """A single session record awaiting distillation."""

    id: str
    timestamp: str
    scope_path: str
    task: str
    outcome: str  # 'success', 'failure', 'partial'
    learnings: list[str] = field(default_factory=list)
    duration_minutes: int = 0
    agent_type: Optional[str] = None
    phase: Optional[str] = None

    def extract_patterns(self) -> list[dict]:
        """Extract potential patterns from this episode."""
        patterns = []

        for learning in self.learnings:
            # Classify the learning
            category = self._classify_learning(learning)
            patterns.append(
                {
                    "content": learning,
                    "category": category,
                    "source_episode": self.id,
                }
            )

        return patterns

    def _classify_learning(self, learning: str) -> str:
        """Classify a learning into a category."""
        learning_lower = learning.lower()

        if any(
            w in learning_lower for w in ["error", "fail", "broke", "wrong", "avoid"]
        ):
            return "pitfall"
        elif any(w in learning_lower for w in ["prefer", "like", "want", "should"]):
            return "preference"
        elif any(
            w in learning_lower for w in ["works", "effective", "success", "helped"]
        ):
            return "approach"
        else:
            return "pattern"


def _compute_similarity(content1: str, content2: str) -> float:
    """Compute Jaccard similarity between two strings."""
    words1 = set(content1.lower().split())
    words2 = set(content2.lower().split())
    
    intersection = len(words1 & words2)
    union = len(words1 | words2)
    
    if union == 0:
        return 0.0
    return intersection / union


@dataclass
class Memory:
    """Semantic memory store for a scope."""

    scope_path: str
    patterns: dict[str, Pattern] = field(default_factory=dict)  # id -> Pattern
    last_distilled: Optional[str] = None
    version: int = 1

    def add_pattern(
        self,
        content: str,
        category: str,
        confidence: float = 0.3,
        episode_id: Optional[str] = None,
    ) -> Pattern:
        """Add a new pattern or reinforce existing."""
        # Check for similar existing pattern
        existing = self._find_similar(content)

        if existing:
            existing.reinforce(datetime.now().isoformat(), episode_id)
            return existing

        # Create new pattern
        now = datetime.now().isoformat()
        pattern = Pattern(
            content=content,
            category=category,
            confidence=confidence,
            first_observed=now,
            last_reinforced=now,
            source_episodes=[episode_id] if episode_id else [],
        )
        self.patterns[pattern.id] = pattern
        return pattern

    def _find_similar(self, content: str, threshold: float = 0.8) -> Optional[Pattern]:
        """Find a similar existing pattern."""
        content_words = set(content.lower().split())

        for pattern in self.patterns.values():
            pattern_words = set(pattern.content.lower().split())

            # Jaccard similarity
            intersection = len(content_words & pattern_words)
            union = len(content_words | pattern_words)

            if union > 0 and intersection / union >= threshold:
                return pattern

        return None

    def apply_decay(self, decay_days: int = 30):
        """Apply decay to all patterns."""
        now = datetime.now()
        for pattern in self.patterns.values():
            pattern.apply_decay(now, decay_days)

    def prune(self, min_confidence: float = 0.2):
        """Remove patterns below confidence threshold."""
        to_remove = [
            pid
            for pid, pattern in self.patterns.items()
            if pattern.confidence < min_confidence
        ]
        for pid in to_remove:
            del self.patterns[pid]

    def compact(
        self,
        similarity_threshold: float = 0.7,
        min_confidence: float = 0.2,
    ):
        """
        Compact memory by merging similar patterns and pruning low confidence.
        
        Args:
            similarity_threshold: Merge patterns with similarity >= this value
            min_confidence: Remove patterns with confidence < this value
        """
        # First, merge similar patterns
        patterns_list = list(self.patterns.values())
        merged_ids = set()
        
        for i, p1 in enumerate(patterns_list):
            if p1.id in merged_ids:
                continue
            
            for j, p2 in enumerate(patterns_list[i + 1:], start=i + 1):
                if p2.id in merged_ids:
                    continue
                
                similarity = _compute_similarity(p1.content, p2.content)
                if similarity >= similarity_threshold:
                    # Merge p2 into p1 (keep the higher confidence one)
                    if p2.confidence > p1.confidence:
                        p1, p2 = p2, p1
                    
                    # Combine observation counts and confidence
                    p1.observation_count += p2.observation_count
                    p1.confidence = min(0.95, p1.confidence + (1 - p1.confidence) * 0.1)
                    
                    # Merge source episodes
                    for ep in p2.source_episodes:
                        if ep not in p1.source_episodes:
                            p1.source_episodes.append(ep)
                    p1.source_episodes = p1.source_episodes[-10:]
                    
                    merged_ids.add(p2.id)
        
        # Remove merged patterns
        for pid in merged_ids:
            if pid in self.patterns:
                del self.patterns[pid]
        
        # Then prune low confidence
        self.prune(min_confidence)

    def get_by_category(self, category: str) -> list[Pattern]:
        """Get all patterns in a category, sorted by confidence."""
        patterns = [p for p in self.patterns.values() if p.category == category]
        return sorted(patterns, key=lambda p: p.confidence, reverse=True)

    def to_markdown(self) -> str:
        """Export memory as markdown."""
        lines = [f"# Memory: {self.scope_path}", ""]

        categories = {
            "pattern": "Patterns Observed",
            "pitfall": "Pitfalls Discovered",
            "preference": "Preferences Inferred",
            "approach": "Effective Approaches",
        }

        for cat_key, cat_name in categories.items():
            patterns = self.get_by_category(cat_key)
            if patterns:
                lines.append(f"## {cat_name}")
                for p in patterns:
                    conf_label = (
                        "high"
                        if p.confidence > 0.7
                        else "medium" if p.confidence > 0.4 else "low"
                    )
                    lines.append(f"- {p.content}")
                    lines.append(
                        f"  Confidence: {conf_label} | Last reinforced: {p.last_reinforced[:10]}"
                    )
                lines.append("")

        if self.last_distilled:
            lines.append("---")
            lines.append(f"*Last distilled: {self.last_distilled[:10]}*")

        return "\n".join(lines)

    def to_dict(self) -> dict:
        """Export as dictionary for JSON serialization."""
        return {
            "scope_path": self.scope_path,
            "patterns": {pid: asdict(p) for pid, p in self.patterns.items()},
            "last_distilled": self.last_distilled,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Memory":
        """Load from dictionary."""
        memory = cls(scope_path=data["scope_path"])
        memory.last_distilled = data.get("last_distilled")
        memory.version = data.get("version", 1)

        for pid, pdata in data.get("patterns", {}).items():
            memory.patterns[pid] = Pattern(**pdata)

        return memory


class EpisodeStore:
    """Manages episode storage and retrieval."""

    def __init__(self, scope_path: Path):
        self.scope_path = scope_path
        self.episodes_file = self._find_or_create_episodes_file()

    def _find_or_create_episodes_file(self) -> Path:
        """Find or create the episodes file."""
        candidates = [
            self.scope_path / ".context" / "EPISODES.md",
            self.scope_path / ".claude" / "EPISODES.md",
            self.scope_path / "EPISODES.md",
        ]

        for candidate in candidates:
            if candidate.exists():
                return candidate

        # Create in .context directory
        episodes_dir = self.scope_path / ".context"
        episodes_dir.mkdir(exist_ok=True)
        episodes_file = episodes_dir / "EPISODES.md"
        episodes_file.write_text(f"# Episodes: {self.scope_path.name}\n\n")
        return episodes_file

    def add_episode(self, episode: Episode):
        """Add an episode to the store."""
        content = self.episodes_file.read_text()

        episode_md = self._episode_to_markdown(episode)
        content = content.rstrip() + "\n\n" + episode_md

        self.episodes_file.write_text(content)

    def _episode_to_markdown(self, episode: Episode) -> str:
        """Convert episode to markdown."""
        lines = [
            f"## Session: {episode.timestamp}",
            f"- **Task**: {episode.task}",
            f"- **Outcome**: {episode.outcome}",
        ]

        if episode.agent_type:
            lines.append(f"- **Agent**: {episode.agent_type}")
        if episode.phase:
            lines.append(f"- **Phase**: {episode.phase}")
        if episode.duration_minutes:
            lines.append(f"- **Duration**: {episode.duration_minutes} min")

        if episode.learnings:
            lines.append("- **Learnings**:")
            for learning in episode.learnings:
                lines.append(f"  - {learning}")

        return "\n".join(lines)

    def get_episodes(self, since: Optional[datetime] = None) -> list[Episode]:
        """Parse episodes from the store."""
        content = self.episodes_file.read_text()
        episodes = []

        # Parse markdown episodes
        session_pattern = r"## Session: (.+?)(?=\n## Session:|\Z)"
        for match in re.finditer(session_pattern, content, re.DOTALL):
            session_content = match.group(0)
            episode = self._parse_episode(session_content)
            if episode:
                if since is None or datetime.fromisoformat(episode.timestamp) >= since:
                    episodes.append(episode)

        return episodes

    def _parse_episode(self, content: str) -> Optional[Episode]:
        """Parse a single episode from markdown."""
        lines = content.strip().split("\n")
        if not lines:
            return None

        # Extract timestamp from header
        header_match = re.match(r"## Session: (.+)", lines[0])
        if not header_match:
            return None

        timestamp = header_match.group(1).strip()
        episode_id = hashlib.md5(timestamp.encode()).hexdigest()[:12]

        task = ""
        outcome = "unknown"
        learnings = []
        agent_type = None
        phase = None
        duration = 0

        in_learnings = False
        for line in lines[1:]:
            if line.startswith("- **Task**:"):
                task = line.split(":", 1)[1].strip()
                in_learnings = False
            elif line.startswith("- **Outcome**:"):
                outcome = line.split(":", 1)[1].strip()
                in_learnings = False
            elif line.startswith("- **Agent**:"):
                agent_type = line.split(":", 1)[1].strip()
                in_learnings = False
            elif line.startswith("- **Phase**:"):
                phase = line.split(":", 1)[1].strip()
                in_learnings = False
            elif line.startswith("- **Duration**:"):
                duration_str = line.split(":", 1)[1].strip()
                duration = int(re.search(r"\d+", duration_str).group())
                in_learnings = False
            elif line.startswith("- **Learnings**:"):
                in_learnings = True
            elif in_learnings and line.strip().startswith("- "):
                learnings.append(line.strip()[2:])

        return Episode(
            id=episode_id,
            timestamp=timestamp,
            scope_path=str(self.scope_path),
            task=task,
            outcome=outcome,
            learnings=learnings,
            duration_minutes=duration,
            agent_type=agent_type,
            phase=phase,
        )

    def clear_episodes(self, before: Optional[datetime] = None):
        """Clear episodes, optionally only those before a date."""
        if before is None:
            # Clear all
            self.episodes_file.write_text(f"# Episodes: {self.scope_path.name}\n\n")
        else:
            # Keep only episodes after the date
            episodes = self.get_episodes()
            self.episodes_file.write_text(f"# Episodes: {self.scope_path.name}\n\n")
            for ep in episodes:
                if datetime.fromisoformat(ep.timestamp) >= before:
                    self.add_episode(ep)


def find_duplicate_patterns(parent_dir: Path) -> list[dict]:
    """
    Scan child .context/MEMORY.md files and find patterns that appear in 2+ children.
    
    Args:
        parent_dir: Parent directory to scan for child memories
        
    Returns:
        List of {pattern, sources, confidence} for patterns appearing in multiple children
    """
    # Collect patterns from all child directories
    pattern_sources: dict[str, list[tuple[str, float, str]]] = {}  # content -> [(source, confidence, category)]
    
    for child_dir in parent_dir.iterdir():
        if not child_dir.is_dir():
            continue
        
        memory_json = child_dir / ".context" / "MEMORY.json"
        if not memory_json.exists():
            continue
        
        try:
            data = json.loads(memory_json.read_text())
            memory = Memory.from_dict(data)
            
            for pattern in memory.patterns.values():
                # Normalize content for comparison
                content_key = pattern.content.strip().lower()
                
                if content_key not in pattern_sources:
                    pattern_sources[content_key] = []
                
                pattern_sources[content_key].append((
                    str(child_dir),
                    pattern.confidence,
                    pattern.category,
                ))
        except (json.JSONDecodeError, KeyError):
            continue
    
    # Find patterns appearing in 2+ children
    duplicates = []
    for content_key, sources in pattern_sources.items():
        if len(sources) >= 2:
            # Calculate average confidence
            avg_confidence = sum(s[1] for s in sources) / len(sources)
            # Use the most common category
            categories = [s[2] for s in sources]
            most_common_category = max(set(categories), key=categories.count)
            
            # Find original content (not lowercased)
            original_content = None
            for child_dir in parent_dir.iterdir():
                if not child_dir.is_dir():
                    continue
                memory_json = child_dir / ".context" / "MEMORY.json"
                if not memory_json.exists():
                    continue
                try:
                    data = json.loads(memory_json.read_text())
                    memory = Memory.from_dict(data)
                    for pattern in memory.patterns.values():
                        if pattern.content.strip().lower() == content_key:
                            original_content = pattern.content
                            break
                    if original_content:
                        break
                except (json.JSONDecodeError, KeyError):
                    continue
            
            duplicates.append({
                "pattern": original_content or content_key,
                "sources": [s[0] for s in sources],
                "confidence": avg_confidence,
                "category": most_common_category,
            })
    
    return duplicates


def propose_promotions(working_dir: Path) -> list[dict]:
    """
    Suggest promoting duplicate patterns from children to parent scope.
    
    Args:
        working_dir: Directory to analyze (will scan children for duplicates)
        
    Returns:
        List of {pattern, from_scope, to_scope, reason} promotion suggestions
    """
    duplicates = find_duplicate_patterns(working_dir)
    
    promotions = []
    for dup in duplicates:
        promotions.append({
            "pattern": dup["pattern"],
            "from_scope": dup["sources"],
            "to_scope": str(working_dir),
            "reason": f"Pattern appears in {len(dup['sources'])} child scopes with avg confidence {dup['confidence']:.2f}",
            "category": dup["category"],
            "confidence": dup["confidence"],
        })
    
    return promotions


class Distiller:
    """Distills episodes into memory patterns."""

    def __init__(self, scope_path: Path):
        self.scope_path = scope_path
        self.episode_store = EpisodeStore(scope_path)
        self.memory = self._load_or_create_memory()

    def _load_or_create_memory(self) -> Memory:
        """Load existing memory or create new."""
        memory_file = self._find_memory_file()
        if memory_file and memory_file.exists():
            # Try to load JSON sidecar first
            json_sidecar = memory_file.with_suffix(".json")
            if json_sidecar.exists():
                data = json.loads(json_sidecar.read_text())
                return Memory.from_dict(data)

        return Memory(scope_path=str(self.scope_path))

    def _find_memory_file(self) -> Optional[Path]:
        """Find the memory file location."""
        candidates = [
            self.scope_path / ".context" / "MEMORY.md",
            self.scope_path / ".claude" / "MEMORY.md",
            self.scope_path / "MEMORY.md",
        ]
        for candidate in candidates:
            if candidate.exists():
                return candidate
        # Default location
        return self.scope_path / ".context" / "MEMORY.md"

    def distill(
        self, since: Optional[datetime] = None, clear_episodes: bool = True
    ) -> Memory:
        """
        Distill episodes into memory.

        Args:
            since: Only process episodes since this time
            clear_episodes: Whether to clear processed episodes

        Returns:
            Updated memory
        """
        episodes = self.episode_store.get_episodes(since)

        for episode in episodes:
            patterns = episode.extract_patterns()
            for pattern_data in patterns:
                self.memory.add_pattern(
                    content=pattern_data["content"],
                    category=pattern_data["category"],
                    episode_id=pattern_data["source_episode"],
                )

        # Apply decay and prune
        self.memory.apply_decay()
        self.memory.prune()

        # Update metadata
        self.memory.last_distilled = datetime.now().isoformat()

        # Save memory
        self._save_memory()

        # Optionally clear processed episodes
        if clear_episodes and episodes:
            oldest_episode = min(episodes, key=lambda e: e.timestamp)
            cutoff = datetime.fromisoformat(oldest_episode.timestamp) - timedelta(
                days=1
            )
            self.episode_store.clear_episodes(before=cutoff)

        return self.memory

    def distill_with_promotions(
        self,
        since: Optional[datetime] = None,
        clear_episodes: bool = True,
        auto_promote: bool = False,
    ) -> dict:
        """
        Distill episodes and check for promotion opportunities.
        
        Args:
            since: Only process episodes since this time
            clear_episodes: Whether to clear processed episodes
            auto_promote: If True, automatically apply promotions
            
        Returns:
            Dict with 'memory' and 'promotions' keys
        """
        # First do normal distillation
        memory = self.distill(since=since, clear_episodes=clear_episodes)
        
        # Check for promotion opportunities
        promotions = propose_promotions(self.scope_path)
        
        if auto_promote and promotions:
            for promo in promotions:
                # Add promoted pattern to this scope's memory
                self.memory.add_pattern(
                    content=promo["pattern"],
                    category=promo["category"],
                    confidence=promo["confidence"],
                )
            
            # Save updated memory
            self._save_memory()
        
        return {
            "memory": memory,
            "promotions": promotions,
        }

    def _save_memory(self):
        """Save memory to disk."""
        memory_file = self._find_memory_file()

        # Ensure directory exists
        memory_file.parent.mkdir(exist_ok=True)

        # Save markdown version
        memory_file.write_text(self.memory.to_markdown())

        # Save JSON sidecar for reliable parsing
        json_sidecar = memory_file.with_suffix(".json")
        json_sidecar.write_text(json.dumps(self.memory.to_dict(), indent=2))


def log_episode(
    scope_path: Path,
    task: str,
    outcome: str,
    learnings: list[str],
    agent_type: Optional[str] = None,
    phase: Optional[str] = None,
    duration_minutes: int = 0,
):
    """Convenience function to log an episode."""
    store = EpisodeStore(scope_path)

    episode = Episode(
        id=hashlib.md5(datetime.now().isoformat().encode()).hexdigest()[:12],
        timestamp=datetime.now().isoformat(),
        scope_path=str(scope_path),
        task=task,
        outcome=outcome,
        learnings=learnings,
        agent_type=agent_type,
        phase=phase,
        duration_minutes=duration_minutes,
    )

    store.add_episode(episode)
    return episode


def trigger_distillation(scope_path: Path, force: bool = False) -> Memory:
    """Convenience function to trigger distillation."""
    distiller = Distiller(scope_path)
    return distiller.distill()


# CLI interface
if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: memory.py <command> [args]")
        print("Commands:")
        print("  distill [dir]         - Distill episodes into memory")
        print("  show [dir]            - Show current memory")
        print("  episodes [dir]        - Show pending episodes")
        print("  log <task> <outcome>  - Log an episode (reads learnings from stdin)")
        print("  promote [dir]         - Show promotion suggestions")
        sys.exit(1)

    command = sys.argv[1]
    work_dir = Path(sys.argv[2] if len(sys.argv) > 2 else ".").resolve()

    if command == "distill":
        memory = trigger_distillation(work_dir)
        print(f"Distilled {len(memory.patterns)} patterns")
        print(memory.to_markdown())

    elif command == "show":
        distiller = Distiller(work_dir)
        print(distiller.memory.to_markdown())

    elif command == "episodes":
        store = EpisodeStore(work_dir)
        episodes = store.get_episodes()
        print(f"Pending episodes: {len(episodes)}")
        for ep in episodes:
            print(f"\n{ep.timestamp}: {ep.task} ({ep.outcome})")
            for learning in ep.learnings:
                print(f"  - {learning}")

    elif command == "log":
        if len(sys.argv) < 4:
            print("Usage: memory.py log <task> <outcome>")
            print("Learnings: provide via stdin, one per line")
            sys.exit(1)

        task = sys.argv[2]
        outcome = sys.argv[3]

        print("Enter learnings (one per line, Ctrl+D to finish):")
        learnings = [line.strip() for line in sys.stdin if line.strip()]

        episode = log_episode(work_dir, task, outcome, learnings)
        print(f"Logged episode: {episode.id}")

    elif command == "promote":
        promotions = propose_promotions(work_dir)
        if not promotions:
            print("No promotion suggestions found.")
        else:
            print(f"Found {len(promotions)} promotion suggestions:\n")
            for promo in promotions:
                print(f"Pattern: {promo['pattern']}")
                print(f"  From: {', '.join(promo['from_scope'])}")
                print(f"  To: {promo['to_scope']}")
                print(f"  Reason: {promo['reason']}")
                print()

    else:
        print(f"Unknown command: {command}")
        sys.exit(1)
