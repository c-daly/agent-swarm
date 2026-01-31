#!/usr/bin/env python3
"""Tests for the in-memory TTL cache."""

import threading
import time

import pytest

from lib.cache import Cache


class TestCacheBasic:
    def test_store_and_get(self):
        c = Cache()
        c.store("k1", "value1")
        assert c.get("k1") == "value1"

    def test_get_removes_by_default(self):
        c = Cache()
        c.store("k1", "value1")
        assert c.get("k1") == "value1"
        assert c.get("k1") is None

    def test_get_keep(self):
        c = Cache()
        c.store("k1", "value1")
        assert c.get("k1", remove=False) == "value1"
        assert c.get("k1", remove=False) == "value1"

    def test_get_missing_key(self):
        c = Cache()
        assert c.get("nonexistent") is None

    def test_has(self):
        c = Cache()
        c.store("k1", "value1")
        assert c.has("k1") is True
        assert c.has("k2") is False

    def test_remove_existing(self):
        c = Cache()
        c.store("k1", "value1")
        assert c.remove("k1") is True
        assert c.get("k1") is None

    def test_remove_missing(self):
        c = Cache()
        assert c.remove("k1") is False

    def test_clear(self):
        c = Cache()
        c.store("k1", "v1")
        c.store("k2", "v2")
        c.clear()
        assert c.size() == 0

    def test_size(self):
        c = Cache()
        c.store("k1", "v1")
        c.store("k2", "v2")
        assert c.size() == 2

    def test_store_overwrites(self):
        c = Cache()
        c.store("k1", "old")
        c.store("k1", "new")
        assert c.get("k1") == "new"

    def test_stores_any_type(self):
        c = Cache()
        c.store("dict", {"a": 1})
        c.store("list", [1, 2, 3])
        assert c.get("dict") == {"a": 1}
        assert c.get("list") == [1, 2, 3]


class TestCacheTTL:
    def test_expired_entry_returns_none(self):
        c = Cache()
        c.store("k1", "v1", ttl=0)
        time.sleep(0.01)
        assert c.get("k1") is None

    def test_custom_ttl_alive(self):
        c = Cache()
        c.store("long", "v1", ttl=3600)
        assert c.has("long") is True

    def test_has_detects_expired(self):
        c = Cache()
        c.store("k1", "v1", ttl=0)
        time.sleep(0.01)
        assert c.has("k1") is False

    def test_size_excludes_expired(self):
        c = Cache()
        c.store("alive", "v1", ttl=3600)
        c.store("dead", "v2", ttl=0)
        time.sleep(0.01)
        assert c.size() == 1

    def test_default_ttl_used(self):
        c = Cache(default_ttl=3600)
        c.store("k1", "v1")
        assert c.has("k1") is True


class TestCacheEviction:
    def test_max_entries_evicts_oldest(self):
        c = Cache(max_entries=3)
        c.store("k1", "v1")
        c.store("k2", "v2")
        c.store("k3", "v3")
        c.store("k4", "v4")  # Should evict k1
        assert c.has("k1") is False
        assert c.has("k4") is True
        assert c.size() == 3

    def test_max_entries_preserves_newest(self):
        c = Cache(max_entries=2)
        for i in range(10):
            c.store(f"k{i}", f"v{i}")
        assert c.size() == 2
        assert c.has("k8") is True
        assert c.has("k9") is True

    def test_overwrite_resets_insertion_order(self):
        c = Cache(max_entries=3)
        c.store("k1", "v1")
        c.store("k2", "v2")
        c.store("k3", "v3")
        # Re-store k1 moves it to end of insertion order
        c.store("k1", "v1_new")
        # Now k2 is oldest; adding k4 should evict k2
        c.store("k4", "v4")
        assert c.has("k2") is False
        assert c.get("k1", remove=False) == "v1_new"


class TestCacheThreadSafety:
    def test_concurrent_store_and_get(self):
        c = Cache()
        errors = []

        def writer():
            try:
                for i in range(100):
                    c.store(f"w-{i}", f"v-{i}")
            except Exception as e:
                errors.append(e)

        def reader():
            try:
                for i in range(100):
                    c.get(f"w-{i}", remove=False)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer) for _ in range(4)]
        threads += [threading.Thread(target=reader) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert errors == []
