/// <reference types="vitest" />
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import path from "path";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      // Allow imports to resolve relative to the webapp source
      "@": path.resolve(__dirname, "../webapp/src"),
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    include: ["*.test.tsx", "*.test.ts"],
    root: __dirname,
    // Increase timeout for component tests that do dynamic imports
    testTimeout: 15000,
  },
});
