"""Characterization tests for lib/connection_pool.py.

These tests pin the EXISTING behavior of AsyncConnection, ConnectionPool, and
ConnectionContextManager.  The subprocess seam is faked using a trivial
Python echo-server that reads JSON-RPC lines and echoes them back (writing a
``result`` field so futures resolve).

All coroutines are driven with asyncio.run() inside plain test functions —
no pytest-asyncio dependency.
"""

import asyncio
import sys
import types
from pathlib import Path
from types import SimpleNamespace

# ---------------------------------------------------------------------------
# Path / module fixup — must happen BEFORE any lib imports.
#
# lib/connection_pool.py does `from config import BackendConfig`.
# There is a config/ directory at the project root that Python discovers as a
# namespace package, which wins over any actual module.  We pre-populate
# sys.modules['config'] with a stub that exposes BackendConfig so the import
# works without touching lib/ at all.
# ---------------------------------------------------------------------------
_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "lib"))

if "config" not in sys.modules or not hasattr(sys.modules["config"], "BackendConfig"):
    _stub_config = types.ModuleType("config")

    class _BackendConfigStub:
        """Stub satisfying the type annotation; tests use SimpleNamespace instead."""
        pass

    _stub_config.BackendConfig = _BackendConfigStub
    sys.modules["config"] = _stub_config

# Now safe to import from lib
from connection_pool import AsyncConnection, ConnectionPool, ConnectionContextManager  # noqa: E402
from errors import ConnectionError as RouterConnectionError  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config(
    *,
    command=None,
    name="test-backend",
    request_timeout=2.0,
    max_concurrent=2,
    pool_size=2,
):
    """Return a minimal BackendConfig-shaped namespace."""
    if command is None:
        # A trivial JSON-RPC echo server: read a line, respond with
        # {"jsonrpc":"2.0","id":<id>,"result":{"echo":true,"method":<method>}}
        command = [
            sys.executable,
            "-c",
            (
                "import sys, json\n"
                "for line in sys.stdin:\n"
                "    line=line.strip()\n"
                "    if not line: continue\n"
                "    req=json.loads(line)\n"
                "    resp={'jsonrpc':'2.0','id':req['id'],'result':{'echo':True,'method':req['method']}}\n"
                "    sys.stdout.write(json.dumps(resp)+'\\n')\n"
                "    sys.stdout.flush()\n"
            ),
        ]
    cfg = SimpleNamespace(
        name=name,
        command=command,
        request_timeout=request_timeout,
        max_concurrent=max_concurrent,
        pool_size=pool_size,
    )
    return cfg


# ---------------------------------------------------------------------------
# AsyncConnection — is_connected state machine
# ---------------------------------------------------------------------------


def test_is_connected_false_before_start():
    """is_connected must be False immediately after construction."""
    cfg = _make_config()
    conn = AsyncConnection(cfg)
    assert conn.is_connected is False


def test_is_connected_true_after_start():
    """is_connected must be True after a successful start()."""
    async def scenario():
        cfg = _make_config()
        conn = AsyncConnection(cfg)
        await asyncio.wait_for(conn.start(), timeout=5.0)
        try:
            assert conn.is_connected is True
        finally:
            await conn.close()

    asyncio.run(scenario())


def test_is_connected_false_after_close():
    """is_connected must be False after close()."""
    async def scenario():
        cfg = _make_config()
        conn = AsyncConnection(cfg)
        await asyncio.wait_for(conn.start(), timeout=5.0)
        await conn.close()
        assert conn.is_connected is False

    asyncio.run(scenario())


# ---------------------------------------------------------------------------
# AsyncConnection — send_request when not connected
# ---------------------------------------------------------------------------


def test_send_request_raises_when_not_connected():
    """send_request before start() raises RouterConnectionError."""
    async def scenario():
        cfg = _make_config()
        conn = AsyncConnection(cfg)
        try:
            await asyncio.wait_for(
                conn.send_request("tools/call", {}),
                timeout=2.0,
            )
            assert False, "Expected RouterConnectionError"
        except RouterConnectionError:
            pass  # expected

    asyncio.run(scenario())


# ---------------------------------------------------------------------------
# AsyncConnection — JSON-RPC multiplexing: two in-flight requests
# ---------------------------------------------------------------------------


def test_send_request_multiplexing_correlates_responses():
    """Two concurrent send_request calls must each get the right response.

    The echo-server reflects the method name back in result.method, so we can
    verify each caller received the matching response.
    """
    async def scenario():
        cfg = _make_config()
        conn = AsyncConnection(cfg)
        await asyncio.wait_for(conn.start(), timeout=5.0)
        try:
            t1 = asyncio.create_task(conn.send_request("method/alpha", {"x": 1}))
            t2 = asyncio.create_task(conn.send_request("method/beta", {"x": 2}))
            r1, r2 = await asyncio.wait_for(asyncio.gather(t1, t2), timeout=5.0)
            assert r1["result"]["method"] == "method/alpha"
            assert r2["result"]["method"] == "method/beta"
        finally:
            await conn.close()

    asyncio.run(scenario())


def test_send_request_returns_result_dict():
    """send_request should return the full JSON-RPC response dict."""
    async def scenario():
        cfg = _make_config()
        conn = AsyncConnection(cfg)
        await asyncio.wait_for(conn.start(), timeout=5.0)
        try:
            resp = await asyncio.wait_for(
                conn.send_request("tools/call", {"name": "x"}),
                timeout=5.0,
            )
            assert isinstance(resp, dict)
            assert "result" in resp
            assert resp["result"]["echo"] is True
        finally:
            await conn.close()

    asyncio.run(scenario())


# ---------------------------------------------------------------------------
# ConnectionPool — start / close
# ---------------------------------------------------------------------------


def test_pool_start_creates_connections():
    """pool.start() creates pool_size connected AsyncConnection instances."""
    async def scenario():
        cfg = _make_config(pool_size=2, max_concurrent=2)
        pool = ConnectionPool(cfg)
        await asyncio.wait_for(pool.start(), timeout=10.0)
        try:
            assert len(pool._connections) == 2
            for conn in pool._connections:
                assert conn.is_connected is True
        finally:
            await pool.close()

    asyncio.run(scenario())


def test_pool_close_shuts_down_all_connections():
    """pool.close() must disconnect every connection in the pool."""
    async def scenario():
        cfg = _make_config(pool_size=2, max_concurrent=2)
        pool = ConnectionPool(cfg)
        await asyncio.wait_for(pool.start(), timeout=10.0)
        connections_snapshot = list(pool._connections)
        await pool.close()
        # After close, each connection must report not-connected
        for conn in connections_snapshot:
            assert conn.is_connected is False

    asyncio.run(scenario())


# ---------------------------------------------------------------------------
# ConnectionPool — semaphore backpressure
# ---------------------------------------------------------------------------


def test_pool_acquire_blocks_when_semaphore_exhausted():
    """With max_concurrent = N, the N+1-th acquire must block.

    We hold N connections in the critical section long enough to demonstrate
    that the extra acquire times out (i.e. it cannot proceed).
    """
    N = 2

    async def scenario():
        cfg = _make_config(pool_size=N, max_concurrent=N)
        pool = ConnectionPool(cfg)
        await asyncio.wait_for(pool.start(), timeout=10.0)

        async def hold_conn(ready_ev, release_ev):
            async with pool.acquire() as conn:
                ready_ev.set()
                await release_ev.wait()

        # Acquire all N slots
        ready_events = [asyncio.Event() for _ in range(N)]
        rel_events = [asyncio.Event() for _ in range(N)]
        tasks = [
            asyncio.create_task(hold_conn(ready_events[i], rel_events[i]))
            for i in range(N)
        ]

        # Wait until all N slots are taken
        await asyncio.wait_for(
            asyncio.gather(*[e.wait() for e in ready_events]),
            timeout=5.0,
        )

        # The N+1-th acquire should time out (semaphore blocks)
        blocked = False
        try:
            await asyncio.wait_for(pool._acquire_connection(), timeout=0.3)
        except asyncio.TimeoutError:
            blocked = True
        finally:
            for e in rel_events:
                e.set()
            await asyncio.gather(*tasks, return_exceptions=True)
            await pool.close()

        assert blocked, "Expected the N+1-th acquire to block"

    asyncio.run(scenario())


# ---------------------------------------------------------------------------
# ConnectionPool — get_stats shape and counts
# ---------------------------------------------------------------------------


def test_get_stats_returns_documented_shape():
    """get_stats() must return a dict with the expected keys."""
    EXPECTED_KEYS = {
        "active_connections",
        "available_connections",
        "in_flight_requests",
        "total_requests",
        "max_concurrent",
        "pool_size",
    }

    async def scenario():
        cfg = _make_config(pool_size=2, max_concurrent=2)
        pool = ConnectionPool(cfg)
        await asyncio.wait_for(pool.start(), timeout=10.0)
        try:
            stats = pool.get_stats()
            assert isinstance(stats, dict)
            assert EXPECTED_KEYS == set(stats.keys())
        finally:
            await pool.close()

    asyncio.run(scenario())


def test_get_stats_counts_after_start():
    """After start, stats should reflect pool_size and zero in-flight."""
    async def scenario():
        cfg = _make_config(pool_size=2, max_concurrent=3)
        pool = ConnectionPool(cfg)
        await asyncio.wait_for(pool.start(), timeout=10.0)
        try:
            stats = pool.get_stats()
            assert stats["active_connections"] == 2
            assert stats["available_connections"] == 2
            assert stats["in_flight_requests"] == 0
            assert stats["total_requests"] == 0
            assert stats["max_concurrent"] == 3
            assert stats["pool_size"] == 2
        finally:
            await pool.close()

    asyncio.run(scenario())


# ---------------------------------------------------------------------------
# ConnectionContextManager — releases on normal exit
# ---------------------------------------------------------------------------


def test_context_manager_releases_on_normal_exit():
    """After exiting `async with pool.acquire()`, the connection is back in the queue."""
    async def scenario():
        cfg = _make_config(pool_size=1, max_concurrent=1)
        pool = ConnectionPool(cfg)
        await asyncio.wait_for(pool.start(), timeout=10.0)
        try:
            async with pool.acquire():
                pass  # normal exit
            # Connection should have been returned; we can acquire again without timeout
            async with pool.acquire() as conn:
                assert conn.is_connected is True
        finally:
            await pool.close()

    asyncio.run(scenario())


def test_context_manager_releases_on_exception():
    """ConnectionContextManager releases the connection even when an exception is raised."""
    async def scenario():
        cfg = _make_config(pool_size=1, max_concurrent=1)
        pool = ConnectionPool(cfg)
        await asyncio.wait_for(pool.start(), timeout=10.0)
        try:
            try:
                async with pool.acquire():
                    raise ValueError("deliberate")
            except ValueError:
                pass  # expected

            # After the exception, the connection should be released so a
            # second acquire does not time out (pool_size=1, max_concurrent=1).
            acquire_task = pool._acquire_connection()
            conn = await asyncio.wait_for(acquire_task, timeout=1.0)
            try:
                assert conn.is_connected is True
            finally:
                await pool._release_connection(conn)
        finally:
            await pool.close()

    asyncio.run(scenario())
