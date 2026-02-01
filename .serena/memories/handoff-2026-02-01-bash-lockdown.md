# Handoff: Bash File I/O Lockdown

## Date: 2026-02-01
## Branch: feature/dashboard (uncommitted)

## Context

During live testing of the summarization pipeline, a spawned subagent was instructed to read a file via `native__read_file` (which goes through summarization → `get_full`). Instead, it used `native__bash` with `python3 -c 'open(...).read()'` to read the file directly, completely bypassing the summarization pipeline.

The root cause: bash is a universal escape hatch. Any file I/O command run inside bash executes server-side in `_native_bash` and only the *result* flows through `handle_call`. If an agent processes file contents inside a bash command, those contents never enter the cache/summarization path.

## What Was Done

### Bash file I/O lockdown in `lib/controller.py`

Added `_check_bash_file_io(command)` — a module-level function called at the top of `Controller._native_bash()`. Returns an error message (with guidance to use the correct native tool) if the command attempts file I/O, else `None`.

**Blocked categories:**

| Category | Commands | Redirect to |
|----------|----------|-------------|
| File readers | cat, head, tail, less, more, bat, tac, nl, strings, xxd, hexdump, od | `native__read_file` |
| File searchers | grep, egrep, fgrep, rg, ag, ack | `native__grep` / `native__glob` |
| File processors | sed, awk | `native__read_file` + `native__edit_file` |
| File writers | tee | `native__write_file` |
| Output redirect | `> file`, `>> file` | `native__write_file` |
| Input redirect | `< file` | `native__read_file` |
| Inline scripts | `python3 -c 'open(...)'` etc. | `native__read_file` / `native__write_file` |
| dd | `dd if=` / `dd of=` | `native__read_file` / `native__write_file` |

**Explicitly allowed:**
- `/dev/*` redirections (`>/dev/null`, `2>/dev/null`, `</dev/stdin`)
- fd duplication (`>&2`, `2>&1`)
- Heredocs (`<<EOF`)
- `dd` targeting `/dev/*`
- All non-file-I/O commands (echo, ls, pwd, git, npm, pip, mkdir, rm, mv, cp, chmod, etc.)

Detection works by splitting on shell operators (`;`, `|`, `&`, `$(`, backtick, `(`) and checking the first word of each segment, plus regex checks for redirections and inline script patterns. Handles `sudo`/`env` prefixes and full-path commands (`/usr/bin/cat`).

### Tests in `tests/test_mcp_native.py`

Added `TestBashFileIOLockdown` class — 68 parametrized tests covering:
- All blocked command categories
- Commands after shell operators (`&&`, `;`, `||`, `$(...)`, backticks)
- `sudo`/`env` prefix bypass attempts
- Full-path command bypass attempts
- Safe commands that must remain allowed
- `/dev/*` redirections, fd duplication, heredocs
- Integration tests through `Controller._native_bash()`

## Known Gaps (intentionally deferred)

These are not yet blocked to avoid premature over-restriction:
- `sort file.txt`, `wc file.txt`, `diff file1 file2`, `comm`, `join`, `paste`, `cut` — read files but less common bypass vectors
- `python3 script.py` where `script.py` reads files internally — can't detect without analyzing the script
- `curl file:///path` — local file read via curl
- `base64 file.txt` — reads and encodes file contents
- `cp file.txt /dev/stdout` — copies file to stdout

Strategy: observe what agents actually try and add blocks as needed.

## Files Modified
- `lib/controller.py` — `_check_bash_file_io()` function + blocklist constants, call in `_native_bash`
- `tests/test_mcp_native.py` — `TestBashFileIOLockdown` class (68 tests)

## Test Results
- 437 passed, 1 pre-existing failure (`test_e2e_event_system.py` — socket test, unrelated)
- All 68 new lockdown tests pass
- All 59 existing `test_mcp_native.py` tests still pass

## NOT YET DONE
- **Daemon restart required** — the running daemon has the old controller.py in memory
- **Not committed** — changes are local only
- **PR #66 review** — these changes are on the same branch but not yet pushed

## Prior Handoff
See `handoff-2026-02-01-dashboard-fixes.md` for the dashboard import pipeline, HTML fixes, and get_full test work done earlier in this session.
