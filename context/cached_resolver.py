"""Cached Context Resolver to minimize redundant context resolution.

Wraps the standard resolver with caching based on file modification times.
"""

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .resolver import resolve_context, AggregatedContext, find_context_file


@dataclass
class CacheEntry:
    """A cached context resolution result."""

    context_json: str  # Serialized context
    mtimes: dict  # Path -> mtime mapping for validation
    created_at: float  # Timestamp when cached
    directory: str  # Source directory


class CachedResolver:
    """Context resolver with caching layer.

    Caches resolved context by directory path. Cache entries are invalidated
    when any context file in the hierarchy is modified.

    Args:
        cache_dir: Directory for storing cache (optional, uses memory if None).
        ttl_seconds: Time-to-live for cache entries (default: 300 = 5 minutes).
        max_entries: Maximum cache entries before LRU eviction (default: 50).
    """

    def __init__(
        self,
        cache_dir: Optional[Path] = None,
        ttl_seconds: float = 300,
        max_entries: int = 50,
    ):
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.ttl_seconds = ttl_seconds
        self.max_entries = max_entries

        # In-memory cache: directory path -> CacheEntry
        self._cache: dict[str, CacheEntry] = {}

        # Stats for monitoring
        self._stats = {
            "cache_hits": 0,
            "cache_misses": 0,
            "evictions": 0,
        }

    def resolve(self, working_dir: Path) -> AggregatedContext:
        """Resolve context for a directory, using cache if valid.

        Args:
            working_dir: Directory to resolve context for.

        Returns:
            AggregatedContext with merged context layers.
        """
        dir_key = str(working_dir.resolve())

        # Check cache
        entry = self._get_cache_entry(dir_key)
        if entry and self._is_entry_valid(entry):
            self._stats["cache_hits"] += 1
            return self._deserialize_context(entry.context_json)

        # Cache miss - resolve fresh
        self._stats["cache_misses"] += 1
        context = resolve_context(working_dir)

        # Cache the result
        self._cache_context(dir_key, context, working_dir)

        return context

    def _get_cache_entry(self, dir_key: str) -> Optional[CacheEntry]:
        """Get cache entry for directory key."""
        return self._cache.get(dir_key)

    def _is_entry_valid(self, entry: CacheEntry) -> bool:
        """Check if cache entry is still valid.

        Entry is invalid if:
        - TTL has expired
        - Any context file has been modified
        """
        # Check TTL
        if time.time() - entry.created_at > self.ttl_seconds:
            return False

        # Check file modification times
        for path_str, cached_mtime in entry.mtimes.items():
            path = Path(path_str)
            if not path.exists():
                return False  # File deleted
            try:
                current_mtime = path.stat().st_mtime
                if current_mtime > cached_mtime:
                    return False  # File modified
            except OSError:
                return False

        return True

    def _cache_context(
        self, dir_key: str, context: AggregatedContext, working_dir: Path
    ) -> None:
        """Cache a resolved context."""
        # Enforce size limit with LRU eviction
        if len(self._cache) >= self.max_entries:
            self._evict_oldest()

        # Collect modification times for all context files in hierarchy
        mtimes = {}
        for layer in context.layers:
            ctx_file = find_context_file(layer.path)
            if ctx_file:
                mtimes[str(ctx_file)] = ctx_file.stat().st_mtime

        entry = CacheEntry(
            context_json=self._serialize_context(context),
            mtimes=mtimes,
            created_at=time.time(),
            directory=dir_key,
        )

        self._cache[dir_key] = entry

    def _evict_oldest(self) -> None:
        """Evict the oldest cache entry."""
        if not self._cache:
            return

        oldest_key = min(self._cache.keys(), key=lambda k: self._cache[k].created_at)
        del self._cache[oldest_key]
        self._stats["evictions"] += 1

    def _serialize_context(self, context: AggregatedContext) -> str:
        """Serialize context to JSON string."""
        return json.dumps(context.to_dict())

    def _deserialize_context(self, context_json: str) -> AggregatedContext:
        """Deserialize context from JSON string."""
        data = json.loads(context_json)

        # Reconstruct AggregatedContext from dict
        from .resolver import ContextLayer

        layers = []
        for layer_data in data.get("layers", []):
            # Create layer with just the essential data
            layer = ContextLayer(
                path=Path(layer_data["path"]),
                level=layer_data["level"],
                content="",  # Content is in merged sections
            )
            # Manually set sections from stored data
            layer.sections = layer_data.get("sections", {})
            layers.append(layer)

        context = AggregatedContext(layers=layers)
        # Override merged sections with cached data
        context.merged_sections = data.get("merged", {})

        return context

    def get_stats(self) -> dict:
        """Get cache statistics."""
        return self._stats.copy()

    def clear(self) -> None:
        """Clear all cached entries."""
        self._cache.clear()

    def invalidate(self, working_dir: Path) -> bool:
        """Manually invalidate cache for a directory.

        Args:
            working_dir: Directory to invalidate.

        Returns:
            True if an entry was invalidated.
        """
        dir_key = str(working_dir.resolve())
        if dir_key in self._cache:
            del self._cache[dir_key]
            return True
        return False
