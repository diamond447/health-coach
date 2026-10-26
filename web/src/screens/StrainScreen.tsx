import { useEffect, useState } from "preact/hooks";
import { apiFetch } from "../api";
import { EmptyState } from "../components/EmptyState";
import { Header } from "../components/Header";
import { RingDial } from "../components/RingDial";
import { Skeleton } from "../components/Skeleton";
import { TimeChart } from "../components/TimeChart";
import { formatDateCzech, formatDecimal, formatNumber, formatTime, strainColor } from "../helpers";
import { StrainResponse } from "../types";

interface StrainScreenProps {
  date: string;
  onDateChange: (date: string) => void;
}

export function StrainScreen({ date, onDateChange }: StrainScreenProps) {
  const [data, setData] = useState<StrainResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const loadData = async (isRef = false) => {
    if (isRef) setRefreshing(true);
    else setLoading(true);

    const res = await apiFetch<StrainResponse>(`/api/strain?date=${encodeURIComponent(date)}`);
    if (res.data) {
      setData(res.data);
    }
    setLoading(false);
    setRefreshing(false);
  };

  useEffect(() => {
    loadData();
  }, [date]);

  const dateFormatted = formatDateCzech(date);

  // The chart spaces points evenly, so lay the 5-minute means on a full day of buckets:
  // x then follows the clock (and the workout windows), with gaps where nothing was worn.
  const hrBuckets = Array.from({ length: 288 }, (_, i) => ({
    date: "",
    label: `${Math.floor(i / 12)}:${String((i % 12) * 5).padStart(2, "0")}`,
    values: [null] as (number | null)[],
  }));
  for (const p of data?.hr_points ?? []) {
    const i = Math.floor(p.minute / 5);
    if (i >= 0 && i < hrBuckets.length) hrBuckets[i].values = [p.bpm];
  }

  // Strain category label
  const strainVal = data?.strain ?? 0;
  const strainCategory =
    strainVal >= 18
      ? "VŠECHNO"
      : strainVal >= 14
        ? "TĚŽKÝ"
        : strainVal >= 10
          ? "STŘEDNÍ"
          : "LEHKÝ";

  const z3Min = data?.zones.find((z) => z.key === "Z3")?.min_hr ?? null;
  const maxZoneMin = Math.max(1, ...(data?.zones.map((z) => z.minutes) || [1]));

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
      <Header
        title={`Strain · ${dateFormatted}`}
        date={date}
        onDateChange={onDateChange}
        asOf={data?.as_of}
        onRefresh={() => loadData(true)}
        isRefreshing={refreshing}
      />

      {loading && !data ? (
        <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
          <Skeleton height={150} />
          <Skeleton height={200} />
          <Skeleton height={220} />
        </div>
      ) : data?.strain === null || data?.strain === undefined ? (
        <EmptyState
          message="Zatím žádná data o strainu"
          submessage="Zátěž pro tento den ještě nebyla zaznamenána."
        />
      ) : (
        <>
          {/* Ring dial & summary */}
          <div style={{ display: "flex", alignItems: "center", gap: "16px" }}>
            <RingDial
              value={data.strain}
              max={21}
              size={132}
              strokeWidth={9}
              displayValue={formatDecimal(data.strain, 1)}
              color={strainColor()}
              ariaLabel={`Strain ${formatDecimal(data.strain, 1)} z 21`}
              sublabel={strainCategory}
              sublabelColor="#7DB8FF"
            />
            <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
              {data.strain_target_low !== null && data.strain_target_high !== null && (
                <div style={{ fontSize: "14px", color: "#C9CED6" }}>
                  Doporučeno {Math.round(data.strain_target_low)}–{Math.round(data.strain_target_high)} podle
                  dnešní recovery {data.recovery !== null ? `${data.recovery} %` : "–"}
                </div>
              )}
              <div style={{ fontSize: "13px", color: "#9BA3AF" }}>
                Kardio zátěž {data.cardio_load !== null ? Math.round(data.cardio_load) : "–"} · svaly{" "}
                {data.muscular_load !== null ? Math.round(data.muscular_load) : "0"} (TRIMP)
              </div>
              <div style={{ fontSize: "13px", color: "#9BA3AF" }}>
                Max tep {data.hr_max} · klidový {data.rest_hr}
              </div>
            </div>
          </div>

          {/* Intraday HR chart */}
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
              <div style={{ fontSize: "15px", fontWeight: 700 }}>Tep během dne</div>
              <div style={{ fontSize: "12px", color: "#9BA3AF" }}>
                max {data.peak_hr !== null ? `${data.peak_hr} bpm` : "–"}
              </div>
            </div>

            <TimeChart
              points={hrBuckets}
              series={[
                {
                  label: "",
                  color: "#FF7A6B",
                  unit: "bpm",
                  kind: "line",
                  maxGap: 3,
                },
              ]}
              target={z3Min !== null ? z3Min : undefined}
              targetColor="#2C323A"
              workoutWindows={data.workout_windows}
              height={130}
              yAxis={true}
              xAxis={false}
              ariaLabel="Tep během dne se zónami a cvičeními"
            />

            {/* Indented by the chart's y-axis gutter (32 of 326 units) */}
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                fontSize: "12px",
                color: "#9BA3AF",
                paddingLeft: "9.8%",
              }}
            >
              <span>0:00</span>
              <span>6:00</span>
              <span>12:00</span>
              <span>18:00</span>
              <span>24:00</span>
            </div>
            <div style={{ fontSize: "12px", color: "#9BA3AF" }}>
              Modře = workouty{z3Min !== null ? ` · čára = začátek zóny 3 (${z3Min} bpm)` : ""}
            </div>
          </div>

          {/* Time in zones */}
          {data.zones && data.zones.length > 0 && (
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
              <div style={{ fontSize: "15px", fontWeight: 700 }}>Čas v zónách</div>
              {data.zones.map((z) => {
                const barPct = Math.min(100, Math.round((z.minutes / maxZoneMin) * 100));
                return (
                  <div
                    key={z.key}
                    style={{
                      display: "grid",
                      gridTemplateColumns: "92px minmax(0, 1fr) 52px",
                      gap: "8px",
                      alignItems: "center",
                      minHeight: "28px",
                    }}
                  >
                    <div style={{ display: "flex", flexDirection: "column" }}>
                      <span style={{ fontSize: "13px", fontWeight: 600 }}>{z.name}</span>
                      <span style={{ fontSize: "11px", color: "#9BA3AF" }}>
                        {z.min_hr}–{z.max_hr} bpm
                      </span>
                    </div>
                    <div style={{ height: "10px", borderRadius: "5px", background: "#23272E" }}>
                      <div
                        style={{
                          width: `${barPct}%`,
                          height: "10px",
                          borderRadius: "5px",
                          background: z.color,
                        }}
                      />
                    </div>
                    <div style={{ fontSize: "13px", fontWeight: 600, textAlign: "right" }}>
                      {z.minutes} min
                    </div>
                  </div>
                );
              })}
            </div>
          )}

          {/* Activities */}
          {data.activities && data.activities.length > 0 && (
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
              <div style={{ fontSize: "15px", fontWeight: 700, paddingBottom: "4px" }}>Aktivity</div>
              {data.activities.map((act, idx) => {
                const startTime = act.start_time ? formatTime(act.start_time) : "";
                const endTime = act.end_time ? formatTime(act.end_time) : "";
                const timeRange = startTime && endTime ? `${startTime}–${endTime}` : "";
                const isStrength = act.type === "strength";

                return (
                  <div
                    key={idx}
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: "12px",
                      padding: "12px",
                      borderRadius: "12px",
                      background: "#1D2127",
                      minHeight: "44px",
                    }}
                  >
                    <div
                      style={{
                        width: "36px",
                        height: "36px",
                        borderRadius: "10px",
                        background: "#1F3550",
                        color: "#7DB8FF",
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                        flexShrink: 0,
                      }}
                    >
                      {isStrength ? (
                        <svg
                          width="20"
                          height="20"
                          viewBox="0 0 24 24"
                          fill="none"
                          stroke="currentColor"
                          strokeWidth="2"
                          strokeLinecap="round"
                          strokeLinejoin="round"
                          aria-hidden="true"
                        >
                          <path d="M6.5 6.5v11M17.5 6.5v11M3 9v6M21 9v6M6.5 12h11" />
                        </svg>
                      ) : (
                        <svg
                          width="20"
                          height="20"
                          viewBox="0 0 24 24"
                          fill="none"
                          stroke="currentColor"
                          strokeWidth="2"
                          strokeLinecap="round"
                          strokeLinejoin="round"
                          aria-hidden="true"
                        >
                          <circle cx="13" cy="4" r="2" />
                          <path d="M10 22l2-7 3 3v4M7 13l3-5 4 1 3 3" />
                        </svg>
                      )}
                    </div>
                    <div style={{ display: "flex", flexDirection: "column", gap: "2px", flexGrow: 1 }}>
                      <div style={{ fontSize: "14px", fontWeight: 600 }}>{act.name}</div>
                      <div style={{ fontSize: "12px", color: "#9BA3AF" }}>
                        {timeRange}
                        {act.avg_hr ? ` · Ø ${Math.round(act.avg_hr)}` : ""}
                        {act.max_hr ? ` / max ${Math.round(act.max_hr)} bpm` : ""}
                      </div>
                      {isStrength && act.hard_sets ? (
                        <div style={{ fontSize: "12px", color: "#9BA3AF" }}>
                          {act.hard_sets} těžkých sérií
                          {act.volume_kg ? ` · ${formatNumber(act.volume_kg)} kg` : ""}
                          {act.mean_rpe ? ` · Ø RPE ${formatDecimal(act.mean_rpe, 0)}` : ""}
                        </div>
                      ) : act.distance_km ? (
                        <div style={{ fontSize: "12px", color: "#9BA3AF" }}>
                          {formatDecimal(act.distance_km, 1)} km
                        </div>
                      ) : null}
                    </div>
                    {act.strain !== null && act.strain !== undefined && (
                      <div style={{ fontSize: "15px", fontWeight: 700, color: "#7DB8FF" }}>
                        +{formatDecimal(act.strain, 1)}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}

          {/* Last 30 days strain */}
          {data.week_strains && data.week_strains.length > 0 && (
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
                <div style={{ fontSize: "15px", fontWeight: 700 }}>Posledních 30 dní</div>
                <div style={{ fontSize: "12px", color: "#9BA3AF" }}>
                  Ø {data.avg_week_strain !== null ? formatDecimal(data.avg_week_strain, 1) : "–"}
                </div>
              </div>

              <TimeChart
                points={data.week_strains.map((d) => ({
                  date: d.date,
                  values: [d.strain],
                }))}
                series={[
                  {
                    label: "Strain",
                    color: "#3D9BFF",
                    unit: "",
                    format: (v) => formatDecimal(v, 1),
                    kind: "bar",
                  },
                ]}
                height={110}
                yAxis={true}
                xAxis={true}
                ariaLabel="Graf strainu za 30 dní"
              />
            </div>
          )}
        </>
      )}
    </div>
  );
}
