import "@testing-library/jest-dom/vitest";
import { afterEach, vi } from "vitest";
import { cleanup } from "@testing-library/react";

afterEach(() => cleanup());

// jsdom lacks these browser APIs
class RO {
  observe() {}
  unobserve() {}
  disconnect() {}
}
(globalThis as unknown as { ResizeObserver: typeof RO }).ResizeObserver = RO;

// Charts render to canvas (unsupported in jsdom); tests assert on data, not pixels.
vi.mock("../components/charts/EChart", async () => {
  const React = await import("react");
  return {
    EChart: ({ ariaLabel }: { ariaLabel: string }) =>
      React.createElement("div", { role: "img", "aria-label": ariaLabel, "data-testid": "chart" }),
  };
});
