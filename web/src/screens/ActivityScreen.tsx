import { useEffect, useState } from "preact/hooks";
import { apiFetch } from "../api";
import { EmptyState } from "../components/EmptyState";
import { Header } from "../components/Header";
import { Skeleton } from "../components/Skeleton";
import { TimeChart } from "../components/TimeChart";
import { formatDateCzech, formatNumber } from "../helpers";
import { ActivityResponse } from "../types";

interface ActivityScreenProps {
  date: string;
}

export function ActivityScreen({ date }: ActivityScreenProps) {
  const [data, setData] = useState<ActivityResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const loadData = async (isRef = false) => {
    if (isRef) setRefreshing(true);
    else setLoading(true);

    const res = await apiFetch<ActivityResponse>(
      `/api/activity?date=${encodeURIComponent(date)}&days=30`
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
        title={`Aktivita · ${dateFormatted}`}
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
        <EmptyState message="Zatím žádná data o aktivitě" />
      ) : (
        <>
          {/* Kroky card */}
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
              <div style={{ fontSize: "15px", fontWeight: 700 }}>Kroky · 30 dní</div>
              <div style={{ fontSize: "13px", color: "#C9CED6" }}>
                Ø {data.steps.avg !== null ? `${formatNumber(data.steps.avg)} kroků` : "–"}
              </div>
            </div>

            <TimeChart
              points={data.steps.series.map((s) => ({ date: s.date, values: [s.val] }))}
              series={[
                {
                  label: "Kroky",
                  color: "#5FE39E",
                  unit: "kroků",
                  format: formatNumber,
                  kind: "bar",
                },
              ]}
              target={data.steps.target ?? undefined}
              targetColor="#FFB15C"
              height={110}
              yAxis={true}
              xAxis={true}
              ariaLabel="Graf kroků za 30 dní"
            />

            {data.steps.target !== null && data.steps.target !== undefined && (
              <div style={{ fontSize: "12px", color: "#9BA3AF" }}>
                Oranžová čára = cíl {formatNumber(data.steps.target)} kroků
              </div>
            )}
          </div>

          {/* Aktivní minuty card */}
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
              <div style={{ fontSize: "15px", fontWeight: 700 }}>Aktivní minuty · 30 dní</div>
              <div style={{ fontSize: "13px", color: "#C9CED6" }}>
                Ø {data.active_minutes.avg !== null ? `${data.active_minutes.avg} min` : "–"}
              </div>
            </div>

            <TimeChart
              points={data.active_minutes.series.map((s) => ({ date: s.date, values: [s.val] }))}
              series={[
                {
                  label: "Aktivní minuty",
                  color: "#3D9BFF",
                  unit: "min",
                  kind: "bar",
                },
              ]}
              height={110}
              yAxis={true}
              xAxis={true}
              ariaLabel="Graf aktivních minut za 30 dní"
            />
          </div>

          {/* Výdej kcal card */}
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
              <div style={{ fontSize: "15px", fontWeight: 700 }}>Výdej kalorií · 30 dní</div>
              <div style={{ fontSize: "13px", color: "#C9CED6" }}>
                Ø {data.calories_out.avg !== null ? `${formatNumber(data.calories_out.avg)} kcal` : "–"}
              </div>
            </div>

            <TimeChart
              points={data.calories_out.series.map((s) => ({ date: s.date, values: [s.val] }))}
              series={[
                {
                  label: "Výdej",
                  color: "#FF7A6B",
                  unit: "kcal",
                  format: (v) => `${formatNumber(v)} kcal`,
                  kind: "line",
                },
              ]}
              height={110}
              yAxis={true}
              xAxis={true}
              ariaLabel="Graf výdeje kalorií za 30 dní"
            />
          </div>
        </>
      )}
    </div>
  );
}
