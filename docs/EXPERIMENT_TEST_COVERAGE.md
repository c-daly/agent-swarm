# Experiment Subsystem — Test Coverage

**Scope:** the experiment (reader, writer) store and its MCP server.
**Modules:** `lib/experiment_store.py`, `lib/experiment_server.py`
**Tests:** `tests/test_experiment_store.py` (40), `tests/test_experiment_server.py` (15), `tests/test_experiment_wiring.py` (2) — 57 total.
**Measured:** 2026-08-14, branch `feat/experiment-writer-contract`, coverage.py 7.15 (`--branch`).

---

## Headline numbers

Branch coverage of the two modules under the experiment test files:

| Module | Stmts | Miss | Branch | BrPart | Cover |
|---|---:|---:|---:|---:|---:|
| `lib/experiment_store.py`  | 215 |  5 | 40 | 5 | **96%** |
| `lib/experiment_server.py` |  96 | 30 | 36 | 2 | **65%** |
| **Total** | 311 | 35 | 76 | 7 | **86%** |

The two percentages must be read, not taken at face value — see below. The
`store` number is a true 96%; the `server` number is dragged down entirely by
the stdio transport loop, which the unit tests bypass by design. On the
**dispatch/routing logic** the server is effectively 100%.

---

## How to reproduce

`coverage` is not in the daemon's Python (PEP 668 externally-managed). Use a
throwaway venv that inherits the system `pytest`/`pyyaml`:

```sh
python3 -m venv --system-site-packages /tmp/covenv
/tmp/covenv/bin/pip install coverage
cd <plugin-root>
/tmp/covenv/bin/python -m coverage run --branch -m pytest \
  tests/test_experiment_store.py tests/test_experiment_server.py -q
/tmp/covenv/bin/python -m coverage report -m \
  --include="*/lib/experiment_store.py,*/lib/experiment_server.py"
```

`--include` (not `--source`) is required: the tests import `experiment_store`
as a top-level module via a `sys.path` shim, so `--source` by file path finds
no data.

---

## What is covered

Behavior-first — the tests assert outcomes on real filesystems and through the
real dispatch path, not internal state or mocks.

**Store (`experiment_store.py`):**
- Run lifecycle: `start_run` → `record_observation` → `end_run`, with outcome +
  metrics round-tripping through `run.json`.
- Durability across fresh instances (write via one store, read via another).
- Sequential observation numbering; per-experiment run scoping.
- YAML-frontmatter observation (de)serialization incl. multi-paragraph prose.
- Presence-gated memory mirroring: mirrors when the sink is available, skips
  when unavailable/`None`, and — the load-bearing guarantee — **a raising sink
  never breaks or prevents the authoritative base write.**
- Tenancy guard `validate_experiment_name`: rejects `..`, `/`, `\`, leading-dot,
  and empty/whitespace names at every entry point (`start_run`, `list_runs`,
  `VaultExperimentStore.__init__`).
- `MemoryPluginSink.record()` real subprocess integration: correct argv + body
  on stdin, `RuntimeError` on non-zero exit, and the `VAULT_DIR → MEMORY_VAULT_DIR`
  env bridge reaching the child process.
- Backend-selection factory (`make_experiment_backend`) and writer wrapping
  (`open_experiment_writer`), with/without memory.

**Server (`experiment_server.py`):**
- `handle_call` dispatch for all six tools (`start_run`, `record_observation`,
  `end_run`, `list_runs`, `get_run`, `observations`).
- Per-project routing to distinct vault subtrees; `stores_for` cache identity
  (same project → same store; different projects → distinct stores).
- `store_from_env` backend/project resolution; default-project fallback.
- Error contract `(text, is_error)`: unknown tool, missing run, invalid
  (traversal) experiment name, and missing required arg all return an error
  tuple rather than raising.

**Wiring (`test_experiment_wiring.py`):**
- `backends.json` registers the `experiment` backend with `tool_prefix`
  `experiment` and the correct server command (real JSON parse).
- `permissions.yaml` `global.allowed` grants `experiment__*` (real YAML parse,
  exact-string membership — catches the `experiment_*` single-underscore typo).

---

## What is NOT covered (and why)

### Store — the 5 uncovered lines are all deferred error paths

| Line | Code | Backlog |
|---|---|---|
| `201` | `record_observation` on a nonexistent run → `KeyError` | MEDIUM |
| `251` | `_split_run_id` malformed run_id → `KeyError` | MEDIUM |
| `234` | `observations()` returns `[]` for a missing journal dir | LOW |
| `153` | `_parse_observation` on a frontmatter-less (corrupt) file | LOW |
| `421` | `make_experiment_backend` vault-dir-missing → `ValueError` | LOW |

Every one is a defensive raise, and they line up exactly with the MEDIUM/LOW
backlog (see `<vault>/10-projects/agent-swarm/open-recommendations.md`).
Coverage independently confirms the triage: **nothing load-bearing is dark.**

### Server — the 35% miss is transport + boilerplate, not logic

Uncovered: `23` (the `sys.path` shim), `197–236` (the `run_server()` stdio
JSON-RPC loop), `241` (`__main__` guard). The branch/routing logic
(`handle_call`, `store_from_env`, `ExperimentServer`, serialization, `TOOLS`)
has **zero uncovered statements**.

`run_server()` is the one genuinely CI-untested piece. It is currently
exercised only by the manual live-verify step (spawn the router backend after a
daemon restart and call `mcp__router__experiment__*`). A subprocess smoke test —
spawn the server on stdio, send `initialize` / `tools/call`, assert the framed
response — would close it and mirror `workflow_server.py`. Tracked as a
follow-up, not one of the three hardening gaps below.

---

## Provenance

An adversarial test-quality review (2026-08-14) found three HIGH-risk gaps in
the first cut of these suites; all three were closed with regression-locking
tests, which is what lifts store coverage to 96% and server-logic coverage to
~100%:

1. `validate_experiment_name` path-traversal guard — was 0% (deletable without
   turning the suite red); now fully exercised. It passed on first run, so the
   guard was already wired and enforcing — the hole was in the *tests*, not the
   code.
2. `MemoryPluginSink.record()` subprocess integration — was 0%; now covers the
   invocation, the non-zero-exit `RuntimeError`, and the env bridge.
3. `experiment_list_runs` dispatch + the server error branches — the tool was
   never routed through `handle_call`; now round-trips, and both error branches
   are covered.

---

## Caveat

These are **line/branch** coverage numbers — "executed," not "meaningfully
asserted." The value of the suite is that it asserts *outcomes* on the paths
that matter (traversal actually rejected, subprocess failure actually
propagated, projects actually land in distinct subtrees), not merely that the
lines ran. Treat the percentage as a floor on what is checked, not a ceiling.
