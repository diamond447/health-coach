import { useEffect, useState } from "preact/hooks";
import { apiFetch } from "../api";
import { EmptyState } from "../components/EmptyState";
import { Header } from "../components/Header";
import { RingDial } from "../components/RingDial";
import { Skeleton } from "../components/Skeleton";
import { TimeChart } from "../components/TimeChart";
import {
  formatDateCzech,
  formatDecimal,
  formatPoints,
  RECOVERY_SIGNALS,
  recoveryColor,
  recoveryZoneLabel,
} from "../helpers";
import { RecoveryResponse } from "../types";

interface RecoveryScreenProps {
  date: string;
}

export function RecoveryScreen({ date }: RecoveryScreenProps) {
  const [data, setData] = useState<RecoveryResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const loadData = async (isRef = false) => {
    if (isRef) setRefreshing(true);
    else setLoading(true);

    const res = await apiFetch<RecoveryResponse>(
      `/api/recovery?date=${encodeURIComponent(date)}&days=30`
    );
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
  const dateFormatted = formatDateCzech(date);

  const [hrvBandLo, hrvBandHi] = data?.hrv_band ?? [null, null];
  const [rhrBandLo, rhrBandHi] = data?.rhr_band ?? [null, null];

  const latestBr = data?.breathing_series
    ?.slice()
    .reverse()
    .find((s) => s.band_lo !== null && s.band_hi !== null);
  const latestTemp = data?.skin_temp_series
    ?.slice()
    .reverse()
    .find((s) => s.band_lo !== null && s.band_hi !== null);

  const currentSleepPerf = data?.sleep_series?.length
    ? data.sleep_series[data.sleep_series.length - 1].val
    : null;
  const currentBr = data?.breathing_series?.length
    ? data.breathing_series[data.breathing_series.length - 1].val
    : null;
  const currentTemp = data?.skin_temp_series?.length
    ? data.skin_temp_series[data.skin_temp_series.length - 1].val
    : null;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
      <Header
        title={`Recovery · ${dateFormatted}`}
        backHref={`/${query}`}
        backLabel="Zpět na Dnes"
        asOf={data?.as_of}
        onRefresh={() => loadData(true)}
        isRefreshing={refreshing}
      />

      {loading && !data ? (
        <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
          <Skeleton height={240} />
          <Skeleton height={180} />
          <Skeleton height={180} />
        </div>
      ) : data?.recovery === null || data?.recovery === undefined ? (
        <EmptyState
          message="Recovery se počítá po synchronizaci noci"
          submessage="Zatím nemáme dostatek nočních dat pro výpočet recovery pro tento den."
        />
      ) : (
        <>
          {/* Main big ring dial */}
          <div
            style={{
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              gap: "12px",
              padding: "8px 0",
            }}
          >
            <RingDial
              value={data.recovery}
              max={100}
              size={200}
              strokeWidth={8}
              unit="%"
              color={recoveryColor(data.recovery)}
              ariaLabel={`Recovery ${data.recovery} procent, ${recoveryZoneLabel(data.recovery).toLowerCase()}`}
              sublabel={recoveryZoneLabel(data.recovery)}
              sublabelColor={recoveryColor(data.recovery)}
            />
            {data.summary && (
              <div
                style={{
                  fontSize: "15px",
                  color: "#C9CED6",
                  textAlign: "center",
                  maxWidth: "320px",
                  lineHeight: 1.4,
                }}
              >
                {data.summary}
              </div>
            )}
          </div>

          {/* HRV 30 days card */}
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
              <div style={{ fontSize: "15px", fontWeight: 700 }}>HRV · 30 dní</div>
              <div style={{ fontSize: "15px", fontWeight: 700 }}>
                {data.current_hrv !== null ? `${Math.round(data.current_hrv)} ms` : "–"}
              </div>
            </div>

            <TimeChart
              points={data.hrv_series.map((s) => ({ date: s.date, values: [s.val] }))}
              series={[
                {
                  label: "HRV",
                  color: "#5FE39E",
                  unit: "ms",
                  format: (v) => `${Math.round(v)} ms`,
                  kind: "line",
                },
              ]}
              band={data.hrv_series.map((s) => ({ lo: s.band_lo, hi: s.band_hi }))}
              bandColor="rgba(95, 227, 158, 0.12)"
              height={110}
              yAxis={true}
              xAxis={true}
              ariaLabel={`Graf HRV za 30 dní, dnes ${data.current_hrv !== null ? Math.round(data.current_hrv) : "–"} ms`}
            />

            {hrvBandLo !== null && hrvBandHi !== null && (
              <div style={{ fontSize: "12px", color: "#9BA3AF" }}>
                pásmo = tvůj normál ({Math.round(hrvBandLo)}–{Math.round(hrvBandHi)} ms)
              </div>
            )}
          </div>

          {/* RHR 30 days card */}
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
              <div style={{ fontSize: "15px", fontWeight: 700 }}>Klidový tep · 30 dní</div>
              <div style={{ fontSize: "15px", fontWeight: 700 }}>
                {data.current_rhr !== null ? `${Math.round(data.current_rhr)} bpm` : "–"}
              </div>
            </div>

            <TimeChart
              points={data.rhr_series.map((s) => ({ date: s.date, values: [s.val] }))}
              series={[
                {
                  label: "Klidový tep",
                  color: "#7DB8FF",
                  unit: "bpm",
                  format: (v) => `${Math.round(v)} bpm`,
                  kind: "line",
                },
              ]}
              band={data.rhr_series.map((s) => ({ lo: s.band_lo, hi: s.band_hi }))}
              bandColor="rgba(125, 184, 255, 0.12)"
              height={110}
              yAxis={true}
              xAxis={true}
              ariaLabel={`Graf klidového tepu za 30 dní, dnes ${data.current_rhr !== null ? Math.round(data.current_rhr) : "–"} bpm`}
            />

            {rhrBandLo !== null && rhrBandHi !== null && (
              <div style={{ fontSize: "12px", color: "#9BA3AF" }}>
                pásmo = tvůj normál ({Math.round(rhrBandLo)}–{Math.round(rhrBandHi)} bpm)
              </div>
            )}
          </div>

          {/* Výkon spánku card */}
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
              <div style={{ fontSize: "15px", fontWeight: 700 }}>Výkon spánku · 30 dní</div>
              <div style={{ fontSize: "15px", fontWeight: 700 }}>
                {currentSleepPerf !== null && currentSleepPerf !== undefined
                  ? `${Math.round(currentSleepPerf)} %`
                  : "–"}
              </div>
            </div>

            <TimeChart
              points={data.sleep_series.map((s) => ({ date: s.date, values: [s.val] }))}
              series={[
                {
                  label: "Výkon spánku",
                  color: "#9C8CFF",
                  unit: "%",
                  format: (v) => `${Math.round(v)} %`,
                  kind: "line",
                },
              ]}
              height={110}
              yAxis={true}
              xAxis={true}
              ariaLabel="Graf výkonu spánku za 30 dní"
            />
          </div>

          {/* Dech card */}
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
              <div style={{ fontSize: "15px", fontWeight: 700 }}>Dech · 30 dní</div>
              <div style={{ fontSize: "15px", fontWeight: 700 }}>
                {currentBr !== null && currentBr !== undefined
                  ? `${formatDecimal(currentBr, 1)} /min`
                  : "–"}
              </div>
            </div>

            <TimeChart
              points={data.breathing_series.map((s) => ({ date: s.date, values: [s.val] }))}
              series={[
                {
                  label: "Dech",
                  color: "#7DB8FF",
                  unit: "/min",
                  format: (v) => `${formatDecimal(v, 1)} /min`,
                  kind: "line",
                },
              ]}
              band={data.breathing_series.map((s) => ({ lo: s.band_lo, hi: s.band_hi }))}
              bandColor="rgba(125, 184, 255, 0.12)"
              height={110}
              yAxis={true}
              xAxis={true}
              ariaLabel="Graf dechové frekvence za 30 dní"
            />

            {latestBr && latestBr.band_lo !== null && latestBr.band_hi !== null && (
              <div style={{ fontSize: "12px", color: "#9BA3AF" }}>
                pásmo = tvůj normál ({formatDecimal(latestBr.band_lo, 1)}–{formatDecimal(latestBr.band_hi, 1)} /min)
              </div>
            )}
          </div>

          {/* Teplota kůže card */}
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
              <div style={{ fontSize: "15px", fontWeight: 700 }}>Teplota kůže · 30 dní</div>
              <div style={{ fontSize: "15px", fontWeight: 700 }}>
                {currentTemp !== null && currentTemp !== undefined
                  ? `${formatDecimal(currentTemp, 1, true)} °C`
                  : "–"}
              </div>
            </div>

            <TimeChart
              points={data.skin_temp_series.map((s) => ({ date: s.date, values: [s.val] }))}
              series={[
                {
                  label: "Teplota kůže",
                  color: "#FFB15C",
                  unit: "°C",
                  format: (v) => `${formatDecimal(v, 1, true)} °C`,
                  kind: "line",
                },
              ]}
              band={data.skin_temp_series.map((s) => ({ lo: s.band_lo, hi: s.band_hi }))}
              bandColor="rgba(255, 177, 92, 0.12)"
              height={110}
              yAxis={true}
              xAxis={true}
              ariaLabel="Graf odchylky teploty kůže za 30 dní"
            />

            {latestTemp && latestTemp.band_lo !== null && latestTemp.band_hi !== null && (
              <div style={{ fontSize: "12px", color: "#9BA3AF" }}>
                pásmo = tvůj normál ({formatDecimal(latestTemp.band_lo, 1, true)} až {formatDecimal(latestTemp.band_hi, 1, true)} °C)
              </div>
            )}
          </div>

          {/* Score breakdown card */}
          {data.components && data.components.length > 0 && (
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
                Z čeho se skóre skládá
              </div>
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "minmax(0, 1fr) 56px 64px",
                  gap: "8px",
                  fontSize: "12px",
                  color: "#9BA3AF",
                  paddingBottom: "4px",
                }}
              >
                <span>Signál</span>
                <span style={{ textAlign: "right" }}>Váha</span>
                <span style={{ textAlign: "right" }}>Odchylka</span>
              </div>

              {data.components.map((comp, idx) => {
                const devColor = formatPoints(comp.points).color;

                return (
                  <div
                    key={idx}
                    style={{
                      display: "grid",
                      gridTemplateColumns: "minmax(0, 1fr) 56px 64px",
                      gap: "8px",
                      alignItems: "center",
                      minHeight: "36px",
                      borderTop: "1px solid #23272E",
                      fontSize: "14px",
                    }}
                  >
                    <span>{RECOVERY_SIGNALS[comp.signal]?.label ?? comp.signal}</span>
                    <span style={{ textAlign: "right", color: "#C9CED6" }}>
                      {Math.round(comp.weight * 100)} %
                    </span>
                    <span style={{ textAlign: "right", fontWeight: 700, color: devColor }}>
                      {formatDecimal(comp.z, 1, true)}
                    </span>
                  </div>
                );
              })}
            </div>
          )}

          {/* Warnings card */}
          <div
            style={{
              background: "#16191E",
              borderRadius: "16px",
              padding: "16px",
              display: "flex",
              alignItems: "center",
              gap: "12px",
            }}
          >
            {data.flags && data.flags.length > 0 ? (
              <>
                <div
                  style={{
                    width: "36px",
                    height: "36px",
                    borderRadius: "18px",
                    background: "#3A1B1B",
                    color: "#FF5A5F",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    flexShrink: 0,
                  }}
                >
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
                    <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
                    <line x1="12" y1="9" x2="12" y2="13" />
                    <line x1="12" y1="17" x2="12.01" y2="17" />
                  </svg>
                </div>
                <div style={{ display: "flex", flexDirection: "column", gap: "2px" }}>
                  <div style={{ fontSize: "14px", fontWeight: 600, color: "#FF5A5F" }}>
                    Varování: {data.flags.join(", ")}
                  </div>
                  <div style={{ fontSize: "12px", color: "#9BA3AF" }}>
                    Byla zaznamenána odchylka v nočních vitálních funkcích.
                  </div>
                </div>
              </>
            ) : (
              <>
                <div
                  style={{
                    width: "36px",
                    height: "36px",
                    borderRadius: "18px",
                    background: "#1B3A2B",
                    color: "#5FE39E",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    flexShrink: 0,
                  }}
                >
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
                    <path d="M5 12l5 5 9-10" />
                  </svg>
                </div>
                <div style={{ display: "flex", flexDirection: "column", gap: "2px" }}>
                  <div style={{ fontSize: "14px", fontWeight: 600 }}>Žádné varování</div>
                  <div style={{ fontSize: "12px", color: "#9BA3AF" }}>
                    Hlídá se nemoc, horečka a nízké SpO2
                  </div>
                </div>
              </>
            )}
          </div>
        </>
      )}
    </div>
  );
}
