/**
 * Pure helper functions for formatting, chart geometry, and zone colors.
 */

const CZECH_DAY_NAMES = ["po", "út", "st", "čt", "pá", "so", "ne"];

/**
 * Format integer with Czech thousands separator (space), e.g. 8432 -> "8 432".
 */
export function formatNumber(val: number | null | undefined): string {
  if (val === null || val === undefined || isNaN(val)) return "–";
  return Math.round(val)
    .toString()
    .replace(/\B(?=(\d{3})+(?!\d))/g, " ");
}

/**
 * Format decimal with Czech comma, e.g. 11.8 -> "11,8".
 * Optionally show sign prefix like "+0,4" or "−0,4".
 */
export function formatDecimal(
  val: number | null | undefined,
  decimals: number = 1,
  showSign: boolean = false
): string {
  if (val === null || val === undefined || isNaN(val)) return "–";
  const absFormatted = Math.abs(val).toFixed(decimals).replace(".", ",");
  if (showSign) {
    if (val > 0) return `+${absFormatted}`;
    if (val < 0) return `−${absFormatted}`;
    return absFormatted;
  }
  return val < 0 ? `−${absFormatted}` : absFormatted;
}

/**
 * Format minutes into Czech duration string, e.g. 432 -> "7 h 12 min", 46 -> "46 min".
 */
export function formatDuration(minutes: number | null | undefined): string {
  if (minutes === null || minutes === undefined || isNaN(minutes) || minutes < 0) return "–";
  const h = Math.floor(minutes / 60);
  const m = Math.round(minutes % 60);
  if (h > 0) {
    return `${h} h ${m.toString().padStart(2, "0")} min`;
  }
  return `${m} min`;
}

/**
 * Format minutes into short duration, e.g. 432 -> "7 h 12".
 */
export function formatDurationShort(minutes: number | null | undefined): string {
  if (minutes === null || minutes === undefined || isNaN(minutes) || minutes < 0) return "–";
  const h = Math.floor(minutes / 60);
  const m = Math.round(minutes % 60);
  return `${h} h ${m.toString().padStart(2, "0")}`;
}

export function getTodayString(): string {
  const now = new Date();
  const y = now.getFullYear();
  const m = (now.getMonth() + 1).toString().padStart(2, "0");
  const d = now.getDate().toString().padStart(2, "0");
  return `${y}-${m}-${d}`;
}

export function isToday(dateStr: string): boolean {
  return dateStr === getTodayString();
}

export function addDays(dateStr: string, days: number): string {
  const parts = dateStr.split("-");
  if (parts.length !== 3) return dateStr;
  const d = new Date(parseInt(parts[0], 10), parseInt(parts[1], 10) - 1, parseInt(parts[2], 10));
  d.setDate(d.getDate() + days);
  const y = d.getFullYear();
  const m = (d.getMonth() + 1).toString().padStart(2, "0");
  const day = d.getDate().toString().padStart(2, "0");
  return `${y}-${m}-${day}`;
}

/**
 * Format date string "YYYY-MM-DD" to Czech format, e.g. "ne 25. 10.".
 */
export function formatDateCzech(dateStr: string): string {
  if (!dateStr) return "";
  const parts = dateStr.split("-");
  if (parts.length !== 3) return dateStr;
  const d = new Date(parseInt(parts[0], 10), parseInt(parts[1], 10) - 1, parseInt(parts[2], 10));
  const weekday = CZECH_DAY_NAMES[(d.getDay() + 6) % 7];
  return `${weekday} ${d.getDate()}. ${d.getMonth() + 1}.`;
}

/**
 * Extract HH:MM from ISO string or HH:MM string.
 */
export function formatTime(isoOrTime: string | null | undefined): string {
  if (!isoOrTime) return "–";
  if (isoOrTime.includes("T")) {
    const d = new Date(isoOrTime);
    if (!isNaN(d.getTime())) {
      return `${d.getHours().toString().padStart(2, "0")}:${d.getMinutes().toString().padStart(2, "0")}`;
    }
  }
  if (isoOrTime.length >= 5 && isoOrTime.includes(":")) {
    return isoOrTime.slice(0, 5);
  }
  return isoOrTime;
}

/**
 * Compute ring stroke-dasharray given value, max, and radius.
 */
export function ringDash(value: number, max: number, radius: number): string {
  const circ = 2 * Math.PI * radius;
  const clamped = Math.max(0, Math.min(max, value));
  const dash = (clamped / max) * circ;
  return `${dash.toFixed(1)} ${circ.toFixed(1)}`;
}

/**
 * Compute SVG polyline points string from array of values.
 */
export function seriesPoints(
  values: (number | null)[],
  width: number,
  height: number,
  minVal: number,
  maxVal: number,
  pad: number = 8
): { points: string; lastX: number; lastY: number } {
  if (!values.length) {
    return { points: "", lastX: 0, lastY: 0 };
  }
  const range = maxVal - minVal || 1;
  const step = values.length > 1 ? width / (values.length - 1) : 0;
  const pts: string[] = [];
  let lastX = 0;
  let lastY = height / 2;

  values.forEach((v, i) => {
    if (v !== null && !isNaN(v)) {
      const x = i * step;
      const y = pad + ((maxVal - v) / range) * (height - 2 * pad);
      pts.push(`${x.toFixed(1)},${y.toFixed(1)}`);
      lastX = x;
      lastY = y;
    }
  });

  return { points: pts.join(" "), lastX, lastY };
}

/**
 * Compute SVG band y and height from band low and band high.
 */
export function calculateBand(
  bandLo: number,
  bandHi: number,
  height: number,
  minVal: number,
  maxVal: number,
  pad: number = 8
): { y: number; h: number } {
  const range = maxVal - minVal || 1;
  const yOf = (v: number) => pad + ((maxVal - v) / range) * (height - 2 * pad);
  const yHi = yOf(bandHi);
  const yLo = yOf(bandLo);
  return {
    y: Math.max(0, yHi),
    h: Math.max(0, yLo - yHi),
  };
}

/**
 * Recovery zone color (#2BD47D, #F5C542, #FF5A5F).
 */
export function recoveryColor(score: number | null | undefined): string {
  if (score === null || score === undefined || isNaN(score)) return "#5C636D";
  if (score >= 67) return "#2BD47D";
  if (score >= 34) return "#F5C542";
  return "#FF5A5F";
}

/**
 * Recovery zone text in Czech.
 */
export function recoveryZoneLabel(score: number | null | undefined): string {
  if (score === null || score === undefined || isNaN(score)) return "";
  if (score >= 67) return "ZELENÁ";
  if (score >= 34) return "ŽLUTÁ";
  return "ČERVENÁ";
}

/**
 * Strain color (#3D9BFF).
 */
export function strainColor(): string {
  return "#3D9BFF";
}

/**
 * Sleep color (#9C8CFF or darker purple).
 */
export function sleepColor(perf: number | null | undefined): string {
  if (perf === null || perf === undefined || isNaN(perf)) return "#5D5499";
  return perf >= 85 ? "#9C8CFF" : "#5D5499";
}

/**
 * Food / nutrition color (#FFB15C).
 */
export function foodColor(): string {
  return "#FFB15C";
}

/**
 * Format pace of aging multiplier, e.g. 0.82 -> "0,8×".
 */
export function formatPace(pace: number | null | undefined): string {
  if (pace === null || pace === undefined || isNaN(pace)) return "—";
  return `${formatDecimal(pace, 1)}×`;
}

/**
 * Format factor effect in years with Czech label and color.
 * Blue for younger, orange for older, gray for no data.
 */
export function formatFactorEffect(years: number | null | undefined): { text: string; color: string } {
  if (years === null || years === undefined || isNaN(years)) {
    return { text: "—", color: "#9BA3AF" };
  }
  const absFormatted = Math.abs(years).toFixed(1).replace(".", ",");
  if (years < 0) {
    return { text: `−${absFormatted} r.`, color: "#7DB8FF" };
  }
  if (years > 0) {
    return { text: `+${absFormatted} r.`, color: "#FFB15C" };
  }
  return { text: "0,0 r.", color: "#9BA3AF" };
}

/**
 * Format factor value according to its type/unit for display in healthspan screen.
 */
export function formatFactorValue(key: string, val: number | null | undefined, unit: string): string {
  if (val === null || val === undefined || isNaN(val)) return "zatím bez dat";
  switch (key) {
    case "sleep_regularity":
      return `${Math.round(val)} %`;
    case "sleep_duration":
      return formatDurationShort(Math.round(val * 60));
    case "moderate_activity":
    case "vigorous_activity":
      return `${formatNumber(Math.round(val))} ${unit}`;
    case "strength_training":
      return `${formatDecimal(val, 1)} ${unit}`;
    case "steps":
      return `${formatNumber(Math.round(val))}${unit}`;
    case "resting_hr":
      return `${Math.round(val)} ${unit}`;
    case "vo2max":
      return `${formatDecimal(val, 1)} ${unit}`;
    case "body_composition":
      return `${formatDecimal(val, 1)} ${unit}`;
    default:
      return `${formatDecimal(val, 1)} ${unit}`;
  }
}

/**
 * Labels and value formats for the recovery components written by the scores job.
 */
export const RECOVERY_SIGNALS: Record<string, { label: string; format: (v: number) => string }> = {
  hrv: { label: "HRV", format: (v) => `${Math.round(v)} ms` },
  resting_hr: { label: "Klidový tep", format: (v) => `${Math.round(v)} bpm` },
  sleep_performance: { label: "Výkon spánku", format: (v) => `${Math.round(v)} %` },
  breathing_rate: { label: "Dech", format: (v) => `${formatDecimal(v, 1)} /min` },
  skin_temperature: { label: "Teplota kůže", format: (v) => `${formatDecimal(v, 1, true)} °C` },
  spo2: { label: "SpO₂", format: (v) => `${formatDecimal(v, 1)} %` },
};

/**
 * Recovery points of one component: "+9", "−2" or "0", with a colour.
 */
export function formatPoints(points: number): { text: string; color: string } {
  if (points > 0) return { text: `+${points}`, color: "#5FE39E" };
  if (points < 0) return { text: `−${Math.abs(points)}`, color: "#FFB15C" };
  return { text: "0", color: "#9BA3AF" };
}

/**
 * Chart value range [min - pad, max + pad] over the known values; [0, 1] without any.
 */
export function valueRange(values: (number | null)[], pad: number): [number, number] {
  const known = values.filter((v): v is number => v !== null && !isNaN(v));
  if (known.length === 0) return [0, 1];
  return [Math.min(...known) - pad, Math.max(...known) + pad];
}

/**
 * Compute nicely rounded ticks for a chart axis tightly covering [min, max].
 * Tries 2, 3 and 4 intervals with nice steps (1, 2, 2.5, 5 × 10^n) and picks
 * the candidate with <= 4 ticks whose span is the smallest that still contains [min, max].
 * E.g. niceTicks(50, 70) -> [50, 60, 70]
 */
export function niceTicks(min: number, max: number, _count: number = 3): number[] {
  if (isNaN(min) || isNaN(max)) return [0];
  if (min >= max) return [min];

  const range = max - min;
  const niceFractions = [1, 2, 2.5, 5];

  interface Candidate {
    step: number;
    start: number;
    end: number;
    tickCount: number;
    span: number;
    ticks: number[];
  }

  const candidates: Candidate[] = [];

  // Try 2, 3, and 4 intervals
  for (const targetIntervals of [2, 3, 4]) {
    const roughStep = range / targetIntervals;
    const exponent = Math.floor(Math.log10(roughStep));
    for (const exp of [exponent - 1, exponent, exponent + 1]) {
      for (const frac of niceFractions) {
        const step = Number((frac * Math.pow(10, exp)).toPrecision(10));
        if (step <= 0) continue;
        const start = Math.floor(min / step) * step;
        const end = Math.ceil(max / step) * step;
        const numTicks = Math.round((end - start) / step) + 1;
        if (numTicks >= 3 && numTicks <= 4 && start <= min + 1e-9 && end >= max - 1e-9) {
          const decimals = Math.max(0, -Math.floor(Math.log10(step)) + 2);
          const ticks: number[] = [];
          for (let t = start; t <= end + step * 0.5; t += step) {
            const rounded = Number(t.toFixed(decimals));
            ticks.push(rounded === 0 ? 0 : rounded);
          }
          candidates.push({
            step,
            start,
            end,
            tickCount: ticks.length,
            span: end - start,
            ticks,
          });
        }
      }
    }
  }

  // Pick the one with <= 4 ticks whose span is the smallest that still contains [min, max]
  candidates.sort((a, b) => {
    const spanDiff = a.span - b.span;
    if (Math.abs(spanDiff) > 1e-9) return spanDiff;
    if (b.tickCount !== a.tickCount) return b.tickCount - a.tickCount;
    return a.step - b.step;
  });

  if (candidates.length > 0) {
    return candidates[0].ticks;
  }

  // Fallback if no 3-4 tick candidate exists: try 2 ticks
  for (const exp of [
    Math.floor(Math.log10(range)) - 1,
    Math.floor(Math.log10(range)),
    Math.floor(Math.log10(range)) + 1,
  ]) {
    for (const frac of niceFractions) {
      const step = Number((frac * Math.pow(10, exp)).toPrecision(10));
      const start = Math.floor(min / step) * step;
      const end = Math.ceil(max / step) * step;
      if (start <= min + 1e-9 && end >= max - 1e-9) {
        return [start, end];
      }
    }
  }

  return [min, max];
}

/**
 * Pure mapping from data value to SVG y coordinate.
 * Maps val from [minVal, maxVal] to [plotBottom, plotTop].
 */
export function mapValueToY(
  val: number,
  minVal: number,
  maxVal: number,
  plotTop: number,
  plotBottom: number
): number {
  const range = maxVal - minVal;
  if (range === 0) return (plotTop + plotBottom) / 2;
  const ratio = (val - minVal) / range;
  return plotBottom - ratio * (plotBottom - plotTop);
}

/**
 * Pure mapping from point index to SVG x coordinate.
 */
export function pointX(
  index: number,
  totalCount: number,
  plotLeft: number,
  plotRight: number
): number {
  if (totalCount <= 1) return (plotLeft + plotRight) / 2;
  return plotLeft + (index / (totalCount - 1)) * (plotRight - plotLeft);
}

/**
 * Pure helper to snap pointer x coordinate to the nearest point index.
 */
export function findNearestIndex(
  svgX: number,
  totalCount: number,
  plotLeft: number,
  plotRight: number
): number {
  if (totalCount <= 1) return 0;
  const ratio = (svgX - plotLeft) / (plotRight - plotLeft);
  const clamped = Math.max(0, Math.min(1, ratio));
  return Math.round(clamped * (totalCount - 1));
}

/**
 * Format date range from two YYYY-MM-DD strings to Czech format: "1. 10. – 30. 10.".
 */
export function formatDateRangeCzech(startStr: string, endStr: string): string {
  if (!startStr || !endStr) return "";
  const parse = (s: string) => {
    const parts = s.split("-");
    if (parts.length !== 3) return { d: 0, m: 0 };
    return { d: parseInt(parts[2], 10), m: parseInt(parts[1], 10) };
  };
  const start = parse(startStr);
  const end = parse(endStr);
  return `${start.d}. ${start.m}. – ${end.d}. ${end.m}.`;
}
