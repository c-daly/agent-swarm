"""Tests for manifest parsing and validation."""

import pytest

from lib.manifest import Manifest, ManifestTask, parse_manifest, validate_manifest


class TestManifestTask:
    def test_task_has_required_fields(self):
        task = ManifestTask(
            name="stack",
            description="Implement a stack",
            target_dir="src/stack",
            test_dir="tests/test_stack",
            min_tests=10,
        )
        assert task.name == "stack"
        assert task.min_tests == 10

    def test_task_default_min_tests(self):
        task = ManifestTask(
            name="stack",
            description="Implement a stack",
            target_dir="src/stack",
            test_dir="tests/test_stack",
        )
        assert task.min_tests == 5

    def test_task_branch_name(self):
        task = ManifestTask(
            name="stack",
            description="Implement a stack",
            target_dir="src/stack",
            test_dir="tests/test_stack",
        )
        assert task.branch_name == "task/stack"

    def test_task_custom_branch(self):
        task = ManifestTask(
            name="stack",
            description="Implement a stack",
            target_dir="src/stack",
            test_dir="tests/test_stack",
            branch_name="feature/custom-stack",
        )
        assert task.branch_name == "feature/custom-stack"

    def test_task_default_depends_on(self):
        task = ManifestTask(
            name="stack",
            description="Implement a stack",
            target_dir="src/stack",
            test_dir="tests/test_stack",
        )
        assert task.depends_on == []

    def test_task_custom_depends_on(self):
        task = ManifestTask(
            name="queue",
            description="Implement a queue",
            target_dir="src/queue",
            test_dir="tests/test_queue",
            depends_on=["stack"],
        )
        assert task.depends_on == ["stack"]


class TestManifest:
    def test_manifest_has_project_and_tasks(self):
        task = ManifestTask(
            name="stack",
            description="Implement a stack",
            target_dir="src/stack",
            test_dir="tests/test_stack",
        )
        manifest = Manifest(project="my-project", base_branch="main", tasks=[task])
        assert manifest.project == "my-project"
        assert len(manifest.tasks) == 1

    def test_manifest_default_base_branch(self):
        manifest = Manifest(project="my-project", tasks=[])
        assert manifest.base_branch == "main"

    def test_manifest_default_max_retries(self):
        manifest = Manifest(project="my-project", tasks=[])
        assert manifest.max_retries == 2


class TestParseManifest:
    def test_parse_valid_manifest(self, tmp_manifest_file, sample_manifest_yaml):
        path = tmp_manifest_file(sample_manifest_yaml)
        manifest = parse_manifest(path)
        assert manifest.project == "test-project"
        assert manifest.base_branch == "main"
        assert len(manifest.tasks) == 2
        assert manifest.tasks[0].name == "stack"
        assert manifest.tasks[1].name == "queue"

    def test_parse_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            parse_manifest("/nonexistent/manifest.yaml")

    def test_parse_missing_project(self, tmp_manifest_file):
        yaml_str = (
            "tasks:\n  - name: foo\n    description: bar\n"
            "    target_dir: x\n    test_dir: y\n"
        )
        path = tmp_manifest_file(yaml_str)
        with pytest.raises(ValueError, match="project"):
            parse_manifest(path)

    def test_parse_missing_tasks(self, tmp_manifest_file):
        path = tmp_manifest_file("project: foo\n")
        with pytest.raises(ValueError, match="tasks"):
            parse_manifest(path)

    def test_parse_empty_tasks(self, tmp_manifest_file):
        path = tmp_manifest_file("project: foo\ntasks: []\n")
        with pytest.raises(ValueError, match="at least one task"):
            parse_manifest(path)

    def test_parse_task_missing_name(self, tmp_manifest_file):
        yaml_str = (
            "project: foo\ntasks:\n  - description: bar\n"
            "    target_dir: x\n    test_dir: y\n"
        )
        path = tmp_manifest_file(yaml_str)
        with pytest.raises(ValueError, match="name"):
            parse_manifest(path)

    def test_parse_task_missing_description(self, tmp_manifest_file):
        yaml_str = "project: foo\ntasks:\n  - name: bar\n    target_dir: x\n    test_dir: y\n"
        path = tmp_manifest_file(yaml_str)
        with pytest.raises(ValueError, match="description"):
            parse_manifest(path)

    def test_parse_task_missing_target_dir(self, tmp_manifest_file):
        yaml_str = "project: foo\ntasks:\n  - name: bar\n    description: desc\n    test_dir: y\n"
        path = tmp_manifest_file(yaml_str)
        with pytest.raises(ValueError, match="target_dir"):
            parse_manifest(path)

    def test_parse_task_missing_test_dir(self, tmp_manifest_file):
        yaml_str = "project: foo\ntasks:\n  - name: bar\n    description: desc\n    target_dir: x\n"
        path = tmp_manifest_file(yaml_str)
        with pytest.raises(ValueError, match="test_dir"):
            parse_manifest(path)

    def test_parse_defaults_applied(self, tmp_manifest_file):
        yaml_str = """\
project: foo
tasks:
  - name: bar
    description: desc
    target_dir: x
    test_dir: y
"""
        path = tmp_manifest_file(yaml_str)
        manifest = parse_manifest(path)
        assert manifest.base_branch == "main"
        assert manifest.max_retries == 2
        assert manifest.tasks[0].min_tests == 5
        assert manifest.tasks[0].branch_name == "task/bar"

    def test_parse_custom_values(self, tmp_manifest_file):
        yaml_str = """\
project: foo
base_branch: develop
max_retries: 5
tasks:
  - name: bar
    description: desc
    target_dir: x
    test_dir: y
    min_tests: 20
    branch_name: feature/custom
"""
        path = tmp_manifest_file(yaml_str)
        manifest = parse_manifest(path)
        assert manifest.base_branch == "develop"
        assert manifest.max_retries == 5
        assert manifest.tasks[0].min_tests == 20
        assert manifest.tasks[0].branch_name == "feature/custom"


    def test_parse_depends_on(self, tmp_manifest_file):
        yaml_str = """\
project: foo
tasks:
  - name: setup
    description: Setup project
    target_dir: src
    test_dir: tests
  - name: feature
    description: Build feature
    target_dir: src/feature
    test_dir: tests/feature
    depends_on:
      - setup
"""
        path = tmp_manifest_file(yaml_str)
        manifest = parse_manifest(path)
        assert manifest.tasks[0].depends_on == []
        assert manifest.tasks[1].depends_on == ["setup"]


class TestValidateManifest:
    def test_validate_no_warnings(self, tmp_manifest_file, sample_manifest_yaml):
        path = tmp_manifest_file(sample_manifest_yaml)
        manifest = parse_manifest(path)
        warnings = validate_manifest(manifest)
        assert warnings == []

    def test_validate_duplicate_task_names(self, tmp_manifest_file):
        yaml_str = """\
project: foo
tasks:
  - name: bar
    description: desc1
    target_dir: x1
    test_dir: y1
  - name: bar
    description: desc2
    target_dir: x2
    test_dir: y2
"""
        path = tmp_manifest_file(yaml_str)
        manifest = parse_manifest(path)
        warnings = validate_manifest(manifest)
        assert any("duplicate" in w.lower() for w in warnings)

    def test_validate_low_min_tests(self, tmp_manifest_file):
        yaml_str = """\
project: foo
tasks:
  - name: bar
    description: desc
    target_dir: x
    test_dir: y
    min_tests: 1
"""
        path = tmp_manifest_file(yaml_str)
        manifest = parse_manifest(path)
        warnings = validate_manifest(manifest)
        assert any("min_tests" in w.lower() for w in warnings)

    def test_validate_duplicate_branches(self, tmp_manifest_file):
        yaml_str = """\
project: foo
tasks:
  - name: a
    description: desc
    target_dir: x1
    test_dir: y1
    branch_name: same-branch
  - name: b
    description: desc
    target_dir: x2
    test_dir: y2
    branch_name: same-branch
"""
        path = tmp_manifest_file(yaml_str)
        manifest = parse_manifest(path)
        warnings = validate_manifest(manifest)
        assert any("branch" in w.lower() for w in warnings)

    def test_validate_depends_on_unknown_task(self, tmp_manifest_file):
        yaml_str = """\
project: foo
tasks:
  - name: a
    description: desc
    target_dir: x
    test_dir: y
    depends_on:
      - nonexistent
"""
        path = tmp_manifest_file(yaml_str)
        manifest = parse_manifest(path)
        with pytest.raises(ValueError, match="nonexistent"):
            validate_manifest(manifest)

    def test_validate_self_dependency(self, tmp_manifest_file):
        yaml_str = """\
project: foo
tasks:
  - name: a
    description: desc
    target_dir: x
    test_dir: y
    depends_on:
      - a
"""
        path = tmp_manifest_file(yaml_str)
        manifest = parse_manifest(path)
        with pytest.raises(ValueError, match="[Cc]ircular"):
            validate_manifest(manifest)

    def test_validate_circular_dependency(self, tmp_manifest_file):
        yaml_str = """\
project: foo
tasks:
  - name: a
    description: desc
    target_dir: x
    test_dir: y
    depends_on:
      - b
  - name: b
    description: desc
    target_dir: x2
    test_dir: y2
    depends_on:
      - a
"""
        path = tmp_manifest_file(yaml_str)
        manifest = parse_manifest(path)
        with pytest.raises(ValueError, match="[Cc]ircular"):
            validate_manifest(manifest)

    def test_validate_deep_circular_dependency(self, tmp_manifest_file):
        yaml_str = """\
project: foo
tasks:
  - name: a
    description: desc
    target_dir: x
    test_dir: y
    depends_on:
      - c
  - name: b
    description: desc
    target_dir: x2
    test_dir: y2
    depends_on:
      - a
  - name: c
    description: desc
    target_dir: x3
    test_dir: y3
    depends_on:
      - b
"""
        path = tmp_manifest_file(yaml_str)
        manifest = parse_manifest(path)
        with pytest.raises(ValueError, match="[Cc]ircular"):
            validate_manifest(manifest)

    def test_validate_valid_dependencies(self, tmp_manifest_file):
        yaml_str = """\
project: foo
tasks:
  - name: a
    description: desc
    target_dir: x
    test_dir: y
  - name: b
    description: desc
    target_dir: x2
    test_dir: y2
    depends_on:
      - a
  - name: c
    description: desc
    target_dir: x3
    test_dir: y3
    depends_on:
      - a
      - b
"""
        path = tmp_manifest_file(yaml_str)
        manifest = parse_manifest(path)
        warnings = validate_manifest(manifest)
        assert not any("depend" in w.lower() or "circular" in w.lower() for w in warnings)
