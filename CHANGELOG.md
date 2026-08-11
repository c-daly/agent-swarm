# Changelog

All notable changes to agent-swarm. Versions are deliberate SemVer — see
`RELEASING.md` in the fearsidhe-plugins marketplace repo. Format loosely follows
keepachangelog.com. The marketplace pin (released version) may lag `master`;
that gap is unreleased testing work.

## [Unreleased]

## [1.1.0] - 2026-08-11
### Added
- Version-independent external state directory (`~/.claude/agent-swarm/data`,
  overridable via `AGENT_SWARM_DATA_DIR`) for `datastore.db` and `dashboard.db`,
  ending the dev-tree/plugin-cache split-brain (C1, PR #155).
- Phase-gate governance for the `pr_comment` (6 phases) and `debug` (9 phases)
  workflows in `permissions.yaml`, so their read-only phases actually enforce
  read-only (C2, PR #156).
- End-to-end `pr_comment` phase-lifecycle enforcement test.
### Fixed
- Briefing gate emitted `permissionDecision: "block"`, which Claude Code ignores;
  now emits `"deny"`, so unbriefed subagent spawns are actually blocked (C2).
- Daemon interpreter resolution now probes for an interpreter that actually has
  the required dependencies before starting.
- Daemon-health probe cache made symlink-safe and endpoint-scoped (PR #155 review).
### Changed
- `bin/sync-to-cache` derives the cache directory from `plugin.json`'s version
  instead of a hardcoded `1.0.0`.

## [1.0.0]
- Initial released version: MCP router with per-phase tool enforcement,
  phase-gated workflows, skills, and the daemon/controller runtime.
