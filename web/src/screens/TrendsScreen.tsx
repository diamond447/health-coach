import { useEffect, useState } from "preact/hooks";
import { apiFetch } from "../api";
import { EmptyState } from "../components/EmptyState";
import { Header } from "../components/Header";
import { Skeleton } from "../components/Skeleton";
import { TimeChart } from "../components/TimeChart";
import {
  addDays,
  formatDateRangeCzech,
  formatDecimal,
  formatDuration,
  formatDurationShort,
  formatNumber,
  getTodayString,
  isToday,
  recoveryColor,
} from "../helpers";
import { TrendsResponse } from "../types";

interface TrendsScreenProps {
  end?: string;
  days?: 7 | 30 | 90;
  onNavigate?: (newEnd: string | undefined, newDays: 7 | 30 | 90) => void;
  date?: string;
  onDateChange?: (newDate: string) => void;
}

export function TrendsScreen({
  end,
  days: initialDays,
  onNavigate,
  date,
  onDateChange,
}: TrendsScreenProps) {
  const [days, setDays] = useState<7 | 30 | 90>(() => initialDays || 30);
  const [data, setData] = useState<TrendsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  useEffect(() => {
    if (initialDays && initialDays !== days) {
      setDays(initialDays);
    }
  }, [initialDays]);

  // Trendy without ?end= shows the window ending today, regardless of date on other tabs
  const currentDate =
    end || (date && date !== getTodayString() ? date : undefined) || getTodayString();
  const startDate = addDays(currentDate, -(days - 1));
  const rangeLabel = formatDateRangeCzech(startDate, currentDate);
  const isAtToday = isToday(currentDate) || currentDate >= getTodayString();

  const loadData = async (isRef = false) => {
    if (isRef) setRefreshing(true);
    else setLoading(true);

    const queryDate =
      end || (date && date !== getTodayString() ? date : undefined)
        ? `&date=${encodeURIComponent(currentDate)}`
        : "";
    const res = await apiFetch<TrendsResponse>(`/api/trends?days=${days}${queryDate}`);
    if (res.data) {
      setData(res.data);
    }
    setLoading(false);
    setRefreshing(false);
  };

  useEffect(() => {
    loadData();
  }, [days, currentDate]);

  const handleDaysChange = (newDays: 7 | 30 | 90) => {
    setDays(newDays);
    if (onNavigate) {
      onNavigate(end, newDays);
    }
  };

  const handlePrevWindow = () => {
    const newDate = addDays(currentDate, -days);
    if (onNavigate) {
      onNavigate(newDate, days);
    } else if (onDateChange) {
      onDateChange(newDate);
    }
  };

  const handleNextWindow = () => {
    if (isAtToday) return;
    const nextDate = addDays(currentDate, days);
    const todayStr = getTodayString();
    const clampedDate = nextDate >= todayStr ? undefined : nextDate;
    if (onNavigate) {
      onNavigate(clampedDate, days);
    } else if (onDateChange) {
      onDateChange(clampedDate || todayStr);
    }
  };

  const targetKcal = data?.kcal.target || 2400;

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
          href="/kalendar"
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
          href="/denik"
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
          href="/prehled"
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
          href="/healthspan"
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

      {/* Period navigation: prev/next window buttons + range label + 7/30/90 selector */}
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
            onClick={handlePrevWindow}
            aria-label="Předchozí období"
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
            onClick={handleNextWindow}
            disabled={isAtToday}
            aria-label="Následující období"
            style={{
              width: "44px",
              height: "44px",
              minHeight: "44px",
              borderRadius: "12px",
              border: "none",
              background: "#16191E",
              color: isAtToday ? "#5C636D" : "#F2F4F7",
              fontSize: "18px",
              fontWeight: 700,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              cursor: isAtToday ? "not-allowed" : "pointer",
              opacity: isAtToday ? 0.4 : 1,
            }}
          >
            ›
          </button>
          <span style={{ fontSize: "14px", fontWeight: 600, color: "#C9CED6", paddingLeft: "4px" }}>
            {rangeLabel}
          </span>
        </div>

        {/* Period selector: 7, 30, 90 days */}
        <div
          role="group"
          aria-label="Období"
          style={{
            display: "flex",
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
                onClick={() => handleDaysChange(d)}
                aria-pressed={isSelected}
                style={{
                  minHeight: "44px",
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
                {d} dní
              </button>
            );
          })}
        </div>
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
            <TimeChart
              points={data.recovery.series.map((s) => ({
                date: s.date,
                values: [s.val],
              }))}
              series={[
                {
                  label: "Recovery",
                  color: "#2BD47D",
                  unit: "%",
                  kind: "bar",
                  colorOf: (v) => recoveryColor(v),
                },
              ]}
              height={90}
              yAxis={true}
              xAxis={false}
              ariaLabel="Trend recovery"
            />
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
            <TimeChart
              points={data.hrv.series.map((s, idx) => ({
                date: s.date,
                values: [s.val, data.rhr.series[idx]?.val ?? null],
              }))}
              series={[
                {
                  label: "HRV",
                  color: "#5FE39E",
                  unit: "ms",
                  kind: "line",
                },
                {
                  label: "Klidový tep",
                  color: "#7DB8FF",
                  unit: "bpm",
                  kind: "line",
                  strokeDasharray: "4 3",
                },
              ]}
              height={100}
              yAxis={true}
              xAxis={true}
              ariaLabel="Trend HRV a klidového tepu"
            />
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
            <TimeChart
              points={data.sleep.series.map((s) => ({
                date: s.date,
                values: [s.val],
              }))}
              series={[
                {
                  label: "Spánek",
                  color: "#9C8CFF",
                  unit: "min",
                  format: formatDurationShort,
                  kind: "bar",
                },
              ]}
              height={80}
              yAxis={true}
              xAxis={false}
              tickFormat={(min) => {
                const h = min / 60;
                return `${h % 1 === 0 ? h : formatDecimal(h, 1)} h`;
              }}
              ariaLabel="Trend spánku"
            />
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

            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginTop: "4px" }}>
              <div style={{ fontSize: "13px", fontWeight: 600, color: "#9BA3AF" }}>Kardio strain</div>
              <div style={{ fontSize: "12px", color: "#9BA3AF" }}>
                Ø {data.strain.cardio_avg !== null ? formatDecimal(data.strain.cardio_avg, 1) : "–"}
              </div>
            </div>
            <TimeChart
              points={data.strain.cardio_series.map((s) => ({
                date: s.date,
                values: [s.val],
              }))}
              series={[
                {
                  label: "Kardio strain",
                  color: "#3D9BFF",
                  unit: "",
                  format: (v) => formatDecimal(v, 1),
                  kind: "bar",
                },
              ]}
              height={70}
              yAxis={true}
              xAxis={false}
              ariaLabel="Trend kardio strainu"
            />

            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginTop: "6px" }}>
              <div style={{ fontSize: "13px", fontWeight: 600, color: "#9BA3AF" }}>Svalová zátěž</div>
              <div style={{ fontSize: "12px", color: "#9BA3AF" }}>
                Ø {data.strain.muscular_avg !== null ? `${Math.round(data.strain.muscular_avg)} %` : "–"}
              </div>
            </div>
            <TimeChart
              points={data.strain.muscular_series.map((s) => ({
                date: s.date,
                values: [s.val],
              }))}
              series={[
                {
                  label: "Svaly",
                  color: "#C38BFF",
                  unit: "%",
                  format: (v) => `${Math.round(v)} %`,
                  kind: "bar",
                },
              ]}
              height={70}
              yAxis={true}
              xAxis={false}
              ariaLabel="Trend svalové zátěže"
            />
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
            <TimeChart
              points={data.weight.series.map((s) => ({
                date: s.date,
                values: [s.raw, s.avg],
              }))}
              series={[
                {
                  label: "vážení",
                  color: "#5C636D",
                  unit: "kg",
                  format: (v) => `${formatDecimal(v, 1)} kg`,
                  kind: "dots",
                },
                {
                  label: "průměr",
                  color: "#F2F4F7",
                  unit: "kg",
                  format: (v) => `${formatDecimal(v, 1)} kg`,
                  kind: "line",
                },
              ]}
              height={90}
              yAxis={true}
              xAxis={true}
              ariaLabel="Trend váhy, 7denní průměr"
            />
            <div style={{ fontSize: "12px", color: "#9BA3AF" }}>
              Tečky = jednotlivá vážení (denně kolísají o vodu) · čára = 7denní průměr
            </div>
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
            <TimeChart
              points={data.kcal.series.map((s) => ({
                date: s.date,
                values: [s.val],
              }))}
              series={[
                {
                  label: "Příjem",
                  color: "#6B7480",
                  unit: "kcal",
                  format: (v) => `${formatNumber(v)} kcal`,
                  kind: "bar",
                },
              ]}
              target={targetKcal}
              height={80}
              yAxis={true}
              xAxis={false}
              ariaLabel="Trend příjmu kalorií"
            />
            <div style={{ fontSize: "12px", color: "#9BA3AF" }}>
              Oranžová čára = cíl {formatNumber(targetKcal)} kcal
            </div>
          </div>
        </>
      )}
    </div>
  );
}
