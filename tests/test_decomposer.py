"""Tests for the spec decomposer."""

import json
import pytest
from pathlib import Path
from unittest.mock import patch
from datetime import datetime

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from decomposer import (
    decompose_spec,
    parse_spec_sections,
    generate_task,
    TaskPriority,
)


class TestParseSpecSections:
    """Test parsing spec files into sections."""

    def test_identifies_code_blocks_as_implementation_units(self):
        """Code blocks with class/function definitions become tasks."""
        spec = """
# My Spec

## Data Structures

### Task Dataclass

```python
@dataclass
class Task:
    id: str
    description: str
```

### TaskStatus Enum

```python
class TaskStatus(str, Enum):
    PENDING = "pending"
```
"""
        sections = parse_spec_sections(spec)
        assert len(sections) >= 2
        assert any("Task Dataclass" in s["title"] for s in sections)
        assert any("TaskStatus Enum" in s["title"] for s in sections)

    def test_identifies_method_sections(self):
        """Method descriptions in spec become tasks."""
        spec = """
## Core Methods

#### add_task(task: Task) -> str
- Add a task to the queue
- Returns the task ID

#### get_task(task_id: str) -> Optional[Task]
- Retrieve a task by ID
"""
        sections = parse_spec_sections(spec)
        assert len(sections) >= 2
        assert any("add_task" in s["title"] for s in sections)
        assert any("get_task" in s["title"] for s in sections)

    def test_identifies_cli_commands(self):
        """CLI command sections become tasks."""
        spec = """
## CLI Commands

### queue add
```bash
python3 iterate_state.py queue add "Task description"
```
- Creates a new task

### queue list
```bash
python3 iterate_state.py queue list
```
- Lists tasks
"""
        sections = parse_spec_sections(spec)
        assert any("queue add" in s["title"] for s in sections)
        assert any("queue list" in s["title"] for s in sections)

    def test_groups_related_items(self):
        """Related enums/constants can be grouped into one task."""
        spec = """
## Enums

### TaskStatus Enum
```python
class TaskStatus(str, Enum):
    PENDING = "pending"
```

### TaskSource Enum
```python
class TaskSource(str, Enum):
    ORIGINAL = "original"
```

### Priority Constants
```python
PRIORITY_TEST_FAILURE = 0
PRIORITY_ORIGINAL = 3
```
"""
        sections = parse_spec_sections(spec, group_enums=True)
        # Should group all enums/constants into fewer tasks
        enum_sections = [s for s in sections if "enum" in s["title"].lower() or "constant" in s["title"].lower()]
        # Either grouped or separate, but recognized
        assert len(enum_sections) >= 1


class TestGenerateTask:
    """Test task generation from parsed sections."""

    def test_generates_task_with_required_fields(self):
        """Generated task has all required fields."""
        section = {
            "title": "Implement Task dataclass",
            "content": "Add Task dataclass with id, description, status fields",
            "type": "dataclass"
        }
        task = generate_task(section, pr_id="pr-001")

        assert "id" in task
        assert task["id"].startswith("task-")
        assert task["description"] == "Implement Task dataclass"
        assert task["status"] == "pending"
        assert task["priority"] == TaskPriority.ORIGINAL
        assert task["source"] == "original"
        assert task["pr_id"] == "pr-001"
        assert task["phase"] == "test_writing"
        assert task["iteration"] == 0
        assert "created_at" in task
        assert "metadata" in task

    def test_task_id_is_unique(self):
        """Each generated task has a unique ID."""
        section = {"title": "Test", "content": "Test content", "type": "function"}
        task1 = generate_task(section, pr_id="pr-001")
        task2 = generate_task(section, pr_id="pr-001")
        assert task1["id"] != task2["id"]

    def test_metadata_includes_spec_reference(self):
        """Metadata includes reference to original spec section."""
        section = {
            "title": "add_task method",
            "content": "Add a task to the queue",
            "type": "method",
            "spec_file": "task-queue-core.md",
            "line_number": 42
        }
        task = generate_task(section, pr_id="pr-001")
        assert task["metadata"]["spec_file"] == "task-queue-core.md"
        assert task["metadata"]["line_number"] == 42


class TestDecomposeSpec:
    """Test full spec decomposition."""

    def test_decomposes_spec_file(self, tmp_path):
        """Decompose a spec file into tasks."""
        spec_content = """
# Task Queue Core

## Data Structures

### Task Dataclass
```python
@dataclass
class Task:
    id: str
```

## Methods

#### add_task(task: Task) -> str
Add a task to the queue.
"""
        spec_file = tmp_path / "test-spec.md"
        spec_file.write_text(spec_content)

        tasks = decompose_spec(str(spec_file), pr_id="pr-001")

        assert len(tasks) >= 2
        assert all(t["pr_id"] == "pr-001" for t in tasks)
        assert all(t["status"] == "pending" for t in tasks)

    def test_returns_empty_for_empty_spec(self, tmp_path):
        """Empty spec returns empty task list."""
        spec_file = tmp_path / "empty.md"
        spec_file.write_text("")

        tasks = decompose_spec(str(spec_file), pr_id="pr-001")
        assert tasks == []

    def test_tasks_are_ordered_by_dependency(self, tmp_path):
        """Data structures come before methods that use them."""
        spec_content = """
# Spec

## Methods
#### use_task(t: Task)
Uses Task object.

## Data Structures
### Task Dataclass
The Task class.
"""
        spec_file = tmp_path / "spec.md"
        spec_file.write_text(spec_content)

        tasks = decompose_spec(str(spec_file), pr_id="pr-001")

        # Data structure tasks should come before method tasks
        dataclass_idx = next(i for i, t in enumerate(tasks) if "dataclass" in t["description"].lower() or "task" in t["description"].lower())
        method_idx = next(i for i, t in enumerate(tasks) if "use_task" in t["description"].lower())
        assert dataclass_idx < method_idx

    def test_output_format_matches_queue_schema(self, tmp_path):
        """Output matches the TaskQueue expected format."""
        spec_content = """
# Spec
## Item
### Thing
Do something.
"""
        spec_file = tmp_path / "spec.md"
        spec_file.write_text(spec_content)

        tasks = decompose_spec(str(spec_file), pr_id="pr-001")

        if tasks:
            task = tasks[0]
            # Verify schema compliance
            required_fields = ["id", "description", "status", "priority", "source",
                             "pr_id", "assigned_agent", "phase", "iteration",
                             "created_at", "metadata"]
            for field in required_fields:
                assert field in task, f"Missing field: {field}"


class TestCLIInterface:
    """Test CLI interface for decomposer."""

    def test_cli_outputs_json(self, tmp_path, capsys):
        """CLI outputs tasks as JSON."""
        spec_content = """
# Spec
## Data
### Item
Something.
"""
        spec_file = tmp_path / "spec.md"
        spec_file.write_text(spec_content)

        # Import main and run
        from decomposer import main
        import sys

        old_argv = sys.argv
        try:
            sys.argv = ["decomposer", str(spec_file), "--pr", "pr-001", "--json"]
            main()
            captured = capsys.readouterr()
            result = json.loads(captured.out)
            assert isinstance(result, list)
        except SystemExit:
            pass
        finally:
            sys.argv = old_argv

    def test_cli_can_write_to_file(self, tmp_path):
        """CLI can write tasks to output file."""
        spec_content = """
# Spec
## Data
### Item
Something.
"""
        spec_file = tmp_path / "spec.md"
        spec_file.write_text(spec_content)
        output_file = tmp_path / "tasks.json"

        from decomposer import main
        import sys

        old_argv = sys.argv
        try:
            sys.argv = ["decomposer", str(spec_file), "--pr", "pr-001", "--output", str(output_file)]
            main()
            assert output_file.exists()
            tasks = json.loads(output_file.read_text())
            assert isinstance(tasks, list)
        except SystemExit:
            pass
        finally:
            sys.argv = old_argv
