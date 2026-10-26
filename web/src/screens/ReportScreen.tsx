import { useEffect, useState } from "preact/hooks";
import { apiFetch } from "../api";
import { EmptyState } from "../components/EmptyState";
import { Header } from "../components/Header";
import { Skeleton } from "../components/Skeleton";
import {
  addDays,
  formatDateCzech,
  formatDateRangeCzech,
  formatDecimal,
  formatDuration,
  formatDurationShort,
  formatNumber,
  formatTime,
  getTodayString,
  isToday,
  recoveryColor,
} from "../helpers";
import { ReportResponse } from "../types";

interface ReportScreenProps {
  end?: string;
  period?: "week" | "month";
  onNavigate?: (newEnd: string | undefined, newPeriod: "week" | "month") => void;
  date?: string;
  onDateChange?: (newDate: string) => void;
}

export function ReportScreen({
  end,
  period: initialPeriod,
  onNavigate,
  date,
  onDateChange,
}: ReportScreenProps) {
  const [period, setPeriod] = useState<"week" | "month">(() => initialPeriod || "week");
  const [data, setData] = useState<ReportResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  useEffect(() => {
    if (initialPeriod && initialPeriod !== period) {
      setPeriod(initialPeriod);
    }
  }, [initialPeriod]);

  // Trendy and Přehled without ?end= show the window ending today
  const currentDate =
    end || (date && date !== getTodayString() ? date : undefined) || getTodayString();
  const isCurrentPeriod = isToday(currentDate) || currentDate >= getTodayString();

  const loadData = async (isRef = false) => {
    if (isRef) setRefreshing(true);
    else setLoading(true);

    const queryEnd =
      end || (date && date !== getTodayString() ? date : undefined)
        ? `&end=${encodeURIComponent(currentDate)}`
        : "";
    const res = await apiFetch<ReportResponse>(
      `/api/report?period=${period}${queryEnd}`
    );
    if (res.data) {
      setData(res.data);
    }
    setLoading(false);
    setRefreshing(false);
  };

  useEffect(() => {
    loadData();
  }, [period, currentDate]);

  const handlePeriodChange = (newPeriod: "week" | "month") => {
    setPeriod(newPeriod);
    if (onNavigate) {
      onNavigate(end, newPeriod);
    }
  };

  const handlePrevPeriod = () => {
    const step = period === "week" ? 7 : 30;
    const newDate = addDays(currentDate, -step);
    if (onNavigate) {
      onNavigate(newDate, period);
    } else if (onDateChange) {
      onDateChange(newDate);
    }
  };

  const handleNextPeriod = () => {
    if (isCurrentPeriod) return;
    const step = period === "week" ? 7 : 30;
    const nextDate = addDays(currentDate, step);
    const todayStr = getTodayString();
    const clampedDate = nextDate >= todayStr ? undefined : nextDate;
    if (onNavigate) {
      onNavigate(clampedDate, period);
    } else if (onDateChange) {
      onDateChange(clampedDate || todayStr);
    }
  };

  const deltaText = (delta: number | null | undefined, unit: string = ""): { text: string; color: string } => {
    if (delta === null || delta === undefined) {
      return { text: "–", color: "#9BA3AF" };
    }
    const sign = delta > 0 ? "+" : delta < 0 ? "−" : "";
    const color = delta > 0 ? "#7DB8FF" : delta < 0 ? "#FFB15C" : "#9BA3AF";
    const absVal = Math.abs(delta);
    const formatted = absVal % 1 === 0 ? absVal.toString() : formatDecimal(absVal, 1);
    return { text: `${sign}${formatted}${unit}`, color };
  };

  const periodTitle = data
    ? `${period === "week" ? "Týden" : "Měsíc"} · ${formatDateRangeCzech(data.start, data.end)}`
    : period === "week"
      ? "Týdenní přehled"
      : "Měsíční přehled";

  const periodSubtitle =
    period === "week" ? "proti předchozímu týdnu" : "proti předchozímu měsíci";

  const maxMuscleSets = Math.max(1, ...(data?.muscles.map((m) => m.sets) || [1]));

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
      <Header
        title={periodTitle}
        backHref="/trendy"
        backLabel="Zpět na Trendy"
        asOf={data?.as_of}
        onRefresh={() => loadData(true)}
        isRefreshing={refreshing}
      />

      {/* Period navigation and toggle */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          gap: "8px",
          flexWrap: "wrap",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: "4px" }}>
          <button
            type="button"
            onClick={handlePrevPeriod}
            aria-label={period === "week" ? "Předchozí týden" : "Předchozí měsíc"}
            style={{
              width: "44px",
              height: "44px",
              minHeight: "44px",
              borderRadius: "12px",
              border: "none",
              background: "#16191E",
              color: "#F2F4F7",
              fontSize: "18px",
              fontWeight: 700,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              cursor: "pointer",
            }}
          >
            ‹
          </button>
          <button
            type="button"
            onClick={handleNextPeriod}
            disabled={isCurrentPeriod}
            aria-label={period === "week" ? "Následující týden" : "Následující měsíc"}
            style={{
              width: "44px",
              height: "44px",
              minHeight: "44px",
              borderRadius: "12px",
              border: "none",
              background: "#16191E",
              color: isCurrentPeriod ? "#5C636D" : "#F2F4F7",
              fontSize: "18px",
              fontWeight: 700,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              cursor: isCurrentPeriod ? "not-allowed" : "pointer",
              opacity: isCurrentPeriod ? 0.4 : 1,
            }}
          >
            ›
          </button>
          <span style={{ fontSize: "12px", color: "#9BA3AF", paddingLeft: "4px" }}>
            {periodSubtitle}
          </span>
        </div>

        <div
          role="group"
          aria-label="Období přehledu"
          style={{
            display: "flex",
            gap: "4px",
            padding: "4px",
            borderRadius: "12px",
            background: "#16191E",
          }}
        >
          <button
            type="button"
            onClick={() => handlePeriodChange("week")}
            aria-pressed={period === "week"}
            style={{
              minHeight: "44px",
              padding: "0 10px",
              border: "none",
              borderRadius: "9px",
              fontFamily: "inherit",
              fontSize: "13px",
              fontWeight: 600,
              background: period === "week" ? "#2C323A" : "transparent",
              color: period === "week" ? "#F2F4F7" : "#9BA3AF",
              cursor: "pointer",
            }}
          >
            Týden
          </button>
          <button
            type="button"
            onClick={() => handlePeriodChange("month")}
            aria-pressed={period === "month"}
            style={{
              minHeight: "44px",
              padding: "0 10px",
              border: "none",
              borderRadius: "9px",
              fontFamily: "inherit",
              fontSize: "13px",
              fontWeight: 600,
              background: period === "month" ? "#2C323A" : "transparent",
              color: period === "month" ? "#F2F4F7" : "#9BA3AF",
              cursor: "pointer",
            }}
          >
            Měsíc
          </button>
        </div>
      </div>

      {loading && !data ? (
        <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
          <Skeleton height={200} />
          <Skeleton height={180} />
          <Skeleton height={160} />
        </div>
      ) : !data ? (
        <EmptyState message="Zatím žádná data pro přehled" />
      ) : (
        <>
          {/* Comparison tiles (6 tiles) */}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: "8px" }}>
            {/* 1. Recovery */}
            {(() => {
              const d = deltaText(data.tiles.recovery.delta, " %");
              return (
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
                    {data.tiles.recovery.val !== null ? `${Math.round(data.tiles.recovery.val)} %` : "–"}
                  </div>
                  <div style={{ fontSize: "12px", fontWeight: 600, color: d.color }}>
                    {data.tiles.recovery.delta !== null ? `${d.text} proti minule` : "–"}
                  </div>
                </div>
              );
            })()}

            {/* 2. Strain */}
            {(() => {
              const d = deltaText(data.tiles.strain.delta);
              return (
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
                    {data.tiles.strain.val !== null ? formatDecimal(data.tiles.strain.val, 1) : "–"}
                  </div>
                  <div style={{ fontSize: "12px", fontWeight: 600, color: d.color }}>{d.text}</div>
                </div>
              );
            })()}

            {/* 3. Sleep */}
            {(() => {
              const d = deltaText(data.tiles.sleep_min.delta, " min");
              return (
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
                    {data.tiles.sleep_min.val !== null
                      ? formatDurationShort(data.tiles.sleep_min.val)
                      : "–"}
                  </div>
                  <div style={{ fontSize: "12px", fontWeight: 600, color: d.color }}>
                    {d.text}
                    {data.tiles.sleep_min.debt_min > 0 && ` · dluh ${data.tiles.sleep_min.debt_min} min`}
                  </div>
                </div>
              );
            })()}

            {/* 4. Sleep consistency */}
            {(() => {
              const d = deltaText(data.tiles.consistency.delta, " %");
              return (
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
                  <div style={{ fontSize: "12px", color: "#9BA3AF" }}>Pravidelnost spánku</div>
                  <div style={{ fontSize: "20px", fontWeight: 700 }}>
                    {data.tiles.consistency.val !== null
                      ? `${Math.round(data.tiles.consistency.val)} %`
                      : "–"}
                  </div>
                  <div style={{ fontSize: "12px", fontWeight: 600, color: d.color }}>{d.text}</div>
                </div>
              );
            })()}

            {/* 5. Intake / Calories */}
            {(() => {
              return (
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
                  <div style={{ fontSize: "12px", color: "#9BA3AF" }}>Ø příjem</div>
                  <div style={{ fontSize: "20px", fontWeight: 700 }}>
                    {data.tiles.kcal.val !== null ? `${formatNumber(data.tiles.kcal.val)} kcal` : "–"}
                  </div>
                  <div style={{ fontSize: "12px", fontWeight: 600, color: "#9BA3AF" }}>
                    bílkoviny {data.tiles.kcal.protein_hit_days} ze {data.tiles.kcal.total_days} dní
                  </div>
                </div>
              );
            })()}

            {/* 6. Weight */}
            {(() => {
              const d = deltaText(data.tiles.weight.delta, " kg");
              return (
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
                  <div style={{ fontSize: "12px", color: "#9BA3AF" }}>Váha (7d Ø)</div>
                  <div style={{ fontSize: "20px", fontWeight: 700 }}>
                    {data.tiles.weight.val !== null ? `${formatDecimal(data.tiles.weight.val, 1)} kg` : "–"}
                  </div>
                  <div style={{ fontSize: "12px", fontWeight: 600, color: d.color }}>{d.text}</div>
                </div>
              );
            })()}
          </div>

          {/* Daily recovery bars */}
          {data.daily_recovery && data.daily_recovery.length > 0 && (
            <div
              style={{
                background: "#16191E",
                borderRadius: "16px",
                padding: "16px",
                display: "flex",
                flexDirection: "column",
                gap: "10px",
              }}
            >
              <div style={{ fontSize: "15px", fontWeight: 700 }}>Recovery po dnech</div>
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: `repeat(${data.daily_recovery.length}, minmax(0, 1fr))`,
                  gap: "8px",
                  alignItems: "end",
                  height: "96px",
                }}
              >
                {data.daily_recovery.map((d, idx) => {
                  const val = d.recovery ?? 0;
                  const h = Math.round((val / 100) * 76);
                  return (
                    <div
                      key={idx}
                      style={{
                        display: "flex",
                        flexDirection: "column",
                        justifyContent: "flex-end",
                        alignItems: "center",
                        gap: "4px",
                        height: "96px",
                      }}
                    >
                      <span style={{ fontSize: "11px", color: "#C9CED6" }}>
                        {d.recovery !== null ? d.recovery : "–"}
                      </span>
                      <div
                        style={{
                          width: "100%",
                          height: `${h}px`,
                          borderRadius: "6px 6px 2px 2px",
                          background: recoveryColor(d.recovery),
                        }}
                      />
                    </div>
                  );
                })}
              </div>

              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: `repeat(${data.daily_recovery.length}, minmax(0, 1fr))`,
                  gap: "8px",
                  fontSize: "11px",
                  color: "#9BA3AF",
                  textAlign: "center",
                }}
              >
                {data.daily_recovery.map((d, idx) => (
                  <span key={idx}>{d.weekday}</span>
                ))}
              </div>

              {/* Best / worst day note */}
              {(data.best_day || data.worst_day) && (
                <div
                  style={{
                    display: "flex",
                    flexDirection: "column",
                    gap: "4px",
                    paddingTop: "8px",
                    borderTop: "1px solid #23272E",
                    fontSize: "13px",
                    color: "#C9CED6",
                  }}
                >
                  {data.best_day && (
                    <div>
                      Nejlepší: {data.best_day.weekday} {data.best_day.recovery} %
                      {data.best_day.sleep_min ? ` po ${formatDuration(data.best_day.sleep_min)} spánku` : ""}
                    </div>
                  )}
                  {data.worst_day && (
                    <div>
                      Nejhorší: {data.worst_day.weekday} {data.worst_day.recovery} %
                      {data.worst_day.sleep_min ? ` po ${formatDuration(data.worst_day.sleep_min)} spánku` : ""}
                    </div>
                  )}
                </div>
              )}
            </div>
          )}

          {/* Hard sets per muscle */}
          {data.muscles && data.muscles.length > 0 && (
            <div
              style={{
                background: "#16191E",
                borderRadius: "16px",
                padding: "16px",
                display: "flex",
                flexDirection: "column",
                gap: "10px",
              }}
            >
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
                <div style={{ fontSize: "15px", fontWeight: 700 }}>Těžké série po svalech</div>
                <div style={{ fontSize: "12px", color: "#9BA3AF" }}>
                  {data.workouts_count} {data.workouts_count === 1 ? "trénink" : data.workouts_count < 5 ? "tréninky" : "tréninků"}
                </div>
              </div>

              {data.muscles.map((m, idx) => {
                const pct = Math.min(100, Math.round((m.sets / maxMuscleSets) * 100));
                return (
                  <div
                    key={idx}
                    style={{
                      display: "grid",
                      gridTemplateColumns: "84px minmax(0, 1fr) 28px",
                      gap: "8px",
                      alignItems: "center",
                      minHeight: "24px",
                    }}
                  >
                    <span style={{ fontSize: "13px" }}>{m.muscle}</span>
                    <div style={{ height: "8px", borderRadius: "4px", background: "#23272E" }}>
                      <div
                        style={{
                          width: `${pct}%`,
                          height: "8px",
                          borderRadius: "4px",
                          background: "#3D9BFF",
                        }}
                      />
                    </div>
                    <span style={{ fontSize: "13px", fontWeight: 600, textAlign: "right" }}>{m.sets}</span>
                  </div>
                );
              })}
            </div>
          )}

          {/* Coach review card */}
          <div
            style={{
              background: "#16191E",
              borderRadius: "16px",
              padding: "16px",
              display: "flex",
              flexDirection: "column",
              gap: "8px",
            }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
              <div style={{ fontSize: "15px", fontWeight: 700 }}>Shrnutí od kouče</div>
              {data.coach_review?.ts && (
                <div style={{ fontSize: "12px", color: "#9BA3AF" }}>
                  {formatDateCzech(data.coach_review.ts.slice(0, 10))} {formatTime(data.coach_review.ts)}
                </div>
              )}
            </div>

            {data.coach_review?.body ? (
              <div style={{ fontSize: "14px", lineHeight: 1.5, color: "#D5D9DF", whiteSpace: "pre-wrap" }}>
                {data.coach_review.body}
              </div>
            ) : (
              <div style={{ fontSize: "14px", lineHeight: 1.5, color: "#9BA3AF", fontStyle: "italic" }}>
                Zatím žádné shrnutí od kouče pro toto období. Kouč píše týdenní review v Claude.
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}
