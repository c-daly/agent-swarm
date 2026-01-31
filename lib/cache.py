#!/usr/bin/env python3
"""In-memory TTL cache for the daemon.

Ephemeral keyed content storage. Used for the two-step summarization
pattern: store full response, return summary with content_id, client
retrieves full response later.
"""

from __future__ import annotations

import threading
import time
from typing import Any


class Cache:
    """In-memory keyed content store with TTL-based expiration.

    Thread-safe. All public methods acquire self._lock.
    Python 3.7+ dict insertion order is used for oldest-first eviction.
    """

    def __init__(self, default_ttl: int = 300, max_entries: int = 1000) -> None:
        """
        Args:
            default_ttl: Default time-to-live in seconds (default 5 minutes).
            max_entries: Maximum cached entries. When exceeded, oldest entries
                         (by insertion time) are evicted regardless of TTL.
        """
        self._store: dict[str, tuple[Any, float]] = {}  # key → (value, expires_at)
        self._lock = threading.RLock()
        self._default_ttl = default_ttl
        self._max_entries = max_entries

    def store(self, key: str, value: Any, ttl: int | None = None) -> None:
        """Store a value with expiration.

        Args:
            key: Unique identifier (e.g., content_id).
            value: Content to store (any type, stored by reference).
            ttl: Time-to-live in seconds. None uses default_ttl.
        """
        expires_at = time.monotonic() + (ttl if ttl is not None else self._default_ttl)
        with self._lock:
            # Remove existing key first to reset insertion order
            self._store.pop(key, None)
            self._store[key] = (value, expires_at)
            self._evict_expired()
            # Evict oldest if over limit
            while len(self._store) > self._max_entries:
                oldest_key = next(iter(self._store))
                del self._store[oldest_key]

    def get(self, key: str, remove: bool = True) -> Any | None:
        """Retrieve a value by key.

        Args:
            key: Key to look up.
            remove: If True, remove entry after retrieval (one-time access).
                    Default True for the two-step retrieval pattern.

        Returns:
            Stored value, or None if key not found or expired.
        """
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            value, expires_at = entry
            if time.monotonic() > expires_at:
                del self._store[key]
                return None
            if remove:
                del self._store[key]
            return value

    def has(self, key: str) -> bool:
        """Check if key exists and is not expired."""
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return False
            _, expires_at = entry
            if time.monotonic() > expires_at:
                del self._store[key]
                return False
            return True

    def remove(self, key: str) -> bool:
        """Remove a key. Returns True if key existed."""
        with self._lock:
            return self._store.pop(key, None) is not None

    def clear(self) -> None:
        """Remove all entries."""
        with self._lock:
            self._store.clear()

    def size(self) -> int:
        """Return number of non-expired entries."""
        with self._lock:
            self._evict_expired()
            return len(self._store)

    def _evict_expired(self) -> None:
        """Remove all entries past their TTL.

        Must be called while holding self._lock.
        """
        now = time.monotonic()
        expired = [k for k, (_, exp) in self._store.items() if now > exp]
        for k in expired:
            del self._store[k]
