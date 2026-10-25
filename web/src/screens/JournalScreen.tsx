import { useEffect, useState } from "preact/hooks";
import { apiFetch } from "../api";
import { EmptyState } from "../components/EmptyState";
import { Header } from "../components/Header";
import { Skeleton } from "../components/Skeleton";
import { formatDateCzech, formatTime } from "../helpers";
import { JournalResponse } from "../types";

interface JournalScreenProps {
  date: string;
}

export function JournalScreen({ date }: JournalScreenProps) {
  const [data, setData] = useState<JournalResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const loadData = async (isRef = false) => {
    if (isRef) setRefreshing(true);
    else setLoading(true);

    const res = await apiFetch<JournalResponse>(`/api/journal?days=60`);
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
  const yesterdayFormatted = data?.yesterday_date ? formatDateCzech(data.yesterday_date) : "";

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
      <Header
        title="Deník · vliv na recovery"
        backHref={`/trendy${query}`}
        backLabel="Zpět na Trendy"
        asOf={data?.as_of}
        onRefresh={() => loadData(true)}
        isRefreshing={refreshing}
      />

      {loading && !data ? (
        <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
          <Skeleton height={140} />
          <Skeleton height={240} />
          <Skeleton height={100} />
        </div>
      ) : !data ? (
        <EmptyState message="Deník zatím nemá dost dní" />
      ) : (
        <>
          {/* Yesterday card */}
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
              <div style={{ fontSize: "15px", fontWeight: 700 }}>Včera, {yesterdayFormatted}</div>
              {data.logged_time && (
                <div style={{ fontSize: "12px", color: "#9BA3AF" }}>
                  zapsal kouč {formatTime(data.logged_time)}
                </div>
              )}
            </div>

            {data.yesterday && data.yesterday.length > 0 ? (
              <div style={{ display: "flex", flexWrap: "wrap", gap: "6px" }}>
                {data.yesterday.map((y, idx) => (
                  <span
                    key={idx}
                    style={{
                      fontSize: "13px",
                      padding: "6px 10px",
                      borderRadius: "999px",
                      background: y.present ? "#1F3550" : "#1D2127",
                      color: y.present ? "#CFE4FF" : "#9BA3AF",
                    }}
                  >
                    {y.label}
                  </span>
                ))}
              </div>
            ) : (
              <div style={{ fontSize: "13px", color: "#9BA3AF" }}>
                Žádné návyky pro včerejší den nebyly zapsány.
              </div>
            )}

            <div style={{ fontSize: "12px", color: "#9BA3AF" }}>
              Zapisuješ v Claude, třeba: „deník: včera 2 piva, sauna, kafe v 15:00“.
            </div>
          </div>

          {/* What affects recovery (insights) */}
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
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "baseline",
                paddingBottom: "4px",
              }}
            >
              <div style={{ fontSize: "15px", fontWeight: 700 }}>Co dělá s tvou recovery</div>
              <div style={{ fontSize: "12px", color: "#9BA3AF" }}>posledních 60 dní</div>
            </div>

            {data.insights && data.insights.length > 0 ? (
              data.insights.map((ins, idx) => {
                const diff = ins.diff_recovery_pct;
                const isPositive = diff > 0;
                const absPct = Math.min(100, Math.round((Math.abs(diff) / 15) * 100));
                const sign = isPositive ? "+" : "−";
                const labelColor = isPositive ? "#7DB8FF" : "#FFB15C";

                return (
                  <div
                    key={idx}
                    style={{
                      display: "flex",
                      flexDirection: "column",
                      gap: "6px",
                      padding: "8px 0",
                      borderTop: "1px solid #23272E",
                    }}
                  >
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
                      <span style={{ fontSize: "14px" }}>{ins.label}</span>
                      <span style={{ fontSize: "14px", fontWeight: 700, color: labelColor }}>
                        {sign}
                        {Math.abs(diff)} %
                      </span>
                    </div>

                    {/* Centered two-way bar */}
                    <div
                      style={{
                        display: "grid",
                        gridTemplateColumns: "repeat(2, minmax(0, 1fr))",
                        height: "8px",
                      }}
                    >
                      <div
                        style={{
                          display: "flex",
                          justifyContent: "flex-end",
                          borderRight: "1px solid #3A3F47",
                        }}
                      >
                        {!isPositive && (
                          <div
                            style={{
                              width: `${absPct}%`,
                              height: "8px",
                              borderRadius: "4px 0 0 4px",
                              background: "#FFB15C",
                            }}
                          />
                        )}
                      </div>
                      <div style={{ display: "flex" }}>
                        {isPositive && (
                          <div
                            style={{
                              width: `${absPct}%`,
                              height: "8px",
                              borderRadius: "0 4px 4px 0",
                              background: "#4D9BE8",
                            }}
                          />
                        )}
                      </div>
                    </div>

                    <span style={{ fontSize: "12px", color: "#9BA3AF" }}>{ins.n_days}</span>
                  </div>
                );
              })
            ) : (
              <div style={{ fontSize: "13px", color: "#9BA3AF", padding: "12px 0" }}>
                Zatím není dostatek dní pro statistické vyhodnocení.
              </div>
            )}

            <div style={{ fontSize: "12px", color: "#9BA3AF", paddingTop: "4px" }}>
              Rozdíl průměrné recovery další den s návykem a bez něj. Ukazuje se, až má návyk aspoň 5 dní s i bez.
            </div>
          </div>

          {/* Insufficient data card */}
          {data.insufficient && data.insufficient.length > 0 && (
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
              <div style={{ fontSize: "15px", fontWeight: 700 }}>Zatím málo dat</div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: "6px" }}>
                {data.insufficient.map((item, idx) => (
                  <span
                    key={idx}
                    style={{
                      fontSize: "13px",
                      padding: "6px 10px",
                      borderRadius: "999px",
                      background: "#1D2127",
                      color: "#C9CED6",
                    }}
                  >
                    {item.label} · {item.text}
                  </span>
                ))}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
