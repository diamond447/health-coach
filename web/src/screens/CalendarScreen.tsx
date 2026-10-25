import { useEffect, useState } from "preact/hooks";
import { apiFetch } from "../api";
import { EmptyState } from "../components/EmptyState";
import { Header } from "../components/Header";
import { Skeleton } from "../components/Skeleton";
import { formatDecimal, formatDurationShort } from "../helpers";
import { CalendarResponse } from "../types";

interface CalendarScreenProps {
  date: string;
  onDateChange: (date: string) => void;
}

export function CalendarScreen({ date, onDateChange }: CalendarScreenProps) {
  const [metric, setMetric] = useState<"rec" | "sleep" | "strain">("rec");
  const [monthStr, setMonthStr] = useState<string>(() => date.slice(0, 7)); // "YYYY-MM"
  const [data, setData] = useState<CalendarResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const loadData = async (isRef = false) => {
    if (isRef) setRefreshing(true);
    else setLoading(true);

    const res = await apiFetch<CalendarResponse>(`/api/calendar?month=${monthStr}`);
    if (res.data) {
      setData(res.data);
    }
    setLoading(false);
    setRefreshing(false);
  };

  useEffect(() => {
    loadData();
  }, [monthStr]);

  const query = date ? `?date=${encodeURIComponent(date)}` : "";

  const changeMonth = (delta: number) => {
    const [y, m] = monthStr.split("-").map(Number);
    const d = new Date(y, m - 1 + delta, 1);
    const newY = d.getFullYear();
    const newM = (d.getMonth() + 1).toString().padStart(2, "0");
    setMonthStr(`${newY}-${newM}`);
  };

  const recColor = (v: number | null | undefined) => {
    if (v === null || v === undefined) return "#1D2127";
    if (v >= 67) return "#1F7A4A";
    if (v >= 34) return "#8A6D1C";
    return "#8F2E33";
  };

  const sleepColorBg = (h: number | null | undefined) => {
    if (h === null || h === undefined) return "#1D2127";
    if (h >= 7) return "#5B4FC9";
    if (h >= 6) return "#3E3780";
    return "#2A2650";
  };

  const strainColorBg = (s: number | null | undefined) => {
    if (s === null || s === undefined) return "#1D2127";
    if (s >= 14) return "#2F7BE0";
    if (s >= 10) return "#245CA6";
    return "#1A3D6B";
  };

  const legends = {
    rec: [
      { c: "#1F7A4A", t: "zelená ≥ 67" },
      { c: "#8A6D1C", t: "žlutá 34–66" },
      { c: "#8F2E33", t: "červená ≤ 33" },
    ],
    sleep: [
      { c: "#5B4FC9", t: "≥ 7 h" },
      { c: "#3E3780", t: "6–7 h" },
      { c: "#2A2650", t: "< 6 h" },
    ],
    strain: [
      { c: "#2F7BE0", t: "≥ 14" },
      { c: "#245CA6", t: "10–14" },
      { c: "#1A3D6B", t: "< 10" },
    ],
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
      <Header
        title={data?.month_label || "Kalendář"}
        backHref={`/trendy${query}`}
        backLabel="Zpět na Trendy"
        asOf={data?.as_of}
        onRefresh={() => loadData(true)}
        isRefreshing={refreshing}
      />

      {/* Month nav + metric toggles */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: "8px" }}>
        <div style={{ display: "flex", alignItems: "center", gap: "4px" }}>
          <button
            type="button"
            onClick={() => changeMonth(-1)}
            aria-label="Předchozí měsíc"
            style={{
              width: "36px",
              height: "36px",
              borderRadius: "18px",
              border: "none",
              background: "#16191E",
              color: "#F2F4F7",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              cursor: "pointer",
            }}
          >
            <svg
              width="16"
              height="16"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="M15 18l-6-6 6-6" />
            </svg>
          </button>
          <button
            type="button"
            onClick={() => changeMonth(1)}
            aria-label="Další měsíc"
            style={{
              width: "36px",
              height: "36px",
              borderRadius: "18px",
              border: "none",
              background: "#16191E",
              color: "#F2F4F7",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              cursor: "pointer",
            }}
          >
            <svg
              width="16"
              height="16"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="M9 18l6-6-6-6" />
            </svg>
          </button>
        </div>

        <div
          role="group"
          aria-label="Metrika"
          style={{
            display: "flex",
            gap: "4px",
            padding: "4px",
            borderRadius: "12px",
            background: "#16191E",
          }}
        >
          {(
            [
              ["rec", "Recovery"],
              ["sleep", "Spánek"],
              ["strain", "Strain"],
            ] as const
          ).map(([mKey, label]) => {
            const isSelected = metric === mKey;
            return (
              <button
                key={mKey}
                type="button"
                onClick={() => setMetric(mKey)}
                aria-pressed={isSelected}
                style={{
                  minHeight: "36px",
                  padding: "0 10px",
                  border: "none",
                  borderRadius: "9px",
                  fontFamily: "inherit",
                  fontSize: "13px",
                  fontWeight: 600,
                  background: isSelected ? "#2C323A" : "transparent",
                  color: isSelected ? "#F2F4F7" : "#9BA3AF",
                  cursor: "pointer",
                }}
              >
                {label}
              </button>
            );
          })}
        </div>
      </div>

      {loading && !data ? (
        <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
          <Skeleton height={280} />
          <Skeleton height={140} />
        </div>
      ) : !data ? (
        <EmptyState message="Zatím žádná data pro tento měsíc" />
      ) : (
        <>
          {/* Calendar grid card */}
          <div
            style={{
              background: "#16191E",
              borderRadius: "16px",
              padding: "12px",
              display: "flex",
              flexDirection: "column",
              gap: "8px",
            }}
          >
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(7, minmax(0, 1fr))",
                gap: "6px",
                fontSize: "11px",
                color: "#9BA3AF",
                textAlign: "center",
              }}
            >
              <span>po</span>
              <span>út</span>
              <span>st</span>
              <span>čt</span>
              <span>pá</span>
              <span>so</span>
              <span>ne</span>
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "repeat(7, minmax(0, 1fr))", gap: "6px" }}>
              {data.cells.map((cell, idx) => {
                if (!cell.day) {
                  return <div key={idx} style={{ aspectRatio: "1 / 1" }} />;
                }

                const isCurrentSelected = cell.date === date;
                let bg = "#1D2127";
                let valStr = "";

                if (metric === "rec") {
                  bg = recColor(cell.recovery);
                  valStr = cell.recovery !== null ? `${cell.recovery}` : "";
                } else if (metric === "sleep") {
                  bg = sleepColorBg(cell.sleep_hours);
                  valStr = cell.sleep_hours !== null ? formatDecimal(cell.sleep_hours, 1) : "";
                } else {
                  bg = strainColorBg(cell.strain);
                  valStr = cell.strain !== null ? formatDecimal(cell.strain, 1) : "";
                }

                return (
                  <button
                    key={idx}
                    type="button"
                    onClick={() => cell.date && onDateChange(cell.date)}
                    style={{
                      aspectRatio: "1 / 1",
                      borderRadius: "10px",
                      background: bg,
                      border: isCurrentSelected ? "2px solid #F2F4F7" : "none",
                      display: "flex",
                      flexDirection: "column",
                      alignItems: "center",
                      justifyContent: "center",
                      gap: "1px",
                      padding: 0,
                      cursor: "pointer",
                      fontFamily: "inherit",
                    }}
                  >
                    <span
                      style={{
                        fontSize: "11px",
                        color: valStr ? "#D5D9DF" : "#5C636D",
                      }}
                    >
                      {cell.day}
                    </span>
                    <span style={{ fontSize: "13px", fontWeight: 700, color: "#F2F4F7" }}>
                      {valStr}
                    </span>
                  </button>
                );
              })}
            </div>

            {/* Legend */}
            <div
              style={{
                display: "flex",
                gap: "12px",
                flexWrap: "wrap",
                fontSize: "12px",
                color: "#9BA3AF",
                paddingTop: "4px",
              }}
            >
              {legends[metric].map((leg, idx) => (
                <span key={idx} style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                  <span style={{ width: "10px", height: "10px", borderRadius: "3px", background: leg.c }} />
                  {leg.t}
                </span>
              ))}
            </div>
          </div>

          {/* Month statistics */}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: "8px" }}>
            <div
              style={{
                background: "#16191E",
                borderRadius: "16px",
                padding: "12px",
                display: "flex",
                flexDirection: "column",
                gap: "2px",
              }}
            >
              <div style={{ fontSize: "12px", color: "#9BA3AF" }}>Ø recovery</div>
              <div style={{ fontSize: "20px", fontWeight: 700 }}>
                {data.stats.avg_recovery !== null ? `${Math.round(data.stats.avg_recovery)} %` : "–"}
              </div>
              <div style={{ fontSize: "12px", color: "#9BA3AF" }}>
                {data.stats.green_days} zelených · {data.stats.yellow_days} žlutých · {data.stats.red_days} červených
              </div>
            </div>

            <div
              style={{
                background: "#16191E",
                borderRadius: "16px",
                padding: "12px",
                display: "flex",
                flexDirection: "column",
                gap: "2px",
              }}
            >
              <div style={{ fontSize: "12px", color: "#9BA3AF" }}>Ø spánek</div>
              <div style={{ fontSize: "20px", fontWeight: 700 }}>
                {data.stats.avg_sleep_hours !== null
                  ? formatDurationShort(data.stats.avg_sleep_hours * 60)
                  : "–"}
              </div>
              <div style={{ fontSize: "12px", color: "#9BA3AF" }}>
                dluh na konci měsíce {data.stats.sleep_debt_end_min} min
              </div>
            </div>

            <div
              style={{
                background: "#16191E",
                borderRadius: "16px",
                padding: "12px",
                display: "flex",
                flexDirection: "column",
                gap: "2px",
              }}
            >
              <div style={{ fontSize: "12px", color: "#9BA3AF" }}>Ø strain</div>
              <div style={{ fontSize: "20px", fontWeight: 700 }}>
                {data.stats.avg_strain !== null ? formatDecimal(data.stats.avg_strain, 1) : "–"}
              </div>
              <div style={{ fontSize: "12px", color: "#9BA3AF" }}>
                {data.stats.max_strain !== null
                  ? `nejvyšší ${formatDecimal(data.stats.max_strain, 1)}`
                  : "–"}
              </div>
            </div>

            <div
              style={{
                background: "#16191E",
                borderRadius: "16px",
                padding: "12px",
                display: "flex",
                flexDirection: "column",
                gap: "2px",
              }}
            >
              <div style={{ fontSize: "12px", color: "#9BA3AF" }}>Tréninky</div>
              <div style={{ fontSize: "20px", fontWeight: 700 }}>{data.stats.workouts_total}×</div>
              <div style={{ fontSize: "12px", color: "#9BA3AF" }}>
                {data.stats.workouts_breakdown || "Zatím žádné"}
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
