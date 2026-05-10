# `config/workflows/` — workflow definition YAMLs

## What the daemon actually consumes

`lib/daemon.py:load_workflow_configs` reads from each `<name>.yaml`:

- `name` (top-level)
- `description` (top-level — informational, not enforced)
- `initial_phase`, `terminal_phase`
- `phases[*].name` and `phases[*].checkpoint`
- `transitions` (mapping `src_phase -> [target_phases]`)

**Everything else in the YAML is ignored at the daemon layer.**

## Aspirational fields and what (if anything) reads them

- `max_iterations`, `max_agents`, `max_review_retries`, `max_agent_respawns` — only consumed by per-workflow Python *engines* (`lib/develop_workflow.py`, `lib/pr_comment_workflow.py`). For workflows without a Python engine (e.g. `simple`), these are **dead** — silently ignored. Don't add them unless you're also writing the engine, or expect them to take effect.
- `phases[*].allowed_tool_categories`, `phases[*].blocked_tools`, `phases[*].eligible_agents` — informational at the YAML layer. Per-tool permissions are enforced via `config/permissions.yaml`, not from these fields. Best practice: keep them mirrored to the permissions block (defense-in-depth) but don't rely on the YAML alone for enforcement.

## Critical gotcha: adding a new workflow

When you add a new YAML here, you MUST also:

1. Add the workflow ID to `lib/permission_query.py:_KNOWN_WORKFLOWS`. Without that, `get_active_workflow_id()` returns `None` for it, `get_permissions()` returns `None`, and `is_tool_allowed()` returns `(True, "")` — **fail-open**. Every restriction in `config/permissions.yaml` is bypassed.
2. Add a peer block under `workflows:` in `config/permissions.yaml` defining per-phase `allowed`/`blocked` tool lists.
3. Restart the daemon (`bin/start-daemon` is idempotent — kill + restart). The daemon loads workflow configs once at startup; no hot-reload.

PR #93 fix `75be6c2` closed the `_KNOWN_WORKFLOWS` gap for `simple`. **The same gap still applies to `develop`, `experiment`, `orchestrate`, `pr_review`** — tracked in `<vault>/10-projects/agent-swarm/open-recommendations.md`. Better long-term fix: derive `_KNOWN_WORKFLOWS` dynamically from the daemon's loaded configs.

## Existing workflows (for reference)

- `simple.yaml` — 4-phase lightweight default (auto-start at session start). `plan` → `work` → `verify` → `done`. Plan and verify are checkpoints; verify can loop back to work.
- `iterate.yaml` — TDD-style. `test_writing` → `implement` → `test` → `review`.
- `develop.yaml` — full PR-based SE team simulation. `intake` → `research` → `design` → `branch` → `test_writing` → `implement` → `test` → `review` → `merge` → `acceptance` → `complete`.
- `pr_comment.yaml` — PR review comment workflow. `understand` → `fix` → `verify` → `push` → `check_reviews` → `done`.
- `orchestrate.yaml` — orchestrator workflow.
- `experiment.yaml` — experiment workflow with eval gates.
