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
