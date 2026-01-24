#!/usr/bin/env python3
"""Async connection pool with JSON-RPC multiplexing.

Provides AsyncConnection for multiplexed requests over a single subprocess,
and ConnectionPool for load-balanced access to multiple connections.
"""

import asyncio
import json
from typing import Optional

from config import BackendConfig
from errors import ConnectionError, RequestTimeoutError


class AsyncConnection:
    """Single async connection to a backend with multiplexed requests.
    
    Uses JSON-RPC 2.0 protocol over stdio. Multiple requests can be in-flight
    simultaneously - responses are matched to requests by ID.
    
    Usage:
        conn = AsyncConnection(config)
        await conn.start()
        result = await conn.send_request("tools/call", {"name": "my_tool"})
        await conn.close()
    """
    
    def __init__(self, config: BackendConfig):
        """Initialize connection with backend config.
        
        Args:
            config: Backend configuration including command and timeouts
        """
        self.config = config
        self._process: Optional[asyncio.subprocess.Process] = None
        self._pending: dict[int, asyncio.Future] = {}
        self._reader_task: Optional[asyncio.Task] = None
        self._write_lock = asyncio.Lock()
        self._next_request_id = 0
        self._connected = False
    
    @property
    def is_connected(self) -> bool:
        """Check if connection is active."""
        return self._connected and self._process is not None
    
    async def start(self) -> None:
        """Spawn subprocess and start reader loop.
        
        Raises:
            ConnectionError: If subprocess fails to start
        """
        if self._connected:
            return
        
        try:
            self._process = await asyncio.create_subprocess_exec(
                *self.config.command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            self._connected = True
            self._reader_task = asyncio.create_task(self._reader_loop())
        except Exception as e:
            raise ConnectionError(f"Failed to start backend '{self.config.name}': {e}")
    
    async def send_request(self, method: str, params: dict) -> dict:
        """Send JSON-RPC request and wait for response.
        
        Args:
            method: JSON-RPC method name (e.g., "tools/call")
            params: Method parameters
            
        Returns:
            Response dict from backend
            
        Raises:
            RequestTimeoutError: If request times out
            ConnectionError: If connection is lost
        """
        if not self._connected:
            raise ConnectionError("Connection not started")
        
        request_id = self._get_next_id()
        future: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending[request_id] = future
        
        request = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params,
        }
        
        try:
            # Send request (serialize writes)
            async with self._write_lock:
                if self._process and self._process.stdin:
                    data = (json.dumps(request) + "\n").encode()
                    self._process.stdin.write(data)
                    await self._process.stdin.drain()
            
            # Wait for response with timeout
            try:
                return await asyncio.wait_for(
                    future, 
                    timeout=self.config.request_timeout
                )
            except asyncio.TimeoutError:
                self._pending.pop(request_id, None)
                raise RequestTimeoutError(
                    f"Request to {self.config.name}/{method} timed out after "
                    f"{self.config.request_timeout}s"
                )
        except Exception as e:
            self._pending.pop(request_id, None)
            if isinstance(e, (RequestTimeoutError, ConnectionError)):
                raise
            raise ConnectionError(f"Request failed: {e}")
    
    async def close(self) -> None:
        """Close connection and terminate subprocess."""
        self._connected = False
        
        if self._reader_task:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass
            self._reader_task = None
        
        if self._process:
            try:
                self._process.terminate()
            except ProcessLookupError:
                pass  # Process already dead
            try:
                await asyncio.wait_for(self._process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                try:
                    self._process.kill()
                except ProcessLookupError:
                    pass  # Process already dead
            self._process = None
        
        # Cancel any pending requests
        for future in self._pending.values():
            if not future.done():
                future.set_exception(ConnectionError("Connection closed"))
        self._pending.clear()
    
    def _get_next_id(self) -> int:
        """Generate unique request ID."""
        self._next_request_id += 1
        return self._next_request_id
    
    async def _reader_loop(self) -> None:
        """Read responses from stdout and resolve matching Futures."""
        try:
            while self._connected and self._process:
                if not self._process.stdout:
                    break
                
                line = await self._process.stdout.readline()
                
                if not line:
                    # EOF - process died
                    self._connected = False
                    for future in self._pending.values():
                        if not future.done():
                            future.set_exception(
                                ConnectionError(f"Backend '{self.config.name}' connection lost")
                            )
                    break
                
                try:
                    response = json.loads(line.decode().strip())
                    request_id = response.get("id")
                    
                    if request_id is not None and request_id in self._pending:
                        future = self._pending.pop(request_id)
                        if not future.done():
                            future.set_result(response)
                except json.JSONDecodeError:
                    # Skip malformed responses
                    pass
        except asyncio.CancelledError:
            pass
        except Exception:
            self._connected = False


class ConnectionPool:
    """Pool of AsyncConnection instances with semaphore-based backpressure.
    
    Manages multiple connections to a backend and limits concurrent requests
    using a semaphore. Provides connection reuse and health monitoring.
    
    Usage:
        pool = ConnectionPool(config)
        await pool.start()
        async with pool.acquire() as conn:
            result = await conn.send_request("tools/call", {...})
        await pool.close()
    """
    
    def __init__(self, config: BackendConfig):
        """Initialize pool with backend config.
        
        Args:
            config: Backend configuration including max_concurrent and pool_size
        """
        self.config = config
        self.max_concurrent = config.max_concurrent
        self.pool_size = config.pool_size
        
        self._connections: list[AsyncConnection] = []
        self._available: asyncio.Queue[AsyncConnection] = asyncio.Queue()
        self._semaphore = asyncio.Semaphore(config.max_concurrent)
        self._lock = asyncio.Lock()
        self._started = False
        self._closed = False
        
        # Statistics
        self._total_requests = 0
        self._in_flight = 0
    
    async def start(self) -> None:
        """Start the pool and create initial connections."""
        if self._started:
            return
        
        self._started = True
        
        # Create initial connections
        for _ in range(self.pool_size):
            conn = AsyncConnection(self.config)
            await conn.start()
            self._connections.append(conn)
            await self._available.put(conn)
    
    async def close(self) -> None:
        """Close all connections in the pool."""
        self._closed = True
        
        # Close all connections
        for conn in self._connections:
            await conn.close()
        
        self._connections.clear()
        
        # Clear queue
        while not self._available.empty():
            try:
                self._available.get_nowait()
            except asyncio.QueueEmpty:
                break
    
    def acquire(self) -> "ConnectionContextManager":
        """Acquire a connection from the pool.
        
        Returns a context manager that handles semaphore and connection lifecycle.
        
        Returns:
            ConnectionContextManager for use with `async with`
        """
        return ConnectionContextManager(self)
    
    async def _acquire_connection(self) -> AsyncConnection:
        """Internal method to get a connection from the pool."""
        await self._semaphore.acquire()
        
        async with self._lock:
            self._in_flight += 1
            self._total_requests += 1
        
        try:
            # Get available connection
            conn = await asyncio.wait_for(self._available.get(), timeout=5.0)
            
            # Verify connection is healthy
            if not conn.is_connected:
                # Replace dead connection
                await conn.close()
                self._connections.remove(conn)
                
                conn = AsyncConnection(self.config)
                await conn.start()
                self._connections.append(conn)
            
            return conn
        except Exception:
            self._semaphore.release()
            async with self._lock:
                self._in_flight -= 1
            raise
    
    async def _release_connection(self, conn: AsyncConnection) -> None:
        """Internal method to return connection to pool."""
        async with self._lock:
            self._in_flight -= 1
        
        self._semaphore.release()
        
        if not self._closed and conn.is_connected:
            await self._available.put(conn)
    
    def get_stats(self) -> dict:
        """Get pool statistics.
        
        Returns:
            Dict with pool metrics
        """
        return {
            "active_connections": len(self._connections),
            "available_connections": self._available.qsize(),
            "in_flight_requests": self._in_flight,
            "total_requests": self._total_requests,
            "max_concurrent": self.max_concurrent,
            "pool_size": self.pool_size,
        }


class ConnectionContextManager:
    """Context manager for pool connection acquisition."""
    
    def __init__(self, pool: ConnectionPool):
        self._pool = pool
        self._conn: Optional[AsyncConnection] = None
    
    async def __aenter__(self) -> AsyncConnection:
        self._conn = await self._pool._acquire_connection()
        return self._conn
    
    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._conn:
            await self._pool._release_connection(self._conn)
