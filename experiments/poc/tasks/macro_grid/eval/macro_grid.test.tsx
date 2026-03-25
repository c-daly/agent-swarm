/**
 * Eval tests for the MacroGrid component.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import React from "react";

// Mock fetch globally — return sample FRED data
beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn(() =>
      Promise.resolve({
        ok: true,
        json: () =>
          Promise.resolve([
            { date: "2024-01-01", value: 100.0 },
            { date: "2024-02-01", value: 101.0 },
            { date: "2024-03-01", value: 102.0 },
          ]),
      })
    )
  );
});

describe("MacroGrid component", () => {
  it("renders without crashing", async () => {
    const mod = await import(
      "../../../../webapp/src/components/MacroGrid"
    );
    const MacroGrid = mod.default ?? mod.MacroGrid;
    expect(() => render(<MacroGrid />)).not.toThrow();
  });

  it("renders with custom indicators prop", async () => {
    const mod = await import(
      "../../../../webapp/src/components/MacroGrid"
    );
    const MacroGrid = mod.default ?? mod.MacroGrid;
    const indicators = [
      { seriesId: "GDP", label: "GDP" },
      { seriesId: "UNRATE", label: "Unemployment" },
    ];
    expect(() =>
      render(<MacroGrid indicators={indicators} />)
    ).not.toThrow();
  });

  it("renders a container with children", async () => {
    const mod = await import(
      "../../../../webapp/src/components/MacroGrid"
    );
    const MacroGrid = mod.default ?? mod.MacroGrid;
    const { container } = render(<MacroGrid />);
    expect(container.children.length).toBeGreaterThan(0);
  });

  it("shows loading state initially", async () => {
    // Use a fetch that never resolves to keep loading state
    vi.stubGlobal(
      "fetch",
      vi.fn(() => new Promise(() => {}))
    );
    const mod = await import(
      "../../../../webapp/src/components/MacroGrid"
    );
    const MacroGrid = mod.default ?? mod.MacroGrid;
    const { container } = render(<MacroGrid />);
    // Component should render something while loading (not be empty)
    expect(container.textContent?.length).toBeGreaterThan(0);
  });

  it("handles fetch error gracefully", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.reject(new Error("Network error")))
    );
    const mod = await import(
      "../../../../webapp/src/components/MacroGrid"
    );
    const MacroGrid = mod.default ?? mod.MacroGrid;
    // Should not throw even when fetch fails
    expect(() => render(<MacroGrid />)).not.toThrow();
  });
});
