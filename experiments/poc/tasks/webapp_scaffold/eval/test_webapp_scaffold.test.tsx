/**
 * Eval tests for the webapp scaffold.
 *
 * These tests validate that the React app renders correctly and that the
 * key visualization components exist and handle edge cases (loading, empty data).
 *
 * Run via: npx vitest run --config eval/vitest.eval.config.ts
 * Or via the harness wrapper: eval/run_eval.sh
 */
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";

// ---------- dynamic imports so tests fail gracefully if components missing ----------

async function importApp() {
  return import("../webapp/src/App");
}

async function importYieldCurveChart() {
  return import("../webapp/src/components/YieldCurveChart");
}

// ---------- Test: App renders without error ----------

describe("App component", () => {
  it("renders without crashing", async () => {
    // Mock fetch globally so the App doesn't fail on network calls
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => [],
    });

    const { default: App } = await importApp();
    const { container } = render(<App />);
    expect(container).toBeTruthy();
    expect(container.innerHTML.length).toBeGreaterThan(0);
  });
});

// ---------- Test: YieldCurveChart component exists and renders ----------

describe("YieldCurveChart component", () => {
  it("exists and is a valid React component", async () => {
    const mod = await importYieldCurveChart();
    const YieldCurveChart = mod.default ?? mod.YieldCurveChart;
    expect(YieldCurveChart).toBeDefined();
    expect(typeof YieldCurveChart).toBe("function");
  });

  it("renders with sample data", async () => {
    const mod = await importYieldCurveChart();
    const YieldCurveChart = mod.default ?? mod.YieldCurveChart;

    const sampleData = [
      { maturity: "1mo", yield_pct: 5.3 },
      { maturity: "3mo", yield_pct: 5.25 },
      { maturity: "2yr", yield_pct: 4.6 },
      { maturity: "10yr", yield_pct: 4.2 },
      { maturity: "30yr", yield_pct: 4.4 },
    ];

    const { container } = render(
      <YieldCurveChart data={sampleData} loading={false} />
    );
    expect(container).toBeTruthy();
    expect(container.innerHTML.length).toBeGreaterThan(0);
  });

  it("handles loading state", async () => {
    const mod = await importYieldCurveChart();
    const YieldCurveChart = mod.default ?? mod.YieldCurveChart;

    const { container } = render(
      <YieldCurveChart data={[]} loading={true} />
    );
    expect(container).toBeTruthy();
    // When loading, should show some indicator or at least not crash
    const text = container.textContent ?? "";
    // Accept either a loading indicator or an empty-but-stable render
    expect(container.innerHTML.length).toBeGreaterThan(0);
  });

  it("handles empty data gracefully", async () => {
    const mod = await importYieldCurveChart();
    const YieldCurveChart = mod.default ?? mod.YieldCurveChart;

    const { container } = render(
      <YieldCurveChart data={[]} loading={false} />
    );
    expect(container).toBeTruthy();
    // Should not throw -- an empty chart or "no data" message is fine
  });
});
