/**
 * Eval tests for the webapp scaffold.
 *
 * These tests validate that the React app renders correctly and that the
 * key visualization components exist and handle edge cases (loading, empty data).
 *
 * Run via: npx vitest run --config eval/vitest.config.ts
 * Or via the harness wrapper: eval/run_eval.sh
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import React from "react";

// Mock fetch globally for components that fetch on mount
beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn(() =>
      Promise.resolve({
        ok: true,
        json: () => Promise.resolve([]),
      })
    )
  );
});

// ---------- Test: App renders without error ----------

describe("App component", () => {
  it("renders without crashing", async () => {
    const mod = await import("../webapp/src/App");
    const AppComponent = mod.default ?? mod.App;
    expect(() => render(<AppComponent />)).not.toThrow();
  });

  it("renders a root container element", async () => {
    const mod = await import("../webapp/src/App");
    const AppComponent = mod.default ?? mod.App;
    const { container } = render(<AppComponent />);
    expect(container.children.length).toBeGreaterThan(0);
  });
});

// ---------- Test: YieldCurveChart component exists and renders ----------

describe("YieldCurveChart component", () => {
  it("renders with sample data", async () => {
    const mod = await import("../webapp/src/components/YieldCurveChart");
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
    const mod = await import("../webapp/src/components/YieldCurveChart");
    const YieldCurveChart = mod.default ?? mod.YieldCurveChart;

    const { container } = render(
      <YieldCurveChart data={[]} loading={true} />
    );
    expect(container).toBeTruthy();
    // When loading, should show some indicator or at least not crash
    expect(container.innerHTML.length).toBeGreaterThan(0);
  });

  it("handles empty data gracefully", async () => {
    const mod = await import("../webapp/src/components/YieldCurveChart");
    const YieldCurveChart = mod.default ?? mod.YieldCurveChart;

    const { container } = render(
      <YieldCurveChart data={[]} loading={false} />
    );
    expect(container).toBeTruthy();
    // Should not throw -- an empty chart or "no data" message is fine
  });
});

// ---------- Test: SpreadChart handles inversions ----------

describe("SpreadChart component", () => {
  it("renders with sample spread data", async () => {
    const mod = await import("../webapp/src/components/SpreadChart");
    const SpreadChart = mod.default ?? mod.SpreadChart;

    const sampleData = [
      { date: "2024-01-01", spread: 0.5, inverted: false },
      { date: "2024-02-01", spread: -0.1, inverted: true },
      { date: "2024-03-01", spread: 0.3, inverted: false },
    ];

    expect(() =>
      render(<SpreadChart data={sampleData} loading={false} />)
    ).not.toThrow();
  });

  it("handles inverted spread values (negative)", async () => {
    const mod = await import("../webapp/src/components/SpreadChart");
    const SpreadChart = mod.default ?? mod.SpreadChart;

    const invertedData = [
      { date: "2024-01-01", spread: -0.5, inverted: true },
      { date: "2024-02-01", spread: -0.3, inverted: true },
    ];

    expect(() =>
      render(<SpreadChart data={invertedData} loading={false} />)
    ).not.toThrow();
  });
});
