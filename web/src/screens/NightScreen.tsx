import { useEffect, useState } from "preact/hooks";
import { apiFetch } from "../api";
import { EmptyState } from "../components/EmptyState";
import { Header } from "../components/Header";
import { Skeleton } from "../components/Skeleton";
import { TimeChart } from "../components/TimeChart";
import { formatDateCzech, formatDecimal } from "../helpers";
import { NightResponse } from "../types";

interface NightScreenProps {
  date: string;
}

export function NightScreen({ date }: NightScreenProps) {
  const [data, setData] = useState<NightResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const loadData = async (isRef = false) => {
    if (isRef) setRefreshing(true);
    else setLoading(true);

    const res = await apiFetch<NightResponse>(
      `/api/night?date=${encodeURIComponent(date)}&days=30`
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

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
      <Header
        title={`V noci · ${dateFormatted}`}
        backHref={`/${query}`}
        backLabel="Zpět na Dnes"
        asOf={data?.as_of}
        onRefresh={() => loadData(true)}
        isRefreshing={refreshing}
      />

      {loading && !data ? (
        <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
          <Skeleton height={180} />
          <Skeleton height={180} />
          <Skeleton height={180} />
        </div>
      ) : !data ? (
        <EmptyState message="Zatím žádná noční data" />
      ) : (
        <>
          {/* HRV card */}
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
              <div style={{ fontSize: "13px", color: "#C9CED6" }}>
                {data.hrv.current !== null ? `${Math.round(data.hrv.current)} ms` : "–"} · Ø{" "}
                {data.hrv.avg !== null ? `${Math.round(data.hrv.avg)} ms` : "–"}
              </div>
            </div>

            <TimeChart
              points={data.hrv.series.map((s) => ({ date: s.date, values: [s.val] }))}
              series={[
                {
                  label: "HRV",
                  color: "#5FE39E",
                  unit: "ms",
                  format: (v) => `${Math.round(v)} ms`,
                  kind: "line",
                },
              ]}
              band={data.hrv.series.map((s) => ({ lo: s.band_lo, hi: s.band_hi }))}
              bandColor="rgba(95, 227, 158, 0.12)"
              height={110}
              yAxis={true}
              xAxis={true}
              ariaLabel="Graf HRV za 30 dní"
            />

            {data.hrv.band && (
              <div style={{ fontSize: "12px", color: "#9BA3AF" }}>
                pásmo = tvůj normál ({Math.round(data.hrv.band[0])}–{Math.round(data.hrv.band[1])} ms)
              </div>
            )}
          </div>

          {/* Klidový tep card */}
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
              <div style={{ fontSize: "13px", color: "#C9CED6" }}>
                {data.rhr.current !== null ? `${Math.round(data.rhr.current)} bpm` : "–"} · Ø{" "}
                {data.rhr.avg !== null ? `${Math.round(data.rhr.avg)} bpm` : "–"}
              </div>
            </div>

            <TimeChart
              points={data.rhr.series.map((s) => ({ date: s.date, values: [s.val] }))}
              series={[
                {
                  label: "Klidový tep",
                  color: "#7DB8FF",
                  unit: "bpm",
                  format: (v) => `${Math.round(v)} bpm`,
                  kind: "line",
                },
              ]}
              band={data.rhr.series.map((s) => ({ lo: s.band_lo, hi: s.band_hi }))}
              bandColor="rgba(125, 184, 255, 0.12)"
              height={110}
              yAxis={true}
              xAxis={true}
              ariaLabel="Graf klidového tepu za 30 dní"
            />

            {data.rhr.band && (
              <div style={{ fontSize: "12px", color: "#9BA3AF" }}>
                pásmo = tvůj normál ({Math.round(data.rhr.band[0])}–{Math.round(data.rhr.band[1])} bpm)
              </div>
            )}
          </div>

          {/* SpO2 card */}
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
              <div style={{ fontSize: "15px", fontWeight: 700 }}>SpO₂ · 30 dní</div>
              <div style={{ fontSize: "13px", color: "#C9CED6" }}>
                {data.spo2.current !== null ? `${Math.round(data.spo2.current)} %` : "–"} · Ø{" "}
                {data.spo2.avg !== null ? `${formatDecimal(data.spo2.avg, 1)} %` : "–"}
              </div>
            </div>

            <TimeChart
              points={data.spo2.series.map((s) => ({ date: s.date, values: [s.val] }))}
              series={[
                {
                  label: "SpO₂",
                  color: "#2BD47D",
                  unit: "%",
                  format: (v) => `${Math.round(v)} %`,
                  kind: "line",
                },
              ]}
              height={110}
              yAxis={true}
              xAxis={true}
              ariaLabel="Graf SpO₂ za 30 dní"
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
              <div style={{ fontSize: "13px", color: "#C9CED6" }}>
                {data.breathing.current !== null ? `${formatDecimal(data.breathing.current, 1)} /min` : "–"} · Ø{" "}
                {data.breathing.avg !== null ? `${formatDecimal(data.breathing.avg, 1)} /min` : "–"}
              </div>
            </div>

            <TimeChart
              points={data.breathing.series.map((s) => ({ date: s.date, values: [s.val] }))}
              series={[
                {
                  label: "Dech",
                  color: "#7DB8FF",
                  unit: "/min",
                  format: (v) => `${formatDecimal(v, 1)} /min`,
                  kind: "line",
                },
              ]}
              band={data.breathing.series.map((s) => ({ lo: s.band_lo, hi: s.band_hi }))}
              bandColor="rgba(125, 184, 255, 0.12)"
              height={110}
              yAxis={true}
              xAxis={true}
              ariaLabel="Graf dechové frekvence za 30 dní"
            />

            {data.breathing.band && (
              <div style={{ fontSize: "12px", color: "#9BA3AF" }}>
                pásmo = tvůj normál ({formatDecimal(data.breathing.band[0], 1)}–{formatDecimal(data.breathing.band[1], 1)} /min)
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
              <div style={{ fontSize: "13px", color: "#C9CED6" }}>
                {data.skin_temp.current !== null ? `${formatDecimal(data.skin_temp.current, 1, true)} °C` : "–"} · Ø{" "}
                {data.skin_temp.avg !== null ? `${formatDecimal(data.skin_temp.avg, 2, true)} °C` : "–"}
              </div>
            </div>

            <TimeChart
              points={data.skin_temp.series.map((s) => ({ date: s.date, values: [s.val] }))}
              series={[
                {
                  label: "Teplota kůže",
                  color: "#FFB15C",
                  unit: "°C",
                  format: (v) => `${formatDecimal(v, 1, true)} °C`,
                  kind: "line",
                },
              ]}
              band={data.skin_temp.series.map((s) => ({ lo: s.band_lo, hi: s.band_hi }))}
              bandColor="rgba(255, 177, 92, 0.12)"
              height={110}
              yAxis={true}
              xAxis={true}
              ariaLabel="Graf odchylky teploty kůže za 30 dní"
            />

            {data.skin_temp.band && (
              <div style={{ fontSize: "12px", color: "#9BA3AF" }}>
                pásmo = tvůj normál ({formatDecimal(data.skin_temp.band[0], 1, true)} až {formatDecimal(data.skin_temp.band[1], 1, true)} °C)
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}
