import { useEffect, useState } from "preact/hooks";
import { apiFetch } from "../api";
import { EmptyState } from "../components/EmptyState";
import { Header } from "../components/Header";
import { RingDial } from "../components/RingDial";
import { Skeleton } from "../components/Skeleton";
import {
  formatDecimal,
  formatNumber,
  formatPoints,
  formatTime,
  RECOVERY_SIGNALS,
  recoveryColor,
  sleepColor,
  strainColor,
} from "../helpers";
import { DayResponse } from "../types";

interface MainScreenProps {
  date: string;
  onDateChange: (date: string) => void;
}

export function MainScreen({ date, onDateChange }: MainScreenProps) {
  const [data, setData] = useState<DayResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const loadData = async (isRef = false) => {
    if (isRef) setRefreshing(true);
    else setLoading(true);

    const res = await apiFetch<DayResponse>(`/api/day?date=${encodeURIComponent(date)}`);
    if (res.data) {
      setData(res.data);
    }
    setLoading(false);
    setRefreshing(false);
  };

  useEffect(() => {
    loadData();
  }, [date]);

  const query = date ? `?date=${encodeURIComponent(date)}` : "";

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
      <Header
        date={date}
        onDateChange={onDateChange}
        asOf={data?.as_of}
        onRefresh={() => loadData(true)}
        isRefreshing={refreshing}
      />

      {loading && !data ? (
        <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
          <Skeleton height={140} />
          <Skeleton height={110} />
          <Skeleton height={240} />
          <Skeleton height={160} />
        </div>
      ) : (
        <>
          {/* 3 Rings */}
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(3, minmax(0, 1fr))",
              gap: "8px",
              padding: "8px 0",
            }}
          >
            <a
              href={`/spanek${query}`}
              style={{
                textDecoration: "none",
                color: "#F2F4F7",
                display: "flex",
                flexDirection: "column",
                alignItems: "center",
                gap: "8px",
              }}
            >
              <RingDial
                value={data?.scores.sleep_performance}
                max={100}
                unit="%"
                color={sleepColor(data?.scores.sleep_performance)}
                ariaLabel={`Spánek ${data?.scores.sleep_performance ?? 0} procent`}
                sublabel="SPÁNEK"
                sublabelColor="#B8B0FF"
              />
            </a>

            <a
              href={`/recovery${query}`}
              style={{
                textDecoration: "none",
                color: "#F2F4F7",
                display: "flex",
                flexDirection: "column",
                alignItems: "center",
                gap: "8px",
              }}
            >
              <RingDial
                value={data?.scores.recovery}
                max={100}
                unit="%"
                color={recoveryColor(data?.scores.recovery)}
                ariaLabel={`Recovery ${data?.scores.recovery ?? 0} procent`}
                sublabel="RECOVERY"
                sublabelColor={recoveryColor(data?.scores.recovery)}
              />
            </a>

            <a
              href={`/strain${query}`}
              style={{
                textDecoration: "none",
                color: "#F2F4F7",
                display: "flex",
                flexDirection: "column",
                alignItems: "center",
                gap: "8px",
              }}
            >
              <RingDial
                value={data?.scores.strain}
                max={21}
                displayValue={
                  data?.scores.strain !== null && data?.scores.strain !== undefined
                    ? formatDecimal(data?.scores.strain, 1)
                    : "–"
                }
                color={strainColor()}
                ariaLabel={`Strain ${data?.scores.strain ?? 0} z 21`}
                sublabel="STRAIN"
                sublabelColor="#7DB8FF"
              />
            </a>
          </div>

          {/* Recommended strain card */}
          {data?.scores.strain_target_low !== null &&
          data?.scores.strain_target_low !== undefined &&
          data?.scores.strain_target_high !== null &&
          data?.scores.strain_target_high !== undefined ? (
            <div
              style={{
                background: "#16191E",
                borderRadius: "16px",
                padding: "16px",
                display: "flex",
                flexDirection: "column",
                gap: "12px",
              }}
            >
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
                <div style={{ fontSize: "15px", fontWeight: 700 }}>Doporučený strain na dnes</div>
                <div style={{ fontSize: "15px", fontWeight: 700, color: "#7DB8FF" }}>
                  {Math.round(data.scores.strain_target_low)}–{Math.round(data.scores.strain_target_high)}
                </div>
              </div>

              {(() => {
                const cur = data.scores.strain ?? 0;
                const low = data.scores.strain_target_low;
                const high = data.scores.strain_target_high;
                const pctCur = Math.min(100, Math.max(0, (cur / 21) * 100));
                const pctTargetLeft = Math.min(100, Math.max(0, (low / 21) * 100));
                const pctTargetWidth = Math.min(100 - pctTargetLeft, Math.max(0, ((high - low) / 21) * 100));
                const remLow = Math.max(0, low - cur);
                const remHigh = Math.max(0, high - cur);
                const remText =
                  cur >= high
                    ? "Cíl splněn"
                    : `Zatím ${formatDecimal(cur, 1)} · zbývá ~${formatDecimal(remLow, 1)}–${formatDecimal(remHigh, 1)}`;

                return (
                  <>
                    <div
                      style={{
                        position: "relative",
                        height: "12px",
                        borderRadius: "6px",
                        background: "#23272E",
                      }}
                    >
                      {/* Target window */}
                      <div
                        style={{
                          position: "absolute",
                          left: `${pctTargetLeft.toFixed(1)}%`,
                          width: `${pctTargetWidth.toFixed(1)}%`,
                          top: 0,
                          bottom: 0,
                          background: "#1F4C80",
                          borderRadius: "6px",
                        }}
                      />
                      {/* Current progress */}
                      <div
                        style={{
                          position: "absolute",
                          left: 0,
                          width: `${pctCur.toFixed(1)}%`,
                          top: "3px",
                          height: "6px",
                          background: "#3D9BFF",
                          borderRadius: "3px",
                        }}
                      />
                      {/* Indicator pip */}
                      <div
                        style={{
                          position: "absolute",
                          left: `${pctCur.toFixed(1)}%`,
                          top: "-4px",
                          width: "4px",
                          height: "20px",
                          marginLeft: "-2px",
                          background: "#F2F4F7",
                          borderRadius: "2px",
                        }}
                      />
                    </div>
                    <div style={{ display: "flex", justifyContent: "space-between", fontSize: "12px", color: "#9BA3AF" }}>
                      <span>0</span>
                      <span>{remText}</span>
                      <span>21</span>
                    </div>
                  </>
                );
              })()}
            </div>
          ) : (
            <EmptyState
              message="Doporučený strain zatím není spočítán"
              submessage="Počítá se po probuzení z ranní recovery."
            />
          )}

          {/* What affected recovery card */}
          {data?.scores.recovery !== null && data?.scores.recovery !== undefined ? (
            <div
              style={{
                background: "#16191E",
                borderRadius: "16px",
                padding: "16px",
                display: "flex",
                flexDirection: "column",
                gap: "4px",
              }}
            >
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", paddingBottom: "8px" }}>
                <div style={{ fontSize: "15px", fontWeight: 700 }}>Co ovlivnilo recovery</div>
                <a
                  href={`/recovery${query}`}
                  style={{ fontSize: "13px", fontWeight: 600, color: "#7DB8FF", textDecoration: "none" }}
                >
                  Detail
                </a>
              </div>

              {(data.scores.components ?? []).map((c) => {
                const signal = RECOVERY_SIGNALS[c.signal];
                const pts = formatPoints(c.points);
                return (
                  <div
                    key={c.signal}
                    style={{
                      display: "grid",
                      gridTemplateColumns: "minmax(0, 1fr) 84px 64px",
                      gap: "8px",
                      alignItems: "center",
                      minHeight: "40px",
                      borderTop: "1px solid #23272E",
                    }}
                  >
                    <div style={{ fontSize: "14px" }}>{signal?.label ?? c.signal}</div>
                    <div style={{ fontSize: "14px", fontWeight: 600, textAlign: "right" }}>
                      {c.value !== null ? (signal ? signal.format(c.value) : formatDecimal(c.value, 1)) : "–"}
                    </div>
                    <div style={{ fontSize: "13px", fontWeight: 700, color: pts.color, textAlign: "right" }}>
                      {pts.text}
                    </div>
                  </div>
                );
              })}

              <div style={{ fontSize: "12px", color: "#9BA3AF", paddingTop: "4px" }}>
                Body oproti tvému normálu za 30 nocí (57 % = běžná noc).
              </div>
            </div>
          ) : (
            <EmptyState
              message="Recovery se počítá po synchronizaci noci"
              submessage="Jakmile náramek zaznamená noční spánek a probuzení, skóre se zobrazí zde."
            />
          )}

          {/* Activity card */}
          <div
            style={{
              position: "relative",
              background: "#16191E",
              borderRadius: "16px",
              padding: "16px",
              display: "flex",
              flexDirection: "column",
              gap: "12px",
            }}
          >
            {/* Stretched card link to /aktivita */}
            <a
              href={`/aktivita${query}`}
              aria-label="Aktivita: detail"
              style={{
                position: "absolute",
                inset: 0,
                borderRadius: "16px",
                zIndex: 1,
              }}
            />

            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                position: "relative",
                zIndex: 2,
                pointerEvents: "none",
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                <div style={{ fontSize: "15px", fontWeight: 700 }}>Aktivita</div>
                <svg
                  width="16"
                  height="16"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="#9BA3AF"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  aria-hidden="true"
                >
                  <path d="M9 18l6-6-6-6" />
                </svg>
              </div>
              <a
                href={`/strain${query}`}
                style={{
                  fontSize: "13px",
                  fontWeight: 600,
                  color: "#7DB8FF",
                  textDecoration: "none",
                  pointerEvents: "auto",
                  padding: "4px 8px",
                  margin: "-4px -8px",
                  minHeight: "44px",
                  display: "inline-flex",
                  alignItems: "center",
                }}
              >
                Strain ›
              </a>
            </div>
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(3, minmax(0, 1fr))",
                gap: "8px",
                position: "relative",
                zIndex: 1,
                pointerEvents: "none",
              }}
            >
              <div style={{ display: "flex", flexDirection: "column", gap: "2px" }}>
                <div style={{ fontSize: "20px", fontWeight: 700 }}>
                  {formatNumber(data?.activity.steps)}
                </div>
                <div style={{ fontSize: "12px", color: "#9BA3AF" }}>kroků</div>
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: "2px" }}>
                <div style={{ fontSize: "20px", fontWeight: 700 }}>
                  {formatNumber(data?.activity.active_minutes)}
                </div>
                <div style={{ fontSize: "12px", color: "#9BA3AF" }}>aktivních min</div>
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: "2px" }}>
                <div style={{ fontSize: "20px", fontWeight: 700 }}>
                  {formatNumber(data?.activity.calories_out)}
                </div>
                <div style={{ fontSize: "12px", color: "#9BA3AF" }}>kcal výdej</div>
              </div>
            </div>

            {/* Activities list */}
            {data?.activities && data.activities.length > 0 && (
              <div
                style={{
                  display: "flex",
                  flexDirection: "column",
                  gap: "8px",
                  paddingTop: "4px",
                  position: "relative",
                  zIndex: 1,
                  pointerEvents: "none",
                }}
              >
                {data.activities.map((act, i) => {
                  const startTime = act.start_ts ? formatTime(act.start_ts) : "";
                  const endTime = act.end_ts ? formatTime(act.end_ts) : "";
                  const timeRange = startTime && endTime ? `${startTime}–${endTime}` : "";
                  const isStrength = act.type === "strength";

                  return (
                    <div
                      key={i}
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
                          {isStrength && act.hard_sets
                            ? ` · ${act.hard_sets} těžkých sérií`
                            : act.distance_km
                              ? ` · ${formatDecimal(act.distance_km, 1)} km`
                              : ""}
                        </div>
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
          </div>

          {/* In night vitals card */}
          <a
            href={`/noc${query}`}
            aria-label="V noci"
            style={{
              textDecoration: "none",
              color: "#F2F4F7",
              background: "#16191E",
              borderRadius: "16px",
              padding: "16px",
              display: "flex",
              flexDirection: "column",
              gap: "12px",
            }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <div style={{ fontSize: "15px", fontWeight: 700 }}>V noci</div>
              <svg
                width="16"
                height="16"
                viewBox="0 0 24 24"
                fill="none"
                stroke="#9BA3AF"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
                aria-hidden="true"
              >
                <path d="M9 18l6-6-6-6" />
              </svg>
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: "12px" }}>
              <div style={{ display: "flex", flexDirection: "column", gap: "2px" }}>
                <div style={{ fontSize: "12px", color: "#9BA3AF" }}>SpO2</div>
                <div style={{ fontSize: "17px", fontWeight: 700 }}>
                  {data?.vitals.spo2_avg !== null && data?.vitals.spo2_avg !== undefined
                    ? `${Math.round(data.vitals.spo2_avg)} %`
                    : "–"}
                </div>
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: "2px" }}>
                <div style={{ fontSize: "12px", color: "#9BA3AF" }}>Dech</div>
                <div style={{ fontSize: "17px", fontWeight: 700 }}>
                  {data?.vitals.breathing_rate !== null && data?.vitals.breathing_rate !== undefined
                    ? `${formatDecimal(data.vitals.breathing_rate, 1)} /min`
                    : "–"}
                </div>
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: "2px" }}>
                <div style={{ fontSize: "12px", color: "#9BA3AF" }}>Teplota kůže</div>
                <div style={{ fontSize: "17px", fontWeight: 700 }}>
                  {data?.vitals.skin_temp_delta !== null && data?.vitals.skin_temp_delta !== undefined
                    ? `${formatDecimal(data.vitals.skin_temp_delta, 1, true)} °C`
                    : "–"}
                </div>
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: "2px" }}>
                <div style={{ fontSize: "12px", color: "#9BA3AF" }}>HRV</div>
                <div style={{ fontSize: "17px", fontWeight: 700 }}>
                  {data?.vitals.hrv_rmssd_ms !== null && data?.vitals.hrv_rmssd_ms !== undefined
                    ? `${Math.round(data.vitals.hrv_rmssd_ms)} ms`
                    : "–"}
                </div>
              </div>
            </div>
          </a>
        </>
      )}
    </div>
  );
}
