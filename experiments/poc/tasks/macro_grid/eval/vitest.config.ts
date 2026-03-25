import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    globals: true,
    reporters: [
      "default",
      {
        onFinished(files) {
          let passed = 0;
          let failed = 0;
          for (const file of files ?? []) {
            for (const task of file.tasks) {
              if (task.result?.state === "pass") passed++;
              else if (task.result?.state === "fail") failed++;
            }
          }
          const total = passed + failed;
          const rate = total > 0 ? passed / total : 0.0;
          console.log(`\n[METRIC] test_pass_rate=${rate.toFixed(4)}`);
        },
      },
    ],
  },
});
