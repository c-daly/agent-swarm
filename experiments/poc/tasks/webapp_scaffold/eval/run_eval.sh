#!/usr/bin/env bash
# -----------------------------------------------------------------------
# Eval runner for webapp_scaffold
#
# Runs vitest in the task directory and parses the output to emit
# [METRIC] test_pass_rate  for the experiment harness.
#
# Usage:  bash eval/run_eval.sh
# Expects to be run from: experiments/poc/tasks/webapp_scaffold/
# -----------------------------------------------------------------------
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TASK_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
WEBAPP_DIR="$TASK_DIR/webapp"

# ---------- 1. Ensure dependencies are installed ----------
if [ -d "$WEBAPP_DIR" ] && [ ! -d "$WEBAPP_DIR/node_modules" ]; then
  echo "Installing webapp dependencies..."
  (cd "$WEBAPP_DIR" && npm install 2>&1)
fi

# Ensure vitest is reachable from the task dir or webapp dir
if ! (cd "$TASK_DIR" && npx vitest --version >/dev/null 2>&1); then
  echo "Installing vitest and testing-library in webapp..."
  (cd "$WEBAPP_DIR" && npm install --save-dev \
    vitest \
    @testing-library/react \
    @testing-library/jest-dom \
    jsdom \
    @vitejs/plugin-react 2>&1)
fi

# ---------- 2. Run vitest with the eval config ----------
echo "Running vitest..."
VITEST_OUTPUT=$(cd "$TASK_DIR" && npx vitest run \
  --config eval/vitest.config.ts \
  --reporter=verbose 2>&1) || true

echo "$VITEST_OUTPUT"

# ---------- 3. Parse results and emit [METRIC] ----------
# vitest verbose output summary line looks like:
#   Tests  4 passed | 1 failed (5)
#   Tests  4 passed (4)

PASSED=0
FAILED=0

# Try to parse from the summary line
SUMMARY_LINE=$(echo "$VITEST_OUTPUT" | grep -E "Tests\s+" | tail -1 || true)

if [ -n "$SUMMARY_LINE" ]; then
  PASSED=$(echo "$SUMMARY_LINE" | grep -oE '[0-9]+ passed' | grep -oE '[0-9]+' || echo "0")
  FAILED=$(echo "$SUMMARY_LINE" | grep -oE '[0-9]+ failed' | grep -oE '[0-9]+' || echo "0")
fi

# Fallback: count individual test result lines
if [ "$PASSED" -eq 0 ] && [ "$FAILED" -eq 0 ]; then
  PASSED=$(echo "$VITEST_OUTPUT" | grep -cE '^\s*[✓✅]' || echo "0")
  FAILED=$(echo "$VITEST_OUTPUT" | grep -cE '^\s*[×✗❌]' || echo "0")
fi

TOTAL=$((PASSED + FAILED))
if [ "$TOTAL" -gt 0 ]; then
  RATE=$(echo "scale=4; $PASSED / $TOTAL" | bc)
else
  RATE="0.0000"
fi

echo ""
echo "[METRIC] test_pass_rate=${RATE}"
