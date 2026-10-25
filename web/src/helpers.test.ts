import { describe, expect, it } from "vitest";
import {
  addDays,
  calculateBand,
  foodColor,
  formatDateCzech,
  formatDecimal,
  formatDuration,
  formatDurationShort,
  formatFactorEffect,
  formatFactorValue,
  formatNumber,
  formatPace,
  formatTime,
  getTodayString,
  isToday,
  recoveryColor,
  recoveryZoneLabel,
  ringDash,
  seriesPoints,
  sleepColor,
  strainColor,
} from "./helpers";

describe("formatNumber", () => {
  it("formats numbers with Czech thousand separators", () => {
    expect(formatNumber(8432)).toBe("8 432");
    expect(formatNumber(0)).toBe("0");
    expect(formatNumber(100)).toBe("100");
    expect(formatNumber(1000000)).toBe("1 000 000");
  });

  it("handles null/undefined/NaN", () => {
    expect(formatNumber(null)).toBe("–");
    expect(formatNumber(undefined)).toBe("–");
    expect(formatNumber(NaN)).toBe("–");
  });
});

describe("formatDecimal", () => {
  it("formats decimal with comma", () => {
    expect(formatDecimal(11.8, 1)).toBe("11,8");
    expect(formatDecimal(-0.4, 1)).toBe("−0,4");
    expect(formatDecimal(0, 1)).toBe("0,0");
  });

  it("shows sign when requested", () => {
    expect(formatDecimal(0.4, 1, true)).toBe("+0,4");
    expect(formatDecimal(-0.4, 1, true)).toBe("−0,4");
    expect(formatDecimal(0, 1, true)).toBe("0,0");
  });

  it("handles null/undefined/NaN", () => {
    expect(formatDecimal(null)).toBe("–");
    expect(formatDecimal(undefined)).toBe("–");
  });
});

describe("formatDuration", () => {
  it("formats minutes into hours and minutes", () => {
    expect(formatDuration(432)).toBe("7 h 12 min");
    expect(formatDuration(46)).toBe("46 min");
    expect(formatDuration(60)).toBe("1 h 00 min");
    expect(formatDuration(0)).toBe("0 min");
  });

  it("handles short duration formatting", () => {
    expect(formatDurationShort(432)).toBe("7 h 12");
    expect(formatDurationShort(46)).toBe("0 h 46");
  });

  it("handles null/negative", () => {
    expect(formatDuration(null)).toBe("–");
    expect(formatDuration(-10)).toBe("–");
  });
});

describe("formatDateCzech", () => {
  it("formats YYYY-MM-DD into Czech short format", () => {
    expect(formatDateCzech("2026-10-25")).toBe("ne 25. 10.");
    expect(formatDateCzech("2026-10-26")).toBe("po 26. 10.");
  });

  it("handles addDays and isToday", () => {
    expect(addDays("2026-10-25", 1)).toBe("2026-10-26");
    expect(addDays("2026-10-25", -1)).toBe("2026-10-24");
    expect(isToday(getTodayString())).toBe(true);
    expect(isToday("1999-01-01")).toBe(false);
  });
});

describe("formatTime", () => {
  it("extracts HH:MM", () => {
    expect(formatTime("2026-10-25T14:30:00+01:00")).toBe("14:30");
    expect(formatTime("08:15:22")).toBe("08:15");
    expect(formatTime(null)).toBe("–");
  });
});

describe("chart geometry", () => {
  it("calculates ring stroke-dasharray", () => {
    // radius 40: circ = 2 * PI * 40 = 251.327...
    const dash = ringDash(50, 100, 40);
    const [len, circ] = dash.split(" ").map(Number);
    expect(len).toBeCloseTo(125.7, 0);
    expect(circ).toBeCloseTo(251.3, 0);
  });

  it("computes polyline series points", () => {
    const { points } = seriesPoints([10, 20, 30], 100, 50, 10, 30, 0);
    // x values: 0, 50, 100. y values for min/max: 10 -> 50, 20 -> 25, 30 -> 0.
    expect(points).toBe("0.0,50.0 50.0,25.0 100.0,0.0");
  });

  it("calculates band y and height", () => {
    const { y, h } = calculateBand(20, 40, 100, 0, 50, 0);
    // maxVal=50, minVal=0, height=100.
    // y(40) = ((50 - 40) / 50) * 100 = 20
    // y(20) = ((50 - 20) / 50) * 100 = 60
    // h = 60 - 20 = 40
    expect(y).toBe(20);
    expect(h).toBe(40);
  });
});

describe("zone colors", () => {
  it("returns correct recovery color and zone label", () => {
    expect(recoveryColor(75)).toBe("#2BD47D");
    expect(recoveryZoneLabel(75)).toBe("ZELENÁ");
    expect(recoveryColor(50)).toBe("#F5C542");
    expect(recoveryZoneLabel(50)).toBe("ŽLUTÁ");
    expect(recoveryColor(25)).toBe("#FF5A5F");
    expect(recoveryZoneLabel(25)).toBe("ČERVENÁ");
    expect(recoveryColor(null)).toBe("#5C636D");
    expect(recoveryZoneLabel(null)).toBe("");
  });

  it("returns other colors", () => {
    expect(strainColor()).toBe("#3D9BFF");
    expect(foodColor()).toBe("#FFB15C");
    expect(sleepColor(90)).toBe("#9C8CFF");
    expect(sleepColor(70)).toBe("#5D5499");
  });
});

describe("healthspan helpers", () => {
  it("formats pace correctly", () => {
    expect(formatPace(0.8)).toBe("0,8×");
    expect(formatPace(1.0)).toBe("1,0×");
    expect(formatPace(1.25)).toBe("1,3×");
    expect(formatPace(null)).toBe("—");
    expect(formatPace(undefined)).toBe("—");
  });

  it("formats factor effect with color", () => {
    expect(formatFactorEffect(-0.6)).toEqual({ text: "−0,6 r.", color: "#7DB8FF" });
    expect(formatFactorEffect(0.2)).toEqual({ text: "+0,2 r.", color: "#FFB15C" });
    expect(formatFactorEffect(0.0)).toEqual({ text: "0,0 r.", color: "#9BA3AF" });
    expect(formatFactorEffect(null)).toEqual({ text: "—", color: "#9BA3AF" });
  });

  it("formats factor values", () => {
    expect(formatFactorValue("sleep_regularity", 78, "%")).toBe("78 %");
    expect(formatFactorValue("sleep_duration", 7.066, "h")).toBe("7 h 04");
    expect(formatFactorValue("moderate_activity", 210, "min/týden")).toBe("210 min/týden");
    expect(formatFactorValue("steps", 8900, "/den")).toBe("8 900/den");
    expect(formatFactorValue("vo2max", null, "ml/kg/min")).toBe("zatím bez dat");
  });
});
