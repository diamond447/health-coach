// @vitest-environment happy-dom
/**
 * Render every screen with the real API samples from fixtures/api/ (written by
 * tests/test_web.py) and fail on any exception, so a screen cannot silently die on the
 * shape of the data again.
 */
import { ComponentChild, render } from "preact";
import { act } from "preact/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";
import { fixtures } from "./fixtures";
import { ActivityScreen } from "./screens/ActivityScreen";
import { CalendarScreen } from "./screens/CalendarScreen";
import { HealthspanScreen } from "./screens/HealthspanScreen";
import { JournalScreen } from "./screens/JournalScreen";
import { MainScreen } from "./screens/MainScreen";
import { NightScreen } from "./screens/NightScreen";
import { NutritionScreen } from "./screens/NutritionScreen";
import { RecoveryScreen } from "./screens/RecoveryScreen";
import { ReportScreen } from "./screens/ReportScreen";
import { SleepScreen } from "./screens/SleepScreen";
import { StrainScreen } from "./screens/StrainScreen";
import { TrendsScreen } from "./screens/TrendsScreen";

vi.mock("./api", () => ({
  apiFetch: async (path: string) => {
    const name = path.replace(/^\/api\//, "").split("?")[0] as keyof typeof fixtures;
    return { data: fixtures[name], error: null, asOf: null, isOffline: false, sessionExpired: false };
  },
  apiSend: async () => ({
    data: null,
    error: null,
    asOf: null,
    isOffline: false,
    sessionExpired: false,
  }),
}));

const DATE = "2026-10-25";
// SVG attributes whose real names are camelCase.
const SVG_CAMEL_CASE = new Set(["viewBox", "preserveAspectRatio"]);
const noop = () => {};

const screens: [string, ComponentChild, string][] = [
  ["Dnes", <MainScreen date={DATE} onDateChange={noop} />, "Co ovlivnilo recovery"],
  ["Recovery", <RecoveryScreen date={DATE} />, "Z čeho se skóre skládá"],
  ["Spánek", <SleepScreen date={DATE} onDateChange={noop} />, "Fáze spánku"],
  ["Strain", <StrainScreen date={DATE} onDateChange={noop} />, "Čas v zónách"],
  ["Jídlo", <NutritionScreen date={DATE} onDateChange={noop} />, "Ovesná kaše"],
  ["Trendy", <TrendsScreen date={DATE} />, "7denní průměr"],
  ["Kalendář", <CalendarScreen date={DATE} onDateChange={noop} />, "posilování"],
  ["Deník", <JournalScreen date={DATE} />, "Alkohol"],
  ["Přehled", <ReportScreen date={DATE} />, "Hrudník"],
  ["Healthspan", <HealthspanScreen date={DATE} />, "BIOLOGICKÝ VĚK"],
  ["Aktivita", <ActivityScreen date={DATE} />, "Aktivní minuty"],
  ["Noc", <NightScreen date={DATE} />, "SpO₂"],
];

describe("screens render the API fixtures", () => {
  const root = document.createElement("div");
  document.body.appendChild(root);
  afterEach(() => render(null, root));

  it.each(screens)("%s", async (_name, screen, expected) => {
    const errors: unknown[] = [];
    const onError = vi.spyOn(console, "error").mockImplementation((...args) => errors.push(args));
    await act(async () => {
      render(screen, root);
    });
    // Let the screen's fetch resolve and re-render with the data.
    await act(() => new Promise((resolve) => setTimeout(resolve, 0)));
    onError.mockRestore();
    expect(errors).toEqual([]);
    expect(root.textContent).toContain(expected);
    // Preact passes attribute names through as written: strokeWidth would be an
    // unknown attribute and the ring or line would fall back to a 1 px stroke.
    const camelCase = [...root.querySelectorAll("svg, svg *")].flatMap((el) =>
      el.getAttributeNames().filter((name) => /[A-Z]/.test(name) && !SVG_CAMEL_CASE.has(name)),
    );
    expect(camelCase).toEqual([]);
  });
});
