# Backend Health-Check Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a periodic background thread to `Controller` that detects and reconnects dead external backends (serena, context7, playwright) every 60 seconds, preventing multi-day outages from undetected disconnections.

**Architecture:** `BackendManager` gets a new `reconnect_if_needed(backend)` method that checks process liveness and reconnects if dead. `Controller` starts a daemon thread that calls this for every backend on a 60-second interval. All exceptions are swallowed in the loop so the thread never dies.

**Tech Stack:** Python stdlib only (`threading`, `time`). No new dependencies.

---

### Task 1: Add `reconnect_if_needed` to `BackendManager`

**Files:**
- Modify: `lib/backends.py` (after `list_tools`, before `list`)

**Step 1: Write the failing test**

Add to `tests/test_backends.py`, inside a new class `TestReconnectIfNeeded` after `TestListTools`:

```python
class TestReconnectIfNeeded:
    def test_unknown_backend_returns_false(self, tmp_path):
        mgr = BackendManager(_write_config(tmp_path))
        assert mgr.reconnect_if_needed("nonexistent") is False

    @patch("lib.backends.select.select")
    @patch("lib.backends.subprocess.Popen")
    def test_alive_connection_returns_true_without_respawn(
        self, mock_popen, mock_select, tmp_path
    ):
        proc = _make_mock_proc([_handshake_response()])
        mock_popen.return_value = proc
        mock_select.return_value = ([proc.stdout], [], [])

        mgr = BackendManager(_write_config(tmp_path))
        mgr._connections["serena"] = proc  # inject live connection

        result = mgr.reconnect_if_needed("serena")

        assert result is True
        assert mock_popen.call_count == 0  # no new spawn needed

    @patch("lib.backends.select.select")
    @patch("lib.backends.subprocess.Popen")
    def test_dead_connection_clears_cache_and_reconnects(
        self, mock_popen, mock_select, tmp_path
    ):
        dead_proc = MagicMock()
        dead_proc.poll.return_value = 1  # process has exited

        tools_response = {
            "jsonrpc": "2.0", "id": "x",
            "result": {"tools": [{"name": "t1"}]},
        }
        live_proc = _make_mock_proc([_handshake_response(), tools_response])
        mock_popen.return_value = live_proc
        mock_select.return_value = ([live_proc.stdout], [], [])

        mgr = BackendManager(_write_config(tmp_path))
        mgr._connections["serena"] = dead_proc
        mgr._tools_cache["serena"] = [{"name": "stale"}]

        result = mgr.reconnect_if_needed("serena")

        assert result is True
        assert "serena" not in mgr._tools_cache  # cache cleared
        assert mgr._connections["serena"] is live_proc  # new connection stored

    @patch("lib.backends.subprocess.Popen")
    def test_reconnect_failure_returns_false(self, mock_popen, tmp_path):
        dead_proc = MagicMock()
        dead_proc.poll.return_value = 1  # process has exited

        mock_popen.side_effect = FileNotFoundError("uvx not found")

        mgr = BackendManager(_write_config(tmp_path))
        mgr._connections["serena"] = dead_proc

        result = mgr.reconnect_if_needed("serena")

        assert result is False
```

**Step 2: Run the tests to verify they fail**

```bash
cd /home/fearsidhe/.claude/plugins/agent-swarm
python -m pytest tests/test_backends.py::TestReconnectIfNeeded -v
```

Expected: `AttributeError: 'BackendManager' object has no attribute 'reconnect_if_needed'`

**Step 3: Implement `reconnect_if_needed` in `lib/backends.py`**

Add after `list_tools` (around line 108), before `list`:

```python
def reconnect_if_needed(self, backend: str) -> bool:
    """Check if backend connection is alive; reconnect if dead.

    Returns True if the backend is healthy after this call, False on failure.
    Safe to call from a background thread — uses the per-backend lock.
    """
    if backend not in self._configs:
        return False
    with self._locks[backend]:
        conn = self._connections.get(backend)
        if conn is not None and conn.poll() is None:
            return True  # Already alive, nothing to do
        # Connection is dead or missing — clear stale cache and reconnect
        self._tools_cache.pop(backend, None)
        try:
            self._get_connection(backend)
            return True
        except Exception:
            return False
```

**Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_backends.py::TestReconnectIfNeeded -v
```

Expected: 4 tests PASS

**Step 5: Run the full backend test suite to check for regressions**

```bash
python -m pytest tests/test_backends.py -v
```

Expected: all tests PASS

**Step 6: Commit**

```bash
git add lib/backends.py tests/test_backends.py
git commit -m "feat: add BackendManager.reconnect_if_needed for health-check support"
```

---

### Task 2: Add health-check loop to `Controller`

**Files:**
- Modify: `lib/controller.py`

**Step 1: Write the failing test**

Find the controller test file (check `tests/` for `test_controller.py` or similar). If one exists, add to it. If not, create `tests/test_health_check.py`:

```python
#!/usr/bin/env python3
"""Tests for Controller backend health-check thread."""

import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch, call


def _make_controller(tmp_path):
    """Create a Controller with all heavy services mocked out."""
    with (
        patch("lib.controller.PermissionChecker"),
        patch("lib.controller.BackendManager") as mock_bm_cls,
        patch("lib.controller.LLMService"),
        patch("lib.controller.DataStore"),
        patch("lib.controller.Cache"),
    ):
        mock_bm = MagicMock()
        mock_bm.list.return_value = ["serena", "context7"]
        mock_bm.reconnect_if_needed.return_value = True
        mock_bm_cls.return_value = mock_bm

        from lib.controller import Controller
        ctrl = Controller(
            config_dir=tmp_path / "config",
            data_dir=tmp_path / "data",
        )
        return ctrl, mock_bm


def test_health_check_loop_calls_reconnect_for_each_backend(tmp_path):
    """Health-check loop calls reconnect_if_needed for every backend."""
    ctrl, mock_bm = _make_controller(tmp_path)

    # Allow at least one loop iteration
    time.sleep(0.2)

    calls = mock_bm.reconnect_if_needed.call_args_list
    backend_names = [c.args[0] for c in calls]
    assert "serena" in backend_names
    assert "context7" in backend_names


def test_health_check_loop_logs_warning_on_failure(tmp_path, caplog):
    """Health-check loop logs a warning when a backend can't reconnect."""
    import logging
    with (
        patch("lib.controller.PermissionChecker"),
        patch("lib.controller.BackendManager") as mock_bm_cls,
        patch("lib.controller.LLMService"),
        patch("lib.controller.DataStore"),
        patch("lib.controller.Cache"),
    ):
        mock_bm = MagicMock()
        mock_bm.list.return_value = ["serena"]
        mock_bm.reconnect_if_needed.return_value = False  # reconnect fails
        mock_bm_cls.return_value = mock_bm

        from lib.controller import Controller
        with caplog.at_level(logging.WARNING):
            ctrl = Controller(
                config_dir=tmp_path / "config",
                data_dir=tmp_path / "data",
            )
            time.sleep(0.2)

    assert any("serena" in r.message and "down" in r.message for r in caplog.records)


def test_health_check_thread_is_daemon(tmp_path):
    """Health-check thread must be daemon so it doesn't block shutdown."""
    ctrl, _ = _make_controller(tmp_path)
    threads = [t for t in threading.enumerate() if t.name == "backend-health-check"]
    assert len(threads) == 1
    assert threads[0].daemon is True
```

**Step 2: Run to verify tests fail**

```bash
python -m pytest tests/test_health_check.py -v
```

Expected: FAIL — `backend-health-check` thread not found, `reconnect_if_needed` not called.

**Step 3: Implement the health-check loop in `lib/controller.py`**

Add constant near the top of `Controller` class (after `_ROUTER_NO_SUMMARIZE`, before the class):

```python
_HEALTH_CHECK_INTERVAL = 60  # seconds between backend reconnect attempts
```

In `Controller.__init__`, immediately after the dashboard import thread block:

```python
        threading.Thread(
            target=self._health_check_loop, daemon=True, name="backend-health-check"
        ).start()
```

Add new method after `_dashboard_import_loop`:

```python
    def _health_check_loop(self) -> None:
        """Periodically reconnect any disconnected external backend.

        Runs every _HEALTH_CHECK_INTERVAL seconds. Swallows all exceptions
        so the thread never dies. Logs a warning when a backend is down.
        """
        while True:
            time.sleep(_HEALTH_CHECK_INTERVAL)
            for name in self.backends.list():
                try:
                    healthy = self.backends.reconnect_if_needed(name)
                    if not healthy:
                        log.warning(
                            "Health check: backend %s is down, reconnect failed", name
                        )
                except Exception as e:
                    log.warning("Health check error for %s: %s", name, e)
```

**Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_health_check.py -v
```

Expected: 3 tests PASS

**Step 5: Run full test suite to check for regressions**

```bash
python -m pytest tests/ -v --ignore=tests/test_develop_controller.py 2>&1 | tail -20
```

Expected: all tests PASS (or same failures as before this change).

**Step 6: Commit**

```bash
git add lib/controller.py tests/test_health_check.py
git commit -m "feat: add periodic backend health-check thread to Controller"
```

---

### Task 3: Restart the daemon to pick up the changes

**Step 1: Restart the daemon**

```bash
cd /home/fearsidhe/.claude/plugins/agent-swarm
python lib/daemon.py --shutdown && sleep 2 && python lib/daemon.py &
```

**Step 2: Verify it started**

```bash
sleep 3 && python lib/daemon.py --status
```

Expected: `Daemon is running`

**Step 3: Verify health-check thread is running**

```bash
grep "backend-health-check\|Health check" logs/daemon.log | tail -5
```

Expected: no errors; after 60s the first health-check run will appear if any backend was down.
