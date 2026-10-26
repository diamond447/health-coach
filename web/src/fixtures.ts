// Compile-time contract check: the API samples in fixtures/api/ (written by
// tests/test_web.py) must fit the response types the screens read.
import activity from "./fixtures/api/activity.json";
import calendar from "./fixtures/api/calendar.json";
import day from "./fixtures/api/day.json";
import healthspan from "./fixtures/api/healthspan.json";
import journal from "./fixtures/api/journal.json";
import night from "./fixtures/api/night.json";
import nutrition from "./fixtures/api/nutrition.json";
import recovery from "./fixtures/api/recovery.json";
import report from "./fixtures/api/report.json";
import sleep from "./fixtures/api/sleep.json";
import strain from "./fixtures/api/strain.json";
import trends from "./fixtures/api/trends.json";
import type {
  ActivityResponse,
  CalendarResponse,
  DayResponse,
  HealthspanResponse,
  JournalResponse,
  NightResponse,
  NutritionResponse,
  RecoveryResponse,
  ReportResponse,
  SleepResponse,
  StrainResponse,
  TrendsResponse,
} from "./types";

// JSON imports widen string literals ("green" becomes string), so compare against a
// version of each type with string unions widened the same way.
type Loose<T> = T extends string
  ? string
  : T extends (infer U)[]
    ? Loose<U>[]
    : T extends object
      ? { [K in keyof T]: Loose<T[K]> }
      : T;

export const fixtures = {
  activity: activity satisfies Loose<ActivityResponse>,
  calendar: calendar satisfies Loose<CalendarResponse>,
  day: day satisfies Loose<DayResponse>,
  healthspan: healthspan satisfies Loose<HealthspanResponse>,
  journal: journal satisfies Loose<JournalResponse>,
  night: night satisfies Loose<NightResponse>,
  nutrition: nutrition satisfies Loose<NutritionResponse>,
  recovery: recovery satisfies Loose<RecoveryResponse>,
  report: report satisfies Loose<ReportResponse>,
  sleep: sleep satisfies Loose<SleepResponse>,
  strain: strain satisfies Loose<StrainResponse>,
  trends: trends satisfies Loose<TrendsResponse>,
};
