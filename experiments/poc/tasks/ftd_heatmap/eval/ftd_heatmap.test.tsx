/**
 * Eval tests for the FtdHeatmap component.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import React from "react";

// Mock fetch globally
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

const SAMPLE_DATA = [
  { date: "2024-01-02", symbol: "GME", quantity: 150000 },
  { date: "2024-01-03", symbol: "GME", quantity: 200000 },
  { date: "2024-01-02", symbol: "AMC", quantity: 80000 },
  { date: "2024-01-03", symbol: "AMC", quantity: 120000 },
];

describe("FtdHeatmap component", () => {
  it("renders without crashing with no data", async () => {
    const mod = await import(
      "../../../../webapp/src/components/FtdHeatmap"
    );
    const FtdHeatmap = mod.default ?? mod.FtdHeatmap;
    expect(() => render(<FtdHeatmap />)).not.toThrow();
  });

  it("renders without crashing with sample data", async () => {
    const mod = await import(
      "../../../../webapp/src/components/FtdHeatmap"
    );
    const FtdHeatmap = mod.default ?? mod.FtdHeatmap;
    expect(() => render(<FtdHeatmap data={SAMPLE_DATA} />)).not.toThrow();
  });

  it("displays empty state message when data is empty", async () => {
    const mod = await import(
      "../../../../webapp/src/components/FtdHeatmap"
    );
    const FtdHeatmap = mod.default ?? mod.FtdHeatmap;
    render(<FtdHeatmap data={[]} />);
    // Should show some kind of empty state, not a blank screen
    const container = document.querySelector("[data-testid]") ??
      document.body;
    const textContent = container.textContent ?? "";
    // The component should have some text content when empty
    expect(textContent.length).toBeGreaterThan(0);
  });

  it("accepts a symbol prop", async () => {
    const mod = await import(
      "../../../../webapp/src/components/FtdHeatmap"
    );
    const FtdHeatmap = mod.default ?? mod.FtdHeatmap;
    expect(() =>
      render(<FtdHeatmap data={SAMPLE_DATA} symbol="GME" />)
    ).not.toThrow();
  });

  it("renders a container element", async () => {
    const mod = await import(
      "../../../../webapp/src/components/FtdHeatmap"
    );
    const FtdHeatmap = mod.default ?? mod.FtdHeatmap;
    const { container } = render(<FtdHeatmap data={SAMPLE_DATA} />);
    expect(container.children.length).toBeGreaterThan(0);
  });
});
