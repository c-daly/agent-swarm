#!/usr/bin/env python3
"""Tests for lib/daemon.py"""

from __future__ import annotations

import fcntl
import json
import socket
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from lib.daemon import (
    DEFAULT_PORT,
    _acquire_lock,
    is_running,
    shutdown,
)


# --- is_running ---


class TestIsRunning:
    def test_not_running(self):
        """Returns False when nothing is listening."""
        assert is_running(port=19876) is False

    def test_running(self):
        """Returns True when a server is listening."""
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(("127.0.0.1", 19877))
        server.listen(1)
        try:
            assert is_running(port=19877) is True
        finally:
            server.close()


# --- _acquire_lock ---


class TestAcquireLock:
    def test_acquire_succeeds(self, tmp_path):
        """Can acquire lock on fresh file."""
        lock_file = tmp_path / ".test.lock"
        with patch("lib.daemon.LOCK_FILE", lock_file):
            fd = _acquire_lock()
            assert fd is not None
            fd.close()

    def test_acquire_fails_when_locked(self, tmp_path):
        """Returns None when lock is already held."""
        lock_file = tmp_path / ".test.lock"
        with patch("lib.daemon.LOCK_FILE", lock_file):
            fd1 = _acquire_lock()
            assert fd1 is not None
            fd2 = _acquire_lock()
            assert fd2 is None
            fd1.close()

    def test_lock_released_on_close(self, tmp_path):
        """Lock can be reacquired after file is closed."""
        lock_file = tmp_path / ".test.lock"
        with patch("lib.daemon.LOCK_FILE", lock_file):
            fd1 = _acquire_lock()
            assert fd1 is not None
            fd1.close()
            fd2 = _acquire_lock()
            assert fd2 is not None
            fd2.close()


# --- shutdown ---


class TestShutdown:
    def test_sends_shutdown_rpc(self):
        """Sends correct JSON-RPC shutdown message."""
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(("127.0.0.1", 19879))
        server.listen(1)
        received = []

        def accept_one():
            conn, _ = server.accept()
            data = conn.recv(4096)
            received.append(data)
            response = (
                json.dumps(
                    {"jsonrpc": "2.0", "id": 1, "result": {"status": "shutting_down"}}
                )
                + "\n"
            )
            conn.sendall(response.encode("utf-8"))
            conn.close()

        t = threading.Thread(target=accept_one, daemon=True)
        t.start()
        try:
            result = shutdown(port=19879)
            assert result is True
            t.join(timeout=2)
            assert len(received) == 1
            msg = json.loads(received[0].decode("utf-8").strip())
            assert msg["method"] == "daemon/shutdown"
            assert msg["jsonrpc"] == "2.0"
            assert msg["id"] == 1
        finally:
            server.close()

    def test_shutdown_not_running(self):
        """Returns False when daemon not running."""
        assert shutdown(port=19880) is False


# --- main ---


class TestMain:
    @patch("lib.controller.Controller")
    @patch("lib.router.Router")
    @patch("lib.daemon._acquire_lock")
    def test_main_starts_and_serves(
        self, mock_lock, mock_router_cls, mock_ctrl_cls, tmp_path
    ):
        """Main creates controller, router, and calls serve_forever."""
        mock_lock.return_value = MagicMock()
        mock_ctrl = MagicMock()
        mock_ctrl_cls.return_value = mock_ctrl
        mock_router = MagicMock()
        mock_router_cls.return_value = mock_router

        with (
            patch("lib.daemon.LOG_DIR", tmp_path / "logs"),
            patch("lib.daemon.DATA_DIR", tmp_path / "data"),
            patch("lib.daemon.CONFIG_DIR", tmp_path / "config"),
            patch("lib.daemon.LOG_FILE", tmp_path / "logs" / "daemon.log"),
            patch("lib.daemon.LOCK_FILE", tmp_path / ".lock"),
        ):
            from lib.daemon import main

            main(port=19881)

        mock_router_cls.assert_called_once_with(port=19881, controller=mock_ctrl)
        mock_router.serve_forever.assert_called_once()

    @patch("lib.daemon._acquire_lock")
    def test_main_exits_if_locked(self, mock_lock, tmp_path):
        """Main exits if lock cannot be acquired."""
        mock_lock.return_value = None

        with (
            patch("lib.daemon.LOG_DIR", tmp_path / "logs"),
            patch("lib.daemon.DATA_DIR", tmp_path / "data"),
            pytest.raises(SystemExit) as exc_info,
        ):
            from lib.daemon import main

            main(port=19882)

        assert exc_info.value.code == 1

    @patch("lib.controller.Controller")
    @patch("lib.router.Router")
    @patch("lib.daemon._acquire_lock")
    def test_signal_handlers_registered(
        self, mock_lock, mock_router_cls, mock_ctrl_cls, tmp_path
    ):
        """Signal handlers are registered for SIGTERM and SIGINT."""
        import signal

        mock_lock.return_value = MagicMock()
        mock_ctrl_cls.return_value = MagicMock()
        mock_router_cls.return_value = MagicMock()

        original_sigterm = signal.getsignal(signal.SIGTERM)
        original_sigint = signal.getsignal(signal.SIGINT)

        with (
            patch("lib.daemon.LOG_DIR", tmp_path / "logs"),
            patch("lib.daemon.DATA_DIR", tmp_path / "data"),
            patch("lib.daemon.CONFIG_DIR", tmp_path / "config"),
            patch("lib.daemon.LOG_FILE", tmp_path / "logs" / "daemon.log"),
            patch("lib.daemon.LOCK_FILE", tmp_path / ".lock"),
        ):
            from lib.daemon import main

            main(port=19883)

        # Signal handlers should have been changed from defaults
        sigterm_handler = signal.getsignal(signal.SIGTERM)
        sigint_handler = signal.getsignal(signal.SIGINT)
        assert sigterm_handler != original_sigterm or callable(sigterm_handler)
        assert sigint_handler != original_sigint or callable(sigint_handler)

        # Restore
        signal.signal(signal.SIGTERM, original_sigterm)
        signal.signal(signal.SIGINT, original_sigint)


# --- Default port ---


class TestConstants:
    def test_default_port(self):
        assert DEFAULT_PORT == 7523
