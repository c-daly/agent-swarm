---
name: verify
description: Run code quality checks (ruff, black, mypy, pytest)
user_invocable: true
---

## Usage
```
/verify              # Run all checks
/verify --fix        # Auto-fix where possible
/verify lint|format|types|tests   # Run specific check
```

## Tools
| Tool | Purpose | Auto-fix |
|------|---------|----------|
| ruff | Lint + imports | Yes (`--fix`) |
| black | Formatting | Yes |
| mypy | Type checking | No |
| pytest | Tests | No |

## CLI
```bash
python3 ~/.claude/plugins/agent-swarm/scripts/verify.py [args]
```

Output: `[VERIFY] tests: X | types: X | lint: X | format: X`
Verify flag resets on any file edit. Run before committing.
