import { useEffect, useState } from "preact/hooks";
import { apiFetch } from "../api";
import { EmptyState } from "../components/EmptyState";
import { Header } from "../components/Header";
import { RingDial } from "../components/RingDial";
import { Skeleton } from "../components/Skeleton";
import { formatDateCzech, formatDuration, formatDurationShort, formatTime, sleepColor } from "../helpers";
import { SleepResponse, SleepStage } from "../types";

interface SleepScreenProps {
  date: string;
  onDateChange: (date: string) => void;
}

export function SleepScreen({ date, onDateChange }: SleepScreenProps) {
  const [data, setData] = useState<SleepResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const loadData = async (isRef = false) => {
    if (isRef) setRefreshing(true);
    else setLoading(true);

    const res = await apiFetch<SleepResponse>(`/api/sleep?date=${encodeURIComponent(date)}`);
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

  // Hypnogram calculation
  const STAGE_Y: Record<string, number> = {
    awake: 2,
    rem: 24,
    light: 46,
    deep: 68,
  };
  const STAGE_COLORS: Record<string, string> = {
    awake: "#E8EAED",
    rem: "#9C8CFF",
    light: "#4F7FE0",
    deep: "#2A3F9E",
  };

  const stages = data?.stages || [];
  const totalDurationSec = stages.reduce((acc, s) => acc + (s.duration_sec || 0), 0) || 1;
  const hypnoScale = 254 / totalDurationSec;

  let curX = 0;
  const hypnoSegments = stages.map((s) => {
    const w = Math.max(1, (s.duration_sec || 0) * hypnoScale - 0.5);
    const seg = {
      x: curX,
      y: STAGE_Y[s.stage] ?? 46,
      w,
      c: STAGE_COLORS[s.stage] ?? "#4F7FE0",
    };
    curX += (s.duration_sec || 0) * hypnoScale;
    return seg;
  });

  const STAGE_LABELS: Record<SleepStage, string> = {
    awake: "Bdělost",
    rem: "REM",
    light: "Lehký",
    deep: "Hluboký",
  };
  const totals = data?.stage_totals;
  const asleepMin = totals ? totals.rem + totals.light + totals.deep : 0;

  // Tonight's plan: bedtime and wake come from the scores job; the reminder fires
  // 30 minutes before bedtime.
  const plan = data?.tonight_plan;
  const bedMs = plan?.planned_bedtime ? Date.parse(plan.planned_bedtime) : NaN;
  const wakeMs = plan?.planned_wake ? Date.parse(plan.planned_wake) : NaN;
  const planInBedMin = !isNaN(bedMs) && !isNaN(wakeMs) ? Math.round((wakeMs - bedMs) / 60000) : null;
  const reminderTime = !isNaN(bedMs) ? formatTime(new Date(bedMs - 30 * 60000).toISOString()) : null;

  const sessionStart = data?.session?.start_ts ? formatTime(data.session.start_ts) : "";
  const sessionEnd = data?.session?.end_ts ? formatTime(data.session.end_ts) : "";

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
      <Header
        title={`Spánek · noc na ${dateFormatted}`}
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
          <Skeleton height={200} />
        </div>
      ) : !data?.session?.duration_min ? (
        <EmptyState
          message="Zatím žádná data o spánku"
          submessage="Spánek pro tuto noc ještě nebyl synchronizován nebo zaznamenán."
        />
      ) : (
        <>
          {/* Top Ring & summary */}
          <div style={{ display: "flex", alignItems: "center", gap: "16px" }}>
            <RingDial
              value={data.performance}
              max={100}
              size={132}
              strokeWidth={9}
              unit="%"
              color={sleepColor(data.performance)}
              ariaLabel={`Výkon spánku ${data.performance ?? 0} procent`}
              sublabel="VÝKON"
              sublabelColor="#B8B0FF"
            />
            <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
              <div style={{ fontSize: "28px", fontWeight: 800 }}>
                {formatDuration(data.session.duration_min)}
              </div>
              <div style={{ fontSize: "14px", color: "#C9CED6" }}>
                z potřebných {formatDuration(data.need_breakdown.total_need_min)}
              </div>
              <div style={{ fontSize: "13px", color: "#9BA3AF" }}>
                {sessionStart} → {sessionEnd} · v posteli {formatDuration(data.session.time_in_bed_min)}
              </div>
            </div>
          </div>

          {/* Tonight's plan card */}
          {plan && planInBedMin !== null && (
            <div
              style={{
                background: "#1E1B3A",
                borderRadius: "16px",
                padding: "16px",
                display: "flex",
                flexDirection: "column",
                gap: "10px",
              }}
            >
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
                <div style={{ fontSize: "15px", fontWeight: 700 }}>Plán na dnešní noc</div>
                <div style={{ fontSize: "12px", color: "#C4BEFF" }}>
                  připomínka v {reminderTime}
                </div>
              </div>
              <div style={{ display: "flex", alignItems: "baseline", gap: "8px" }}>
                <div style={{ fontSize: "34px", fontWeight: 800 }}>{formatTime(plan.planned_bedtime)}</div>
                <div style={{ fontSize: "14px", color: "#D6D2FF" }}>
                  jdi spát · budík {formatTime(plan.planned_wake)}
                </div>
              </div>
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(3, minmax(0, 1fr))",
                  gap: "8px",
                  fontSize: "12px",
                  color: "#C4BEFF",
                }}
              >
                <div style={{ display: "flex", flexDirection: "column", gap: "2px" }}>
                  <span>Potřeba</span>
                  <span style={{ fontSize: "15px", fontWeight: 700, color: "#F2F4F7" }}>
                    {formatDuration(plan.sleep_need_min)}
                  </span>
                </div>
                <div style={{ display: "flex", flexDirection: "column", gap: "2px" }}>
                  <span>V posteli</span>
                  <span style={{ fontSize: "15px", fontWeight: 700, color: "#F2F4F7" }}>
                    {formatDuration(planInBedMin)}
                  </span>
                </div>
                <div style={{ display: "flex", flexDirection: "column", gap: "2px" }}>
                  <span>Dnešní strain</span>
                  <span style={{ fontSize: "15px", fontWeight: 700, color: "#F2F4F7" }}>
                    +{plan.today_strain_bonus_min} min
                  </span>
                </div>
              </div>
              <div style={{ fontSize: "12px", color: "#C4BEFF" }}>
                Budík = tvůj obvyklý čas vstávání. Čas v posteli počítá s tvou obvyklou
                efektivitou spánku.
              </div>
            </div>
          )}

          {/* Sleep stages (Hypnogram) */}
          {stages.length > 0 && (
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
              <div style={{ fontSize: "15px", fontWeight: 700 }}>Fáze spánku</div>
              <div style={{ display: "grid", gridTemplateColumns: "64px minmax(0, 1fr)", gap: "8px" }}>
                <div style={{ display: "flex", flexDirection: "column", fontSize: "11px", color: "#9BA3AF" }}>
                  <div style={{ height: "22px", display: "flex", alignItems: "center" }}>Bdělost</div>
                  <div style={{ height: "22px", display: "flex", alignItems: "center" }}>REM</div>
                  <div style={{ height: "22px", display: "flex", alignItems: "center" }}>Lehký</div>
                  <div style={{ height: "22px", display: "flex", alignItems: "center" }}>Hluboký</div>
                </div>
                <svg
                  width="254"
                  height="88"
                  viewBox="0 0 254 88"
                  role="img"
                  aria-label={`Hypnogram noci od ${sessionStart} do ${sessionEnd}`}
                  style={{ width: "100%", height: "auto" }}
                >
                  <rect x="0" y="10" width="254" height="1" fill="#23272E" />
                  <rect x="0" y="32" width="254" height="1" fill="#23272E" />
                  <rect x="0" y="54" width="254" height="1" fill="#23272E" />
                  <rect x="0" y="76" width="254" height="1" fill="#23272E" />
                  {hypnoSegments.map((seg, idx) => (
                    <rect
                      key={idx}
                      x={seg.x.toFixed(1)}
                      y={seg.y}
                      width={seg.w.toFixed(1)}
                      height="16"
                      rx="3"
                      fill={seg.c}
                    />
                  ))}
                </svg>
              </div>

              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  fontSize: "12px",
                  color: "#9BA3AF",
                  paddingLeft: "72px",
                }}
              >
                <span>{sessionStart}</span>
                <span>{sessionEnd}</span>
              </div>

              {/* Totals */}
              {totals && (
                <div
                  style={{
                    display: "grid",
                    gridTemplateColumns: "repeat(4, minmax(0, 1fr))",
                    gap: "8px",
                    paddingTop: "6px",
                    borderTop: "1px solid #23272E",
                  }}
                >
                  {(["awake", "rem", "light", "deep"] as const).map((stage) => (
                    <div key={stage} style={{ display: "flex", flexDirection: "column", gap: "2px", paddingTop: "8px" }}>
                      <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                        <div
                          style={{ width: "8px", height: "8px", borderRadius: "4px", background: STAGE_COLORS[stage] }}
                        />
                        <div style={{ fontSize: "12px", color: "#9BA3AF" }}>{STAGE_LABELS[stage]}</div>
                      </div>
                      <div style={{ fontSize: "15px", fontWeight: 700 }}>{formatDurationShort(totals[stage])}</div>
                      <div style={{ fontSize: "12px", color: "#9BA3AF" }}>
                        {stage === "awake" || asleepMin === 0
                          ? ""
                          : `${Math.round((totals[stage] / asleepMin) * 100)} %`}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* Need breakdown card */}
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
            <div style={{ fontSize: "15px", fontWeight: 700, paddingBottom: "8px" }}>
              Kolik spánku jsi potřeboval
            </div>
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                minHeight: "36px",
                borderTop: "1px solid #23272E",
                fontSize: "14px",
              }}
            >
              <span>Základ</span>
              <span style={{ fontWeight: 600 }}>{formatDuration(data.need_breakdown.base_need_min)}</span>
            </div>
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                minHeight: "36px",
                borderTop: "1px solid #23272E",
                fontSize: "14px",
              }}
            >
              <span>Spánkový dluh (14 nocí)</span>
              <span style={{ fontWeight: 600, color: "#FFB15C" }}>
                +{data.need_breakdown.debt_min} min
              </span>
            </div>
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                minHeight: "36px",
                borderTop: "1px solid #23272E",
                fontSize: "14px",
              }}
            >
              <span>
                Včerejší strain{" "}
                {data.need_breakdown.prev_strain !== null
                  ? data.need_breakdown.prev_strain.toFixed(1).replace(".", ",")
                  : "–"}
              </span>
              <span style={{ fontWeight: 600, color: "#7DB8FF" }}>
                +{data.need_breakdown.strain_bonus_min} min
              </span>
            </div>
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                minHeight: "36px",
                borderTop: "1px solid #23272E",
                fontSize: "14px",
              }}
            >
              <span>Zdřímnutí</span>
              <span style={{ fontWeight: 600, color: "#5FE39E" }}>
                {data.need_breakdown.nap_credit_min > 0 ? `−${data.need_breakdown.nap_credit_min} min` : "0 min"}
              </span>
            </div>
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                minHeight: "40px",
                borderTop: "1px solid #3A3F47",
                fontSize: "15px",
                fontWeight: 700,
              }}
            >
              <span>Potřeba</span>
              <span>{formatDuration(data.need_breakdown.total_need_min)}</span>
            </div>
          </div>

          {/* 3 mini cards */}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: "8px" }}>
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
              <div style={{ fontSize: "12px", color: "#9BA3AF" }}>Efektivita</div>
              <div style={{ fontSize: "20px", fontWeight: 700 }}>
                {data.session.efficiency !== null ? `${Math.round(data.session.efficiency)} %` : "–"}
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
              <div style={{ fontSize: "12px", color: "#9BA3AF" }}>Pravidelnost</div>
              <div style={{ fontSize: "20px", fontWeight: 700 }}>
                {data.consistency !== null ? `${Math.round(data.consistency)} %` : "–"}
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
              <div style={{ fontSize: "12px", color: "#9BA3AF" }}>Probuzení</div>
              <div style={{ fontSize: "20px", fontWeight: 700 }}>{data.session.wake_count}×</div>
            </div>
          </div>

          {/* Last 7 nights bars */}
          {data.week && data.week.length > 0 && (
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
                <div style={{ fontSize: "15px", fontWeight: 700 }}>Posledních 7 nocí</div>
                <div style={{ fontSize: "12px", color: "#9BA3AF" }}>čárka = potřeba</div>
              </div>

              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(7, minmax(0, 1fr))",
                  gap: "10px",
                  alignItems: "end",
                  height: "130px",
                }}
              >
                {data.week.map((n, idx) => {
                  const px = 130 / 600;
                  const actualH = Math.min(130, Math.round((n.actual_min ?? 0) * px));
                  const needBottom = Math.min(130, Math.round((n.need_min ?? 480) * px));
                  const isGood = (n.actual_min ?? 0) / (n.need_min || 480) >= 0.85;
                  const barColor = isGood ? "#9C8CFF" : "#5D5499";

                  return (
                    <div
                      key={idx}
                      style={{
                        position: "relative",
                        height: "130px",
                        display: "flex",
                        flexDirection: "column",
                        justifyContent: "flex-end",
                      }}
                    >
                      <div
                        style={{
                          position: "absolute",
                          left: "-3px",
                          right: "-3px",
                          bottom: `${needBottom}px`,
                          height: "2px",
                          background: "#F2F4F7",
                          zIndex: 2,
                        }}
                      />
                      <div
                        style={{
                          height: `${actualH}px`,
                          borderRadius: "6px 6px 2px 2px",
                          background: barColor,
                        }}
                      />
                    </div>
                  );
                })}
              </div>

              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(7, minmax(0, 1fr))",
                  gap: "10px",
                  fontSize: "11px",
                  color: "#9BA3AF",
                  textAlign: "center",
                }}
              >
                {data.week.map((n, idx) => (
                  <span key={idx}>{n.weekday}</span>
                ))}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
