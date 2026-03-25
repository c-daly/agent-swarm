/**
 * Vitest setup file for webapp_scaffold eval.
 * Emits [METRIC] test_pass_rate after all tests complete.
 */
import { afterAll } from "vitest";

let passed = 0;
let failed = 0;

export function recordPass() {
  passed++;
}

export function recordFail() {
  failed++;
}

afterAll(() => {
  const total = passed + failed;
  const rate = total > 0 ? passed / total : 0.0;
  console.log(`\n[METRIC] test_pass_rate=${rate.toFixed(4)}`);
});
