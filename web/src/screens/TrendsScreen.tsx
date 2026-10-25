import { useEffect, useState } from "preact/hooks";
import { apiFetch } from "../api";
import { EmptyState } from "../components/EmptyState";
import { Header } from "../components/Header";
import { Skeleton } from "../components/Skeleton";
import {
  formatDecimal,
  formatDuration,
  formatNumber,
  recoveryColor,
  seriesPoints,
} from "../helpers";
import { TrendsResponse } from "../types";

interface TrendsScreenProps {
  date: string;
}

export function TrendsScreen({ date }: TrendsScreenProps) {
  const [days, setDays] = useState<7 | 30 | 90>(30);
  const [data, setData] = useState<TrendsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const loadData = async (isRef = false) => {
    if (isRef) setRefreshing(true);
    else setLoading(true);

    const res = await apiFetch<TrendsResponse>(`/api/trends?days=${days}`);
    if (res.data) {
      setData(res.data);
    }
    setLoading(false);
    setRefreshing(false);
  };

  useEffect(() => {
    loadData();
  }, [days]);

  const query = date ? `?date=${encodeURIComponent(date)}` : "";
  const gap = days > 30 ? 1 : 3;

  // HRV & RHR chart geometry
  const hrvVals = data?.hrv.series.map((s) => s.val) || [];
  const rhrVals = data?.rhr.series.map((s) => s.val) || [];
  const validHrv = hrvVals.filter((v): v is number => v !== null && !isNaN(v));
  const validRhr = rhrVals.filter((v): v is number => v !== null && !isNaN(v));

  const minHrv = Math.min(...validHrv.length ? validHrv : [35]) - 2;
  const maxHrv = Math.max(...validHrv.length ? validHrv : [70]) + 2;
  const hrvPts = seriesPoints(hrvVals, 326, 100, minHrv, maxHrv, 4);

  const minRhr = Math.min(...validRhr.length ? validRhr : [45]) - 2;
  const maxRhr = Math.max(...validRhr.length ? validRhr : [65]) + 2;
  const rhrPts = seriesPoints(rhrVals, 326, 100, minRhr, maxRhr, 4);

  // Weight chart geometry
  const wtRaw = data?.weight.series.map((s) => s.raw) || [];
  const wtAvg = data?.weight.series.map((s) => s.avg) || [];
  const validWt = [
    ...wtRaw.filter((v): v is number => v !== null && !isNaN(v)),
    ...wtAvg.filter((v): v is number => v !== null && !isNaN(v)),
  ];
  const minWt = Math.min(...validWt.length ? validWt : [70]) - 0.5;
  const maxWt = Math.max(...validWt.length ? validWt : [85]) + 0.5;
  const wtRawPts = seriesPoints(wtRaw, 326, 90, minWt, maxWt, 4);
  const wtAvgPts = seriesPoints(wtAvg, 326, 90, minWt, maxWt, 4);

  // Calorie chart target line
  const targetKcal = data?.kcal.target || 2400;
  const maxKcal = Math.max(3000, targetKcal + 500, ...(data?.kcal.series.map((s) => s.val || 0) || [3000]));
  const kcalTargetB = Math.round((targetKcal / maxKcal) * 80);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
      <Header
        title="Trendy"
        asOf={data?.as_of}
        onRefresh={() => loadData(true)}
        isRefreshing={refreshing}
      />

      {/* Sub-nav tiles: Kalendář, Deník, Přehled, Healthspan (2x2 grid) */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: "8px" }}>
        <a
          href={`/kalendar${query}`}
          style={{
            textDecoration: "none",
            color: "#F2F4F7",
            background: "#16191E",
            borderRadius: "14px",
            padding: "12px",
            minHeight: "44px",
            display: "flex",
            flexDirection: "column",
            gap: "4px",
          }}
        >
          <span style={{ fontSize: "14px", fontWeight: 700 }}>Kalendář</span>
          <span style={{ fontSize: "12px", color: "#9BA3AF" }}>měsíc přehled</span>
        </a>
        <a
          href={`/denik${query}`}
          style={{
            textDecoration: "none",
            color: "#F2F4F7",
            background: "#16191E",
            borderRadius: "14px",
            padding: "12px",
            minHeight: "44px",
            display: "flex",
            flexDirection: "column",
            gap: "4px",
          }}
        >
          <span style={{ fontSize: "14px", fontWeight: 700 }}>Deník</span>
          <span style={{ fontSize: "12px", color: "#9BA3AF" }}>vliv návyků</span>
        </a>
        <a
          href={`/prehled${query}`}
          style={{
            textDecoration: "none",
            color: "#F2F4F7",
            background: "#16191E",
            borderRadius: "14px",
            padding: "12px",
            minHeight: "44px",
            display: "flex",
            flexDirection: "column",
            gap: "4px",
          }}
        >
          <span style={{ fontSize: "14px", fontWeight: 700 }}>Přehled</span>
          <span style={{ fontSize: "12px", color: "#9BA3AF" }}>týden / měsíc</span>
        </a>
        <a
          href={`/healthspan${query}`}
          style={{
            textDecoration: "none",
            color: "#F2F4F7",
            background: "#16191E",
            borderRadius: "14px",
            padding: "12px",
            minHeight: "44px",
            display: "flex",
            flexDirection: "column",
            gap: "4px",
          }}
        >
          <span style={{ fontSize: "14px", fontWeight: 700 }}>Healthspan</span>
          <span style={{ fontSize: "12px", color: "#9BA3AF" }}>biologický věk</span>
        </a>
      </div>

      {/* Period selector: 7, 30, 90 days */}
      <div
        role="group"
        aria-label="Období"
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(3, minmax(0, 1fr))",
          gap: "4px",
          padding: "4px",
          borderRadius: "12px",
          background: "#16191E",
        }}
      >
        {([7, 30, 90] as const).map((d) => {
          const isSelected = days === d;
          return (
            <button
              key={d}
              type="button"
              onClick={() => setDays(d)}
              aria-pressed={isSelected}
              style={{
                minHeight: "40px",
                border: "none",
                borderRadius: "9px",
                fontFamily: "inherit",
                fontSize: "14px",
                fontWeight: 600,
                background: isSelected ? "#2C323A" : "transparent",
                color: isSelected ? "#F2F4F7" : "#9BA3AF",
                cursor: "pointer",
              }}
            >
              {d} dní
            </button>
          );
        })}
      </div>

      {loading && !data ? (
        <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
          <Skeleton height={140} />
          <Skeleton height={160} />
          <Skeleton height={140} />
          <Skeleton height={140} />
        </div>
      ) : !data ? (
        <EmptyState message="Zatím žádná data o trendech" />
      ) : (
        <>
          {/* Recovery trend */}
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
              <div style={{ fontSize: "15px", fontWeight: 700 }}>Recovery</div>
              <div style={{ fontSize: "13px", color: "#C9CED6" }}>
                Ø {data.recovery.avg !== null ? `${Math.round(data.recovery.avg)} %` : "–"} ·{" "}
                {data.recovery.green_count}× zelená
              </div>
            </div>
            <div style={{ display: "flex", alignItems: "flex-end", gap: `${gap}px`, height: "90px" }}>
              {data.recovery.series.map((b, idx) => {
                const val = b.val ?? 0;
                const h = Math.round(val * 0.9);
                return (
                  <div
                    key={idx}
                    style={{
                      flex: "1 1 0",
                      height: `${h}px`,
                      borderRadius: "2px",
                      background: recoveryColor(b.val),
                    }}
                  />
                );
              })}
            </div>
          </div>

          {/* HRV & RHR chart */}
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
              <div style={{ fontSize: "15px", fontWeight: 700 }}>HRV a klidový tep</div>
              <div style={{ fontSize: "13px", color: "#C9CED6" }}>
                Ø {data.hrv.avg !== null ? `${Math.round(data.hrv.avg)} ms` : "–"} · Ø{" "}
                {data.rhr.avg !== null ? `${Math.round(data.rhr.avg)} bpm` : "–"}
              </div>
            </div>
            <svg
              width="326"
              height="100"
              viewBox="0 0 326 100"
              role="img"
              aria-label="Trend HRV a klidového tepu"
              style={{ width: "100%", height: "auto" }}
            >
              {hrvPts.points && (
                <polyline
                  points={hrvPts.points}
                  fill="none"
                  stroke="#5FE39E"
                  strokeWidth="2"
                  strokeLinejoin="round"
                />
              )}
              {rhrPts.points && (
                <polyline
                  points={rhrPts.points}
                  fill="none"
                  stroke="#7DB8FF"
                  strokeWidth="2"
                  strokeLinejoin="round"
                  strokeDasharray="4 3"
                />
              )}
            </svg>
            <div style={{ display: "flex", gap: "16px", fontSize: "12px", color: "#9BA3AF" }}>
              <span style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                <span style={{ width: "14px", height: "2px", background: "#5FE39E" }} />
                HRV
              </span>
              <span style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                <span style={{ width: "14px", height: "2px", background: "#7DB8FF" }} />
                Klidový tep (čárkovaně)
              </span>
            </div>
          </div>

          {/* Sleep trend */}
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
              <div style={{ fontSize: "15px", fontWeight: 700 }}>Spánek</div>
              <div style={{ fontSize: "13px", color: "#C9CED6" }}>
                Ø {data.sleep.avg_min !== null ? formatDuration(data.sleep.avg_min) : "–"} · výkon Ø{" "}
                {data.sleep.avg_perf !== null ? `${Math.round(data.sleep.avg_perf)} %` : "–"}
              </div>
            </div>
            <div style={{ display: "flex", alignItems: "flex-end", gap: `${gap}px`, height: "80px" }}>
              {data.sleep.series.map((b, idx) => {
                const m = b.val ?? 0;
                const h = Math.round((m / 600) * 80);
                const isGood = m >= 420; // 7h
                return (
                  <div
                    key={idx}
                    style={{
                      flex: "1 1 0",
                      height: `${h}px`,
                      borderRadius: "2px",
                      background: isGood ? "#9C8CFF" : "#5D5499",
                    }}
                  />
                );
              })}
            </div>
          </div>

          {/* Strain trend */}
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
              <div style={{ fontSize: "15px", fontWeight: 700 }}>Strain</div>
              <div style={{ fontSize: "13px", color: "#C9CED6" }}>
                Ø {data.strain.avg !== null ? formatDecimal(data.strain.avg, 1) : "–"}
                {data.strain.acwr !== null && ` · zátěž 7/28 d ${formatDecimal(data.strain.acwr, 2)}`}
              </div>
            </div>
            <div style={{ display: "flex", alignItems: "flex-end", gap: `${gap}px`, height: "80px" }}>
              {data.strain.series.map((b, idx) => {
                const s = b.val ?? 0;
                const h = Math.round((s / 21) * 80);
                return (
                  <div
                    key={idx}
                    style={{
                      flex: "1 1 0",
                      height: `${h}px`,
                      borderRadius: "2px",
                      background: "#3D9BFF",
                    }}
                  />
                );
              })}
            </div>
          </div>

          {/* Weight trend */}
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
              <div style={{ fontSize: "15px", fontWeight: 700 }}>Váha · 7denní průměr</div>
              <div style={{ fontSize: "13px", color: "#C9CED6" }}>
                {data.weight.last !== null ? `${formatDecimal(data.weight.last, 1)} kg` : "–"}
                {data.weight.rate !== null && ` · ${formatDecimal(data.weight.rate, 2, true)} kg/týden`}
              </div>
            </div>
            <svg
              width="326"
              height="90"
              viewBox="0 0 326 90"
              role="img"
              aria-label="Trend váhy, 7denní průměr"
              style={{ width: "100%", height: "auto" }}
            >
              {wtRawPts.points && (
                <polyline
                  points={wtRawPts.points}
                  fill="none"
                  stroke="#5C636D"
                  strokeWidth="1"
                  strokeLinejoin="round"
                />
              )}
              {wtAvgPts.points && (
                <polyline
                  points={wtAvgPts.points}
                  fill="none"
                  stroke="#F2F4F7"
                  strokeWidth="2.4"
                  strokeLinejoin="round"
                />
              )}
            </svg>
          </div>

          {/* Calorie vs target trend */}
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
              <div style={{ fontSize: "15px", fontWeight: 700 }}>Příjem vs. cíl</div>
              <div style={{ fontSize: "13px", color: "#C9CED6" }}>
                Ø {data.kcal.avg !== null ? `${formatNumber(data.kcal.avg)} kcal` : "–"} · bílkoviny Ø{" "}
                {data.kcal.avg_protein !== null ? `${formatDecimal(data.kcal.avg_protein, 0)} g` : "–"}
              </div>
            </div>
            <div
              style={{
                position: "relative",
                display: "flex",
                alignItems: "flex-end",
                gap: `${gap}px`,
                height: "80px",
              }}
            >
              <div
                style={{
                  position: "absolute",
                  left: 0,
                  right: 0,
                  bottom: `${kcalTargetB}px`,
                  height: "2px",
                  background: "#FFB15C",
                  zIndex: 2,
                }}
              />
              {data.kcal.series.map((b, idx) => {
                const k = b.val ?? 0;
                const h = Math.round((k / maxKcal) * 80);
                return (
                  <div
                    key={idx}
                    style={{
                      flex: "1 1 0",
                      height: `${h}px`,
                      borderRadius: "2px",
                      background: "#6B7480",
                    }}
                  />
                );
              })}
            </div>
            <div style={{ fontSize: "12px", color: "#9BA3AF" }}>
              Oranžová čára = cíl {formatNumber(targetKcal)} kcal
            </div>
          </div>
        </>
      )}
    </div>
  );
}
