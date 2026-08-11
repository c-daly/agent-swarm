# `bin/` — shell scripts for daemon and cache management

## Dev/cache discipline (load-bearing)

- **Dev path:** `~/.claude/plugins/agent-swarm/` is what `bin/sync-to-cache` treats as the canonical source. Edits live there.
- **Cache path:** `~/.claude/plugins/cache/fearsidhe-plugins/agent-swarm/1.0.0/` is build output. Never edit cache directly. Sync goes dev → cache only; never bidirectional.
- **In practice on this machine:** there's also a separate dev tree at `~/projects/agent-swarm/` (this repo's working clone). When working from the dev tree, mirror changes to `~/.claude/plugins/agent-swarm/` first, then run `bin/sync-to-cache` from there. (Origin of the divergence: project was originally developed on a different machine; the dev-tree convention is the user's, not what `sync-to-cache` was written to assume.)
- If cache and `~/.claude/plugins/agent-swarm/` diverge, that's a bug (someone edited cache directly). Treat as a one-time backport (cache → dev), commit, then re-establish dev as canonical.

## Known infra bugs (tracked in `<vault>/10-projects/agent-swarm/open-recommendations.md` under "Pre-existing `bin/` infra bugs")

- **`sync-to-cache` uses GNU-only `realpath -m`.** BSD realpath on macOS doesn't support `-m` and the script fails on first invocation with `realpath: illegal option -- m`. Workaround: replicate `sync_selective` logic manually (`mkdir -p` + `cp -p` per file). Fix: portable shim — try `grealpath`/`realpath -m`, fall back to a Python `realpath` call.
- **`start-daemon --restart` is a no-op flag.** `bin/sync-to-cache` invokes `start-daemon --restart` after syncing config-touching paths, but the script just runs the port-probe early-exit and prints `Daemon is already running`. Workaround: kill the daemon manually (`kill $(lsof -tiTCP:7523 -sTCP:LISTEN)`) then run `bin/start-daemon`. Fix: implement `--restart` properly or remove the flag from `sync-to-cache`.
- **`start-daemon` uses `sys.executable`.** When invoked outside the poetry venv (e.g. from a plain shell), `sys.executable` resolves to homebrew Python 3.14 which lacks PyYAML, and the daemon crashes at `import yaml`. Workaround: spawn from the poetry venv interpreter explicitly. Fix: resolve the poetry venv interpreter at startup (e.g. via `poetry env info -e`) instead of `sys.executable`.

## Quick reference

- `bin/start-daemon` — spawn the daemon if not running. Idempotent (port-probe early-exit). Background detach.
- `bin/mcp-router` — shim Claude Code talks to. Connects to daemon over TCP. Returns "daemon not running" error if it can't connect.
- `bin/sync-to-cache` — dev → cache copy with optional selective-files mode (`bin/sync-to-cache <file> [<file>...]`).
- `bin/mcp-call` — CLI for subagents to call router tools. Always pass `--caller-id=<agent-id>`.
- `bin/audit-tests`, `bin/todo` — utility scripts.

## 2026-08-11 — mutable state moved to ~/.claude/agent-swarm/data/
`datastore.db` and `dashboard.db` now live at `~/.claude/agent-swarm/data/` (override: `AGENT_SWARM_DATA_DIR`), resolved by `lib/paths.py:agent_swarm_data_dir()`. The in-tree `data/` and `dashboard/data/` dirs are dead — dev-tree copies archived at `~/.claude/agent-swarm/archive/`. Rationale: the src/cache dichotomy is structural (runtime executes from the versioned plugin cache), so state inside either tree goes stale or gets orphaned on version bumps. Note: with state external, WHICH tree the daemon runs from no longer affects data; two latent issues found during migration — the `.daemon.lock` flock is per-tree (cannot prevent a dev daemon and a cache daemon racing for port 7523) and `bin/mcp-router` auto-respawns its own tree's daemon on connection loss.
