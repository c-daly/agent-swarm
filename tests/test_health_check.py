#!/usr/bin/env python3
"""Tests for Controller backend health-check thread."""

import threading
import time
from unittest.mock import MagicMock, patch
import logging


def _make_controller(tmp_path):
    """Create a Controller with all heavy services mocked out.

    Returns (ctrl, mock_bm, stop_patches) where stop_patches() must be
    called when the test is done to undo all patches.
    """
    patches = [
        patch("lib.controller.PermissionChecker"),
        patch("lib.controller.LLMService"),
        patch("lib.controller.DataStore"),
        patch("lib.controller.Cache"),
        patch("lib.controller._HEALTH_CHECK_INTERVAL", 0.05),
        patch("lib.controller.BackendManager"),
    ]
    mocks = [p.start() for p in patches]
    mock_bm_cls = mocks[-1]  # BackendManager is last

    mock_bm = MagicMock()
    mock_bm.list.return_value = ["serena", "context7"]
    mock_bm.reconnect_if_needed.return_value = True
    mock_bm_cls.return_value = mock_bm

    from lib.controller import Controller
    ctrl = Controller(
        config_dir=tmp_path / "config",
        data_dir=tmp_path / "data",
    )

    def stop_patches():
        for p in patches:
            p.stop()

    return ctrl, mock_bm, stop_patches


def test_health_check_thread_is_daemon(tmp_path):
    """Health-check thread must be daemon so it doesn't block shutdown."""
    ctrl, _, stop = _make_controller(tmp_path)
    try:
        threads = [t for t in threading.enumerate() if t.name == "backend-health-check"]
        assert len(threads) == 1
        assert all(t.daemon for t in threads)
    finally:
        stop()


def test_health_check_loop_calls_reconnect_for_each_backend(tmp_path):
    """Health-check loop calls reconnect_if_needed for every backend."""
    ctrl, mock_bm, stop = _make_controller(tmp_path)
    try:
        # Allow at least one loop iteration (interval patched to 0.05s)
        time.sleep(0.3)
        calls = mock_bm.reconnect_if_needed.call_args_list
        backend_names = [c.args[0] for c in calls]
        assert "serena" in backend_names
        assert "context7" in backend_names
    finally:
        stop()


def test_health_check_loop_logs_warning_on_failure(tmp_path, caplog):
    """Health-check loop logs a warning when a backend can't reconnect."""
    ctrl, mock_bm, stop = _make_controller(tmp_path)
    mock_bm.list.return_value = ["serena"]
    mock_bm.reconnect_if_needed.return_value = False

    try:
        with caplog.at_level(logging.WARNING, logger="lib.controller"):
            time.sleep(0.2)
    finally:
        stop()

    assert any("serena" in r.message and "down" in r.message for r in caplog.records)
