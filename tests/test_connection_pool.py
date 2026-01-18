#!/usr/bin/env python3
"""Tests for async connection pool with multiplexing."""

import asyncio
import json
import sys
from pathlib import Path

import pytest

# Add lib to path
sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

from config import BackendConfig
from errors import ConnectionError, RequestTimeoutError
from connection_pool import AsyncConnection


@pytest.fixture
def backend_config():
    """Basic backend configuration for tests."""
    return BackendConfig(
        name="test",
        command=["python", "-c", "print('hello')"],
        tool_prefix="test",
        max_concurrent=10,
        request_timeout=5.0,
        pool_size=2
    )


# Simple echo server script for integration tests
ECHO_SERVER = '''
import json
import sys

while True:
    line = sys.stdin.readline()
    if not line:
        break
    try:
        req = json.loads(line)
        resp = {"jsonrpc": "2.0", "id": req.get("id"), "result": req.get("params", {})}
        print(json.dumps(resp), flush=True)
    except:
        pass
'''


class TestAsyncConnection:
    """Tests for AsyncConnection class."""

    @pytest.mark.asyncio
    async def test_connection_init(self, backend_config):
        """AsyncConnection initializes with config."""
        conn = AsyncConnection(backend_config)
        assert conn.config == backend_config
        assert not conn.is_connected

    @pytest.mark.asyncio
    async def test_connection_start_with_real_process(self):
        """start() spawns subprocess successfully."""
        config = BackendConfig(
            name="echo",
            command=["python", "-c", ECHO_SERVER],
            request_timeout=5.0
        )
        conn = AsyncConnection(config)
        
        try:
            await conn.start()
            assert conn.is_connected
        finally:
            await conn.close()
            assert not conn.is_connected

    @pytest.mark.asyncio
    async def test_connection_send_request_returns_response(self):
        """send_request() sends JSON-RPC and returns response."""
        config = BackendConfig(
            name="echo",
            command=["python", "-c", ECHO_SERVER],
            request_timeout=5.0
        )
        conn = AsyncConnection(config)
        
        try:
            await conn.start()
            
            result = await conn.send_request("tools/call", {"name": "test_tool", "value": 42})
            
            assert "result" in result
            assert result["result"]["name"] == "test_tool"
            assert result["result"]["value"] == 42
        finally:
            await conn.close()

    @pytest.mark.asyncio
    async def test_connection_multiplexes_requests(self):
        """Multiple concurrent requests are multiplexed correctly."""
        config = BackendConfig(
            name="echo",
            command=["python", "-c", ECHO_SERVER],
            request_timeout=5.0
        )
        conn = AsyncConnection(config)
        
        try:
            await conn.start()
            
            # Send multiple requests concurrently
            results = await asyncio.gather(
                conn.send_request("tools/call", {"name": "tool_a"}),
                conn.send_request("tools/call", {"name": "tool_b"}),
                conn.send_request("tools/call", {"name": "tool_c"}),
            )
            
            # Each response should match its request
            names = {r["result"]["name"] for r in results}
            assert names == {"tool_a", "tool_b", "tool_c"}
        finally:
            await conn.close()

    @pytest.mark.asyncio
    async def test_connection_request_timeout(self):
        """Request times out if no response received."""
        # Server that never responds
        slow_server = '''
import time
import sys
while True:
    line = sys.stdin.readline()
    if not line:
        break
    time.sleep(100)  # Never respond
'''
        config = BackendConfig(
            name="slow",
            command=["python", "-c", slow_server],
            request_timeout=0.5  # Short timeout
        )
        conn = AsyncConnection(config)
        
        try:
            await conn.start()
            
            with pytest.raises(RequestTimeoutError):
                await conn.send_request("tools/call", {"name": "test"})
        finally:
            await conn.close()

    @pytest.mark.asyncio
    async def test_connection_close(self):
        """close() terminates subprocess gracefully."""
        config = BackendConfig(
            name="echo",
            command=["python", "-c", ECHO_SERVER],
            request_timeout=5.0
        )
        conn = AsyncConnection(config)
        
        await conn.start()
        assert conn.is_connected
        
        await conn.close()
        assert not conn.is_connected

    @pytest.mark.asyncio
    async def test_connection_handles_process_death(self):
        """Connection detects when process dies unexpectedly."""
        # Server that exits immediately
        exit_server = '''
import sys
sys.exit(0)
'''
        config = BackendConfig(
            name="exit",
            command=["python", "-c", exit_server],
            request_timeout=5.0
        )
        conn = AsyncConnection(config)
        
        try:
            await conn.start()
            # Give process time to exit
            await asyncio.sleep(0.1)
            
            with pytest.raises(ConnectionError):
                await conn.send_request("tools/call", {"name": "test"})
        finally:
            await conn.close()

    @pytest.mark.asyncio
    async def test_connection_request_ids_are_unique(self):
        """Each request gets a unique ID."""
        config = BackendConfig(
            name="echo",
            command=["python", "-c", ECHO_SERVER],
            request_timeout=5.0
        )
        conn = AsyncConnection(config)
        
        try:
            await conn.start()
            
            # Inspect internal state for IDs
            id1 = conn._get_next_id()
            id2 = conn._get_next_id()
            id3 = conn._get_next_id()
            
            assert id1 != id2 != id3
            assert len({id1, id2, id3}) == 3
        finally:
            await conn.close()

    @pytest.mark.asyncio
    async def test_connection_not_started_raises_error(self):
        """Sending request without start() raises ConnectionError."""
        config = BackendConfig(
            name="test",
            command=["python", "-c", "pass"],
            request_timeout=5.0
        )
        conn = AsyncConnection(config)
        
        with pytest.raises(ConnectionError):
            await conn.send_request("tools/call", {"name": "test"})


class TestConnectionPool:
    """Tests for ConnectionPool class with semaphore-based backpressure."""

    @pytest.mark.asyncio
    async def test_pool_initialization(self):
        """ConnectionPool initializes with config."""
        from connection_pool import ConnectionPool
        
        config = BackendConfig(
            name="test",
            command=["python", "-c", ECHO_SERVER],
            max_concurrent=5,
            pool_size=2
        )
        pool = ConnectionPool(config)
        
        assert pool.config == config
        assert pool.max_concurrent == 5
        assert pool.pool_size == 2

    @pytest.mark.asyncio
    async def test_pool_acquire_returns_connection(self):
        """acquire() returns a working connection."""
        from connection_pool import ConnectionPool
        
        config = BackendConfig(
            name="test",
            command=["python", "-c", ECHO_SERVER],
            max_concurrent=5,
            pool_size=2,
            request_timeout=5.0
        )
        pool = ConnectionPool(config)
        
        try:
            await pool.start()
            
            async with pool.acquire() as conn:
                assert conn.is_connected
                result = await conn.send_request("tools/call", {"test": True})
                assert result["result"]["test"] is True
        finally:
            await pool.close()

    @pytest.mark.asyncio
    async def test_pool_reuses_connections(self):
        """Pool reuses connections instead of creating new ones."""
        from connection_pool import ConnectionPool
        
        config = BackendConfig(
            name="test",
            command=["python", "-c", ECHO_SERVER],
            max_concurrent=5,
            pool_size=1,  # Single connection to guarantee reuse
            request_timeout=5.0
        )
        pool = ConnectionPool(config)
        
        try:
            await pool.start()
            
            # Get connection, use it, release it
            async with pool.acquire() as conn1:
                id1 = id(conn1)
            
            # Get connection again - should be same one (only 1 in pool)
            async with pool.acquire() as conn2:
                id2 = id(conn2)
            
            assert id1 == id2
        finally:
            await pool.close()

    @pytest.mark.asyncio
    async def test_pool_semaphore_limits_concurrent(self):
        """Semaphore limits concurrent requests."""
        from connection_pool import ConnectionPool
        
        config = BackendConfig(
            name="test",
            command=["python", "-c", ECHO_SERVER],
            max_concurrent=2,  # Only 2 concurrent
            pool_size=2,
            request_timeout=5.0
        )
        pool = ConnectionPool(config)
        
        try:
            await pool.start()
            
            # Track concurrent count
            concurrent = 0
            max_seen = 0
            lock = asyncio.Lock()
            
            async def make_request():
                nonlocal concurrent, max_seen
                async with pool.acquire() as conn:
                    async with lock:
                        concurrent += 1
                        max_seen = max(max_seen, concurrent)
                    
                    await asyncio.sleep(0.1)  # Hold connection briefly
                    await conn.send_request("tools/call", {"test": True})
                    
                    async with lock:
                        concurrent -= 1
            
            # Launch more requests than max_concurrent
            await asyncio.gather(*[make_request() for _ in range(5)])
            
            # Should never exceed max_concurrent
            assert max_seen <= config.max_concurrent
        finally:
            await pool.close()

    @pytest.mark.asyncio
    async def test_pool_stats_tracks_metrics(self):
        """Pool tracks usage statistics."""
        from connection_pool import ConnectionPool
        
        config = BackendConfig(
            name="test",
            command=["python", "-c", ECHO_SERVER],
            max_concurrent=5,
            pool_size=2,
            request_timeout=5.0
        )
        pool = ConnectionPool(config)
        
        try:
            await pool.start()
            
            # Make some requests
            async with pool.acquire() as conn:
                await conn.send_request("tools/call", {"test": True})
            
            stats = pool.get_stats()
            
            assert "active_connections" in stats
            assert "available_connections" in stats
            assert "in_flight_requests" in stats
            assert "total_requests" in stats
        finally:
            await pool.close()

    @pytest.mark.asyncio
    async def test_pool_close_terminates_all(self):
        """close() terminates all connections."""
        from connection_pool import ConnectionPool
        
        config = BackendConfig(
            name="test",
            command=["python", "-c", ECHO_SERVER],
            max_concurrent=5,
            pool_size=2,
            request_timeout=5.0
        )
        pool = ConnectionPool(config)
        
        await pool.start()
        
        # Get connections to ensure they're created
        async with pool.acquire():
            pass
        
        stats_before = pool.get_stats()
        assert stats_before["active_connections"] > 0
        
        await pool.close()
        
        stats_after = pool.get_stats()
        assert stats_after["active_connections"] == 0
