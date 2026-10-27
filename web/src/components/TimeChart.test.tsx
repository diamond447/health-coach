// @vitest-environment happy-dom
import { render } from "preact";
import { describe, expect, it } from "vitest";
import { TimeChart } from "./TimeChart";

function xLabels(count: number): { text: string; anchor: string | null }[] {
  const points = Array.from({ length: count }, (_, i) => ({
    date: `2026-10-${String(i + 1).padStart(2, "0")}`,
    values: [50 + i],
  }));
  const root = document.createElement("div");
  render(
    <TimeChart points={points} series={[{ label: "HRV", color: "#fff", unit: "ms" }]} xAxis yAxis />,
    root,
  );
  return Array.from(root.querySelectorAll("text"))
    .filter((t) => t.textContent?.includes("10."))
    .map((t) => ({ text: t.textContent ?? "", anchor: t.getAttribute("text-anchor") }));
}

describe("TimeChart x axis", () => {
  it("aligns the outer date labels inward so they are not clipped", () => {
    expect(xLabels(30)).toEqual([
      { text: "1. 10.", anchor: "start" },
      { text: "10. 10.", anchor: "middle" },
      { text: "20. 10.", anchor: "middle" },
      { text: "30. 10.", anchor: "end" },
    ]);
  });

  it("centres a single label", () => {
    expect(xLabels(1)).toEqual([{ text: "1. 10.", anchor: "middle" }]);
  });
});
