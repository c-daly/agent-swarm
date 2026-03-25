/**
 * Eval tests for the GlossaryTooltip component.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import React from "react";

const MOCK_GLOSSARY = {
  yield_curve: {
    term: "Yield Curve",
    description: "A line plotting interest rates of bonds with equal credit quality but differing maturity dates.",
    interpretation: "A normal upward-sloping curve suggests economic growth; an inverted curve may signal recession.",
    caveats: "The yield curve is one of many indicators and should not be used in isolation.",
  },
  spread: {
    term: "Spread",
    description: "The difference between two yields.",
    interpretation: "A narrowing spread may indicate economic uncertainty.",
    caveats: "Spreads vary based on which maturities are compared.",
  },
};

beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn(() =>
      Promise.resolve({
        ok: true,
        json: () => Promise.resolve(MOCK_GLOSSARY),
      })
    )
  );
});

describe("GlossaryTooltip component", () => {
  it("renders without crashing", async () => {
    const mod = await import(
      "../../../../webapp/src/components/GlossaryTooltip"
    );
    const GlossaryTooltip = mod.default ?? mod.GlossaryTooltip;
    expect(() =>
      render(
        <GlossaryTooltip term="yield_curve">
          <span>Yield Curve</span>
        </GlossaryTooltip>
      )
    ).not.toThrow();
  });

  it("renders children text", async () => {
    const mod = await import(
      "../../../../webapp/src/components/GlossaryTooltip"
    );
    const GlossaryTooltip = mod.default ?? mod.GlossaryTooltip;
    render(
      <GlossaryTooltip term="yield_curve">
        <span>Yield Curve</span>
      </GlossaryTooltip>
    );
    expect(screen.getByText("Yield Curve")).toBeDefined();
  });

  it("accepts term prop as string", async () => {
    const mod = await import(
      "../../../../webapp/src/components/GlossaryTooltip"
    );
    const GlossaryTooltip = mod.default ?? mod.GlossaryTooltip;
    expect(() =>
      render(
        <GlossaryTooltip term="spread">
          <span>Spread</span>
        </GlossaryTooltip>
      )
    ).not.toThrow();
  });

  it("handles unknown term gracefully (does not crash)", async () => {
    const mod = await import(
      "../../../../webapp/src/components/GlossaryTooltip"
    );
    const GlossaryTooltip = mod.default ?? mod.GlossaryTooltip;
    expect(() =>
      render(
        <GlossaryTooltip term="unknown_term_xyz">
          <span>Unknown</span>
        </GlossaryTooltip>
      )
    ).not.toThrow();
    expect(screen.getByText("Unknown")).toBeDefined();
  });

  it("renders a wrapper element around children", async () => {
    const mod = await import(
      "../../../../webapp/src/components/GlossaryTooltip"
    );
    const GlossaryTooltip = mod.default ?? mod.GlossaryTooltip;
    const { container } = render(
      <GlossaryTooltip term="yield_curve">
        <span data-testid="inner">Yield Curve</span>
      </GlossaryTooltip>
    );
    expect(container.children.length).toBeGreaterThan(0);
    expect(screen.getByTestId("inner")).toBeDefined();
  });

  it("caches glossary data — only fetches once for multiple instances", async () => {
    const mod = await import(
      "../../../../webapp/src/components/GlossaryTooltip"
    );
    const GlossaryTooltip = mod.default ?? mod.GlossaryTooltip;

    render(
      <div>
        <GlossaryTooltip term="yield_curve">
          <span>Yield Curve</span>
        </GlossaryTooltip>
        <GlossaryTooltip term="spread">
          <span>Spread</span>
        </GlossaryTooltip>
      </div>
    );

    // Wait for any fetches to complete
    await waitFor(() => {
      // fetch should have been called at most once (due to caching)
      const fetchCalls = (fetch as ReturnType<typeof vi.fn>).mock.calls;
      expect(fetchCalls.length).toBeLessThanOrEqual(1);
    });
  });
});
