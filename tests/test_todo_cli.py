"""Tests for the todo CLI tool."""

import json
import os
import subprocess
import sys
from pathlib import Path


# Add bin directory to path for imports
BIN_DIR = Path(__file__).parent.parent / "bin"
sys.path.insert(0, str(BIN_DIR))


class TestTodoStorage:
    """Test the JSON storage functionality."""

    def test_storage_file_created_on_first_add(self, tmp_path):
        """Storage file should be created when first task is added."""
        storage_file = tmp_path / "user_tasks.json"
        env = os.environ.copy()
        env["TODO_STORAGE_PATH"] = str(storage_file)

        result = subprocess.run(
            [sys.executable, str(BIN_DIR / "todo"), "add", "Test task"],
            capture_output=True,
            text=True,
            env=env,
        )

        assert result.returncode == 0
        assert storage_file.exists()

    def test_storage_preserves_tasks_between_runs(self, tmp_path):
        """Tasks should persist between CLI invocations."""
        storage_file = tmp_path / "user_tasks.json"
        env = os.environ.copy()
        env["TODO_STORAGE_PATH"] = str(storage_file)

        # Add a task
        subprocess.run(
            [sys.executable, str(BIN_DIR / "todo"), "add", "Persistent task"],
            capture_output=True,
            text=True,
            env=env,
        )

        # List tasks in new process
        result = subprocess.run(
            [sys.executable, str(BIN_DIR / "todo"), "list"],
            capture_output=True,
            text=True,
            env=env,
        )

        assert "Persistent task" in result.stdout


class TestAddCommand:
    """Test the 'add' command."""

    def test_add_creates_task_with_pending_status(self, tmp_path):
        """Adding a task should create it with pending status."""
        storage_file = tmp_path / "user_tasks.json"
        env = os.environ.copy()
        env["TODO_STORAGE_PATH"] = str(storage_file)

        subprocess.run(
            [sys.executable, str(BIN_DIR / "todo"), "add", "New task"],
            capture_output=True,
            text=True,
            env=env,
        )

        with open(storage_file) as f:
            data = json.load(f)

        assert len(data["tasks"]) == 1
        assert data["tasks"][0]["description"] == "New task"
        assert data["tasks"][0]["status"] == "pending"

    def test_add_assigns_incrementing_ids(self, tmp_path):
        """Each task should get a unique incrementing ID."""
        storage_file = tmp_path / "user_tasks.json"
        env = os.environ.copy()
        env["TODO_STORAGE_PATH"] = str(storage_file)

        for i in range(3):
            subprocess.run(
                [sys.executable, str(BIN_DIR / "todo"), "add", f"Task {i}"],
                capture_output=True,
                text=True,
                env=env,
            )

        with open(storage_file) as f:
            data = json.load(f)

        ids = [t["id"] for t in data["tasks"]]
        assert ids == [1, 2, 3]

    def test_add_outputs_confirmation(self, tmp_path):
        """Add command should output a confirmation message."""
        storage_file = tmp_path / "user_tasks.json"
        env = os.environ.copy()
        env["TODO_STORAGE_PATH"] = str(storage_file)

        result = subprocess.run(
            [sys.executable, str(BIN_DIR / "todo"), "add", "Confirm task"],
            capture_output=True,
            text=True,
            env=env,
        )

        assert "Added" in result.stdout or "added" in result.stdout


class TestListCommand:
    """Test the 'list' command."""

    def test_list_shows_all_tasks(self, tmp_path):
        """List should show all tasks."""
        storage_file = tmp_path / "user_tasks.json"
        env = os.environ.copy()
        env["TODO_STORAGE_PATH"] = str(storage_file)

        # Add multiple tasks
        for desc in ["Task A", "Task B", "Task C"]:
            subprocess.run(
                [sys.executable, str(BIN_DIR / "todo"), "add", desc],
                capture_output=True,
                text=True,
                env=env,
            )

        result = subprocess.run(
            [sys.executable, str(BIN_DIR / "todo"), "list"],
            capture_output=True,
            text=True,
            env=env,
        )

        assert "Task A" in result.stdout
        assert "Task B" in result.stdout
        assert "Task C" in result.stdout

    def test_list_shows_pending_with_circle(self, tmp_path):
        """Pending tasks should show with circle symbol."""
        storage_file = tmp_path / "user_tasks.json"
        env = os.environ.copy()
        env["TODO_STORAGE_PATH"] = str(storage_file)

        subprocess.run(
            [sys.executable, str(BIN_DIR / "todo"), "add", "Pending task"],
            capture_output=True,
            text=True,
            env=env,
        )

        result = subprocess.run(
            [sys.executable, str(BIN_DIR / "todo"), "list"],
            capture_output=True,
            text=True,
            env=env,
        )

        # Should have circle symbol for pending
        assert "\u25cb" in result.stdout  # circle

    def test_list_shows_in_progress_with_arrow(self, tmp_path):
        """In-progress tasks should show with arrow symbol."""
        storage_file = tmp_path / "user_tasks.json"
        env = os.environ.copy()
        env["TODO_STORAGE_PATH"] = str(storage_file)

        subprocess.run(
            [sys.executable, str(BIN_DIR / "todo"), "add", "WIP task"],
            capture_output=True,
            text=True,
            env=env,
        )
        subprocess.run(
            [sys.executable, str(BIN_DIR / "todo"), "start", "1"],
            capture_output=True,
            text=True,
            env=env,
        )

        result = subprocess.run(
            [sys.executable, str(BIN_DIR / "todo"), "list"],
            capture_output=True,
            text=True,
            env=env,
        )

        # Should have arrow symbol for in-progress
        assert "\u25b6" in result.stdout  # arrow

    def test_list_shows_done_with_checkmark(self, tmp_path):
        """Completed tasks should show with checkmark symbol."""
        storage_file = tmp_path / "user_tasks.json"
        env = os.environ.copy()
        env["TODO_STORAGE_PATH"] = str(storage_file)

        subprocess.run(
            [sys.executable, str(BIN_DIR / "todo"), "add", "Done task"],
            capture_output=True,
            text=True,
            env=env,
        )
        subprocess.run(
            [sys.executable, str(BIN_DIR / "todo"), "done", "1"],
            capture_output=True,
            text=True,
            env=env,
        )

        result = subprocess.run(
            [sys.executable, str(BIN_DIR / "todo"), "list"],
            capture_output=True,
            text=True,
            env=env,
        )

        # Should have checkmark symbol for done
        assert "\u2713" in result.stdout  # checkmark

    def test_list_shows_task_ids(self, tmp_path):
        """List should show task IDs in brackets."""
        storage_file = tmp_path / "user_tasks.json"
        env = os.environ.copy()
        env["TODO_STORAGE_PATH"] = str(storage_file)

        subprocess.run(
            [sys.executable, str(BIN_DIR / "todo"), "add", "ID test"],
            capture_output=True,
            text=True,
            env=env,
        )

        result = subprocess.run(
            [sys.executable, str(BIN_DIR / "todo"), "list"],
            capture_output=True,
            text=True,
            env=env,
        )

        assert "[1]" in result.stdout

    def test_list_empty_shows_message(self, tmp_path):
        """Empty list should show helpful message."""
        storage_file = tmp_path / "user_tasks.json"
        env = os.environ.copy()
        env["TODO_STORAGE_PATH"] = str(storage_file)

        result = subprocess.run(
            [sys.executable, str(BIN_DIR / "todo"), "list"],
            capture_output=True,
            text=True,
            env=env,
        )

        assert "No tasks" in result.stdout or "empty" in result.stdout.lower()


class TestDoneCommand:
    """Test the 'done' command."""

    def test_done_marks_task_complete(self, tmp_path):
        """Done command should mark task as complete."""
        storage_file = tmp_path / "user_tasks.json"
        env = os.environ.copy()
        env["TODO_STORAGE_PATH"] = str(storage_file)

        subprocess.run(
            [sys.executable, str(BIN_DIR / "todo"), "add", "Complete me"],
            capture_output=True,
            text=True,
            env=env,
        )
        subprocess.run(
            [sys.executable, str(BIN_DIR / "todo"), "done", "1"],
            capture_output=True,
            text=True,
            env=env,
        )

        with open(storage_file) as f:
            data = json.load(f)

        assert data["tasks"][0]["status"] == "done"

    def test_done_invalid_id_shows_error(self, tmp_path):
        """Done with invalid ID should show error."""
        storage_file = tmp_path / "user_tasks.json"
        env = os.environ.copy()
        env["TODO_STORAGE_PATH"] = str(storage_file)

        result = subprocess.run(
            [sys.executable, str(BIN_DIR / "todo"), "done", "999"],
            capture_output=True,
            text=True,
            env=env,
        )

        assert result.returncode != 0 or "not found" in result.stdout.lower() or "not found" in result.stderr.lower()


class TestStartCommand:
    """Test the 'start' command."""

    def test_start_marks_task_in_progress(self, tmp_path):
        """Start command should mark task as in-progress."""
        storage_file = tmp_path / "user_tasks.json"
        env = os.environ.copy()
        env["TODO_STORAGE_PATH"] = str(storage_file)

        subprocess.run(
            [sys.executable, str(BIN_DIR / "todo"), "add", "Start me"],
            capture_output=True,
            text=True,
            env=env,
        )
        subprocess.run(
            [sys.executable, str(BIN_DIR / "todo"), "start", "1"],
            capture_output=True,
            text=True,
            env=env,
        )

        with open(storage_file) as f:
            data = json.load(f)

        assert data["tasks"][0]["status"] == "in_progress"

    def test_start_invalid_id_shows_error(self, tmp_path):
        """Start with invalid ID should show error."""
        storage_file = tmp_path / "user_tasks.json"
        env = os.environ.copy()
        env["TODO_STORAGE_PATH"] = str(storage_file)

        result = subprocess.run(
            [sys.executable, str(BIN_DIR / "todo"), "start", "999"],
            capture_output=True,
            text=True,
            env=env,
        )

        assert result.returncode != 0 or "not found" in result.stdout.lower() or "not found" in result.stderr.lower()


class TestRemoveCommand:
    """Test the 'remove' command."""

    def test_remove_deletes_task(self, tmp_path):
        """Remove command should delete the task."""
        storage_file = tmp_path / "user_tasks.json"
        env = os.environ.copy()
        env["TODO_STORAGE_PATH"] = str(storage_file)

        subprocess.run(
            [sys.executable, str(BIN_DIR / "todo"), "add", "Delete me"],
            capture_output=True,
            text=True,
            env=env,
        )
        subprocess.run(
            [sys.executable, str(BIN_DIR / "todo"), "remove", "1"],
            capture_output=True,
            text=True,
            env=env,
        )

        with open(storage_file) as f:
            data = json.load(f)

        assert len(data["tasks"]) == 0

    def test_remove_invalid_id_shows_error(self, tmp_path):
        """Remove with invalid ID should show error."""
        storage_file = tmp_path / "user_tasks.json"
        env = os.environ.copy()
        env["TODO_STORAGE_PATH"] = str(storage_file)

        result = subprocess.run(
            [sys.executable, str(BIN_DIR / "todo"), "remove", "999"],
            capture_output=True,
            text=True,
            env=env,
        )

        assert result.returncode != 0 or "not found" in result.stdout.lower() or "not found" in result.stderr.lower()


class TestClearCommand:
    """Test the 'clear' command."""

    def test_clear_removes_only_completed_tasks(self, tmp_path):
        """Clear should only remove completed tasks."""
        storage_file = tmp_path / "user_tasks.json"
        env = os.environ.copy()
        env["TODO_STORAGE_PATH"] = str(storage_file)

        # Add tasks with different statuses
        subprocess.run(
            [sys.executable, str(BIN_DIR / "todo"), "add", "Pending task"],
            capture_output=True,
            text=True,
            env=env,
        )
        subprocess.run(
            [sys.executable, str(BIN_DIR / "todo"), "add", "Done task"],
            capture_output=True,
            text=True,
            env=env,
        )
        subprocess.run(
            [sys.executable, str(BIN_DIR / "todo"), "done", "2"],
            capture_output=True,
            text=True,
            env=env,
        )
        subprocess.run(
            [sys.executable, str(BIN_DIR / "todo"), "add", "In progress"],
            capture_output=True,
            text=True,
            env=env,
        )
        subprocess.run(
            [sys.executable, str(BIN_DIR / "todo"), "start", "3"],
            capture_output=True,
            text=True,
            env=env,
        )

        # Clear completed
        subprocess.run(
            [sys.executable, str(BIN_DIR / "todo"), "clear"],
            capture_output=True,
            text=True,
            env=env,
        )

        with open(storage_file) as f:
            data = json.load(f)

        # Should only have pending and in_progress tasks
        assert len(data["tasks"]) == 2
        statuses = [t["status"] for t in data["tasks"]]
        assert "done" not in statuses
        assert "pending" in statuses
        assert "in_progress" in statuses


class TestCLIInterface:
    """Test general CLI interface behavior."""

    def test_no_args_shows_help(self, tmp_path):
        """Running with no args should show help or usage."""
        storage_file = tmp_path / "user_tasks.json"
        env = os.environ.copy()
        env["TODO_STORAGE_PATH"] = str(storage_file)

        result = subprocess.run(
            [sys.executable, str(BIN_DIR / "todo")],
            capture_output=True,
            text=True,
            env=env,
        )

        output = result.stdout + result.stderr
        assert "usage" in output.lower() or "help" in output.lower() or "command" in output.lower()

    def test_unknown_command_shows_error(self, tmp_path):
        """Unknown command should show error."""
        storage_file = tmp_path / "user_tasks.json"
        env = os.environ.copy()
        env["TODO_STORAGE_PATH"] = str(storage_file)

        result = subprocess.run(
            [sys.executable, str(BIN_DIR / "todo"), "invalid_cmd"],
            capture_output=True,
            text=True,
            env=env,
        )

        assert result.returncode != 0
