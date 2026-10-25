import { useEffect, useState } from "preact/hooks";
import { apiFetch } from "../api";
import { EmptyState } from "../components/EmptyState";
import { Header } from "../components/Header";
import { RingDial } from "../components/RingDial";
import { Skeleton } from "../components/Skeleton";
import {
  calculateBand,
  formatDateCzech,
  recoveryColor,
  recoveryZoneLabel,
  seriesPoints,
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

  // HRV chart calculations
  const hrvVals = data?.hrv_series.map((s) => s.val) || [];
  const validHrv = hrvVals.filter((v): v is number => v !== null && !isNaN(v));
  const hrvBandLo = data?.hrv_band?.lo ?? 48;
  const hrvBandHi = data?.hrv_band?.hi ?? 60;
  const minHrv = Math.min(hrvBandLo - 5, ...validHrv.length ? validHrv : [40]);
  const maxHrv = Math.max(hrvBandHi + 5, ...validHrv.length ? validHrv : [70]);

  const hrvPts = seriesPoints(hrvVals, 326, 110, minHrv, maxHrv, 8);
  const hrvBand = calculateBand(hrvBandLo, hrvBandHi, 110, minHrv, maxHrv, 8);

  // RHR chart calculations
  const rhrVals = data?.rhr_series.map((s) => s.val) || [];
  const validRhr = rhrVals.filter((v): v is number => v !== null && !isNaN(v));
  const rhrBandLo = data?.rhr_band?.lo ?? 52;
  const rhrBandHi = data?.rhr_band?.hi ?? 57;
  const minRhr = Math.min(rhrBandLo - 5, ...validRhr.length ? validRhr : [45]);
  const maxRhr = Math.max(rhrBandHi + 5, ...validRhr.length ? validRhr : [65]);

  const rhrPts = seriesPoints(rhrVals, 326, 110, minRhr, maxRhr, 8);
  const rhrBand = calculateBand(rhrBandLo, rhrBandHi, 110, minRhr, maxRhr, 8);

  const startDateCzech = data?.hrv_series.length
    ? formatDateCzech(data.hrv_series[0].date)
    : "30 dní";

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

            <svg
              width="326"
              height="110"
              viewBox="0 0 326 110"
              role="img"
              aria-label={`Graf HRV za 30 dní, dnes ${data.current_hrv !== null ? Math.round(data.current_hrv) : "–"} ms`}
              style={{ width: "100%", height: "auto", overflow: "visible" }}
            >
              <rect x="0" y={hrvBand.y} width="326" height={hrvBand.h} fill="#1B3A2B" rx="3" />
              {hrvPts.points && (
                <>
                  <polyline
                    points={hrvPts.points}
                    fill="none"
                    stroke="#5FE39E"
                    strokeWidth="2"
                    strokeLinejoin="round"
                    strokeLinecap="round"
                  />
                  <circle cx={hrvPts.lastX} cy={hrvPts.lastY} r="4" fill="#5FE39E" />
                </>
              )}
            </svg>

            <div style={{ display: "flex", justifyContent: "space-between", fontSize: "12px", color: "#9BA3AF" }}>
              <span>{startDateCzech}</span>
              <span>
                pásmo = tvůj normál ({Math.round(hrvBandLo)}–{Math.round(hrvBandHi)} ms)
              </span>
              <span>dnes</span>
            </div>
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

            <svg
              width="326"
              height="110"
              viewBox="0 0 326 110"
              role="img"
              aria-label={`Graf klidového tepu za 30 dní, dnes ${data.current_rhr !== null ? Math.round(data.current_rhr) : "–"} bpm`}
              style={{ width: "100%", height: "auto", overflow: "visible" }}
            >
              <rect x="0" y={rhrBand.y} width="326" height={rhrBand.h} fill="#1B2E44" rx="3" />
              {rhrPts.points && (
                <>
                  <polyline
                    points={rhrPts.points}
                    fill="none"
                    stroke="#7DB8FF"
                    strokeWidth="2"
                    strokeLinejoin="round"
                    strokeLinecap="round"
                  />
                  <circle cx={rhrPts.lastX} cy={rhrPts.lastY} r="4" fill="#7DB8FF" />
                </>
              )}
            </svg>

            <div style={{ display: "flex", justifyContent: "space-between", fontSize: "12px", color: "#9BA3AF" }}>
              <span>{startDateCzech}</span>
              <span>
                pásmo = tvůj normál ({Math.round(rhrBandLo)}–{Math.round(rhrBandHi)} bpm)
              </span>
              <span>dnes</span>
            </div>
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
                const devColor =
                  comp.status === "good"
                    ? "#5FE39E"
                    : comp.status === "bad"
                      ? "#FFB15C"
                      : "#9BA3AF";

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
                    <span>{comp.name}</span>
                    <span style={{ textAlign: "right", color: "#C9CED6" }}>{comp.weight}</span>
                    <span style={{ textAlign: "right", fontWeight: 700, color: devColor }}>
                      {comp.deviation}
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
