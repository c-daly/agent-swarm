---
name: plan-to-manifest
description: "Translate a superpowers implementation plan into a parallel orchestration YAML manifest"
---

# Plan to Manifest

Translate a superpowers-style implementation plan (Markdown) into a parallel orchestration manifest (YAML).

**Usage:** `/plan-to-manifest <path-to-plan.md>`

---

## Process

Follow these steps exactly:

### 1. Read the plan file

Read the file passed as the argument. If the file doesn't exist or isn't readable, report the error and stop.

### 2. Extract project name

Find the top-level heading matching `# <Name> - Implementation Plan`.

Slugify the name portion:
- Lowercase
- Replace spaces with hyphens
- Strip non-alphanumeric characters (except hyphens)
- Collapse multiple hyphens into one

Example: `"Svelte Todo List"` becomes `"svelte-todo-list"`

### 3. Parse each task

Locate every `### Task N: <Title>` section. For each task, extract:

- **name**: Slugify the task number and title together. Example: `"Task 3: Todo Store"` becomes `"3-todo-store"`
- **description**: Combine the description paragraph, `**Do:**` bullets, and `**Verify:**` bullets into a single multiline string. Preserve the original wording faithfully.
- **depends_on**: If the task has a `**Depends on:** Task N, Task M` line, parse the referenced task numbers, look up their slugified names, and list them as dependencies.
- **target_dir**: Infer from file paths in Do/Verify bullets (see directory inference rules below).
- **test_dir**: Infer from file paths in Do/Verify bullets (see directory inference rules below).

#### Implicit dependency detection

After parsing all tasks, if **no tasks** have explicit `**Depends on:**` markers, warn the user:

> No dependency markers found. Tasks will all run in parallel. Should I analyze file references to detect implicit dependencies?

If the user agrees (or if some but not all tasks have markers), perform implicit analysis:

1. For each task, collect all file paths from its Do/Verify bullets.
2. For each pair of tasks (A, B), check if Task B references (imports, reads, or extends) a file that Task A creates or modifies.
3. If a cross-reference is found, suggest the dependency to the user:
   > Task B ("<name>") references `<file>` which Task A ("<name>") creates. Add dependency B → A?
4. The user can accept, reject, or choose **"skip all"** to stop further suggestions.
5. Add accepted dependencies to the manifest.

### 4. Directory inference rules

Scan all Do and Verify bullets for file paths (patterns like `src/foo/bar.py`, `tests/something.ts`, `Create src/lib/store.ts`):

- Paths containing `/test` or `/tests` or starting with `test` are candidates for **test_dir**. Extract the directory portion (strip the filename).
- Other paths with file extensions (`.py`, `.ts`, `.js`, `.rs`, `.go`, `.jsx`, `.tsx`, `.svelte`, `.vue`, `.rb`, `.java`, `.kt`, `.swift`, `.c`, `.cpp`, `.h`, etc.) are candidates for **target_dir**. Extract the directory portion.
- If multiple candidates exist for either directory, pick the most specific common directory (longest common prefix that is a complete directory path).
- **If inference fails** for a task (no file paths found, or paths are ambiguous), ask the user: `"I couldn't determine target_dir/test_dir for task '<name>'. What directories should it use?"`

### 5. Generate YAML

Produce the manifest with this structure:

```yaml
project: <slugified-project-name>
base_branch: main
max_retries: 2

tasks:
  - name: <slugified-name>
    description: |
      <combined description>
    target_dir: <inferred-target-dir>
    test_dir: <inferred-test-dir>
    depends_on:  # only include if the task has dependencies
      - <dep-slug>
```

Do not set `min_tests` explicitly unless the plan specifies a test count. The default is 5.

### 6. Write the output file

Write the YAML to `<plan-basename>-manifest.yaml` in the same directory as the input plan.

Example: `docs/plans/my-plan.md` produces `docs/plans/my-plan-manifest.yaml`

### 7. Report

Tell the user the output path and summarize how many tasks were extracted.

### 8. Confirm execution

Show a manifest summary table:

```
| Task | Dependencies | target_dir | test_dir |
|------|-------------|------------|----------|
| ...  | ...         | ...        | ...      |
```

Ask the user: **Proceed to orchestration / Edit the manifest first / Stop**

### 9. Hand off to orchestrator

If the user chose to proceed, invoke `agent-swarm:parallel-orchestrate` with the generated manifest path. This is a **REQUIRED SUB-SKILL** — do not skip the handoff.

---

## Example

**Input** (`docs/plans/api-plan.md`):

```markdown
# Simple API - Implementation Plan

## Tasks

### Task 1: Project Setup

Initialize the Node.js project.

**Do:**
- Create `src/server.js` with Express app
- Create `tests/server.test.js`

**Verify:**
- Server starts on port 3000

---

### Task 2: Todo Model

Create the data model.

**Depends on:** Task 1

**Do:**
- Create `src/models/todo.js`
- Create `tests/models/todo.test.js`

**Verify:**
- CRUD functions work
```

**Output** (`docs/plans/api-plan-manifest.yaml`):

```yaml
project: simple-api
base_branch: main
max_retries: 2

tasks:
  - name: 1-project-setup
    description: |
      Initialize the Node.js project.

      Do:
      - Create `src/server.js` with Express app
      - Create `tests/server.test.js`

      Verify:
      - Server starts on port 3000
    target_dir: src
    test_dir: tests

  - name: 2-todo-model
    description: |
      Create the data model.

      Do:
      - Create `src/models/todo.js`
      - Create `tests/models/todo.test.js`

      Verify:
      - CRUD functions work
    target_dir: src/models
    test_dir: tests/models
    depends_on:
      - 1-project-setup
```

---

## Rules

- Never add tasks that aren't in the plan.
- Never remove tasks from the plan.
- Preserve the original task descriptions faithfully.
- Ask the user when directories can't be inferred.
- Default `min_tests` to 5 (don't set it explicitly unless the plan specifies a count).
