#!/usr/bin/env python3
"""Tests for MCPRouter content storage and retrieval (two-step pattern)."""

import sys
from pathlib import Path

# Add lib to path before imports
sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

import pytest  # noqa: E402

from mcp_router import MCPRouter  # noqa: E402


class TestContentStore:
    """Tests for two-step content retrieval."""

    def test_store_content_returns_unique_id(self):
        """store_content should return unique content IDs."""
        router = MCPRouter()
        id1 = router.store_content({"data": "first"})
        id2 = router.store_content({"data": "second"})
        assert id1 != id2
        assert id1.startswith("content_")
        assert id2.startswith("content_")

    def test_get_full_content_retrieves_stored_content(self):
        """get_full_content should return stored content."""
        router = MCPRouter()
        original = {"key": "value", "nested": {"a": 1}}
        content_id = router.store_content(original)
        result = router.get_full_content(content_id)
        assert "content" in result
        assert result["content"] == original

    def test_get_full_content_removes_after_retrieval(self):
        """Content should be removed after retrieval (one-time use)."""
        router = MCPRouter()
        content_id = router.store_content({"data": "temp"})
        router.get_full_content(content_id)  # First retrieval
        result = router.get_full_content(content_id)  # Second retrieval
        assert "error" in result

    def test_get_full_content_invalid_id_returns_error(self):
        """get_full_content should return error for unknown ID."""
        router = MCPRouter()
        result = router.get_full_content("nonexistent_id")
        assert "error" in result
        assert "not found" in result["error"].lower()

    def test_store_content_handles_various_types(self):
        """store_content should handle different content types."""
        router = MCPRouter()
        
        # Dict
        dict_id = router.store_content({"key": "value"})
        assert router.get_full_content(dict_id)["content"] == {"key": "value"}
        
        # List
        list_id = router.store_content([1, 2, 3])
        assert router.get_full_content(list_id)["content"] == [1, 2, 3]
        
        # String
        str_id = router.store_content("hello world")
        assert router.get_full_content(str_id)["content"] == "hello world"
        
        # None
        none_id = router.store_content(None)
        assert router.get_full_content(none_id)["content"] is None

    def test_store_content_id_format(self):
        """Content IDs should have consistent format."""
        router = MCPRouter()
        content_id = router.store_content({"test": True})
        
        # Should be content_{identifier} format
        assert content_id.startswith("content_")
        # Should have some identifier after prefix
        identifier_part = content_id[len("content_"):]
        assert len(identifier_part) >= 1  # At least some identifier

    def test_multiple_store_retrieve_cycles(self):
        """Multiple store/retrieve cycles should work independently."""
        router = MCPRouter()
        
        # First cycle
        id1 = router.store_content({"cycle": 1})
        result1 = router.get_full_content(id1)
        assert result1["content"]["cycle"] == 1
        
        # Second cycle
        id2 = router.store_content({"cycle": 2})
        result2 = router.get_full_content(id2)
        assert result2["content"]["cycle"] == 2
        
        # First ID should be gone
        assert "error" in router.get_full_content(id1)

    def test_content_store_thread_safety(self):
        """Content store should be thread-safe."""
        import threading
        
        router = MCPRouter()
        errors = []
        stored_ids = []
        lock = threading.Lock()
        
        def store_and_retrieve(thread_num):
            try:
                for i in range(50):
                    content = {"thread": thread_num, "iteration": i}
                    content_id = router.store_content(content)
                    
                    with lock:
                        stored_ids.append(content_id)
                    
                    result = router.get_full_content(content_id)
                    if "error" in result:
                        errors.append(f"Failed to retrieve {content_id}")
                    elif result["content"] != content:
                        errors.append(f"Content mismatch for {content_id}")
            except Exception as e:
                errors.append(str(e))
        
        threads = [
            threading.Thread(target=store_and_retrieve, args=(i,))
            for i in range(5)
        ]
        
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        assert errors == [], f"Thread safety errors: {errors}"
        # All IDs should be unique
        assert len(stored_ids) == len(set(stored_ids))

    def test_content_store_initialized_on_router_creation(self):
        """Router should initialize content store on creation."""
        router = MCPRouter()
        # Should have _content_store attribute
        assert hasattr(router, "_content_store")
        # Should be dict-like
        assert isinstance(router._content_store, dict)


class TestRouterGetFullTool:
    """Tests for router__get_full MCP tool dispatch."""

    def test_get_full_tool_in_socket_tool_list(self):
        """router__get_full should appear in socket tool list."""
        router = MCPRouter()
        tools = router._list_all_tools_for_socket()
        tool_names = [t["name"] for t in tools]
        assert "router__get_full" in tool_names

    def test_get_full_tool_has_required_schema(self):
        """router__get_full tool definition should require correlation_id."""
        router = MCPRouter()
        tools = router._list_all_tools_for_socket()
        get_full = next(t for t in tools if t["name"] == "router__get_full")
        assert "correlation_id" in get_full["inputSchema"]["properties"]
        assert "correlation_id" in get_full["inputSchema"]["required"]

    def test_get_full_retrieves_stored_content(self):
        """router__get_full should retrieve content stored by store_content."""
        router = MCPRouter()
        content_id = router.store_content({"key": "value", "nested": [1, 2, 3]})
        result = router.get_full_content(content_id)
        assert "content" in result
        assert result["content"]["key"] == "value"

    def test_get_full_returns_error_for_missing_id(self):
        """router__get_full should return error for unknown correlation_id."""
        router = MCPRouter()
        result = router.get_full_content("nonexistent_id")
        assert "error" in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
