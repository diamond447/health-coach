import { useEffect, useRef, useState } from "preact/hooks";
import { apiFetch, apiSend } from "../api";
import { EmptyState } from "../components/EmptyState";
import { Header } from "../components/Header";
import { Skeleton } from "../components/Skeleton";
import { formatDateCzech, formatTime } from "../helpers";
import { JournalOption, JournalResponse } from "../types";

interface JournalScreenProps {
  date: string;
}

export function JournalScreen({ date }: JournalScreenProps) {
  const [data, setData] = useState<JournalResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const timersRef = useRef<Record<string, ReturnType<typeof setTimeout>>>({});
  const lastSavedDataRef = useRef<JournalResponse | null>(null);

  const loadData = async (isRef = false) => {
    if (isRef) setRefreshing(true);
    else setLoading(true);

    const res = await apiFetch<JournalResponse>(`/api/journal?days=60`);
    if (res.data) {
      setData(res.data);
      lastSavedDataRef.current = res.data;
    }
    setLoading(false);
    setRefreshing(false);
  };

  useEffect(() => {
    loadData();
    return () => {
      Object.values(timersRef.current).forEach((t) => clearTimeout(t));
      timersRef.current = {};
    };
  }, [date]);

  const handleToggle = async (opt: JournalOption) => {
    if (!data) return;
    setSaveError(null);

    if (timersRef.current[opt.behavior]) {
      clearTimeout(timersRef.current[opt.behavior]);
      delete timersRef.current[opt.behavior];
    }

    const prevData = data;
    const activeEntry = data.yesterday.find((y) => y.behavior === opt.behavior && y.active);
    const wasActive = Boolean(activeEntry);

    if (wasActive) {
      const updatedYesterday = data.yesterday.filter((y) => y.behavior !== opt.behavior);
      setData({ ...data, yesterday: updatedYesterday });

      const res = await apiSend(
        "DELETE",
        `/api/journal/entries?date=${data.log_date}&behavior=${opt.behavior}`
      );
      if (res.error) {
        setData(prevData);
        setSaveError("Nepodařilo se uložit, zkus to znovu");
      } else {
        lastSavedDataRef.current = { ...data, yesterday: updatedYesterday };
      }
    } else {
      const initialAmount = opt.unit ? 1 : null;
      const newEntry = {
        behavior: opt.behavior,
        name: opt.name,
        amount: initialAmount,
        note: null,
        active: true,
      };
      const updatedYesterday = [
        ...data.yesterday.filter((y) => y.behavior !== opt.behavior),
        newEntry,
      ];
      setData({ ...data, yesterday: updatedYesterday });

      const res = await apiSend<JournalResponse>("PUT", "/api/journal/entries", {
        date: data.log_date,
        behavior: opt.behavior,
        amount: initialAmount,
        note: null,
      });
      if (res.error || !res.data) {
        setData(prevData);
        setSaveError("Nepodařilo se uložit, zkus to znovu");
      } else {
        setData(res.data);
        lastSavedDataRef.current = res.data;
      }
    }
  };

  const handleStep = (opt: JournalOption, delta: number) => {
    if (!data) return;
    setSaveError(null);

    const activeEntry = data.yesterday.find((y) => y.behavior === opt.behavior && y.active);
    if (!activeEntry) return;

    const currentAmount = activeEntry.amount ?? 1;
    const newAmount = Math.max(1, Math.round(currentAmount + delta));
    if (newAmount === currentAmount) return;

    const prevData = data;
    const updatedYesterday = data.yesterday.map((y) =>
      y.behavior === opt.behavior ? { ...y, amount: newAmount } : y
    );
    setData({ ...data, yesterday: updatedYesterday });

    if (timersRef.current[opt.behavior]) {
      clearTimeout(timersRef.current[opt.behavior]);
    }

    timersRef.current[opt.behavior] = setTimeout(async () => {
      delete timersRef.current[opt.behavior];
      const res = await apiSend<JournalResponse>("PUT", "/api/journal/entries", {
        date: data.log_date,
        behavior: opt.behavior,
        amount: newAmount,
        note: null,
      });
      if (res.error || !res.data) {
        setData(prevData);
        setSaveError("Nepodařilo se uložit, zkus to znovu");
      } else {
        setData(res.data);
        lastSavedDataRef.current = res.data;
      }
    }, 600);
  };

  const yesterdayFormatted = data?.yesterday_date ? formatDateCzech(data.yesterday_date) : "";

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
      <Header
        title="Deník · vliv na recovery"
        backHref="/trendy"
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

            {data.can_write ? (
              <div style={{ display: "flex", flexWrap: "wrap", gap: "8px" }}>
                {data.options.map((opt) => {
                  const activeEntry = data.yesterday.find(
                    (y) => y.behavior === opt.behavior && y.active
                  );
                  const isActive = Boolean(activeEntry);
                  const amount = activeEntry?.amount ?? 1;

                  if (isActive && opt.unit) {
                    return (
                      <div
                        key={opt.behavior}
                        style={{
                          display: "inline-flex",
                          alignItems: "center",
                          background: "#1F3550",
                          color: "#CFE4FF",
                          borderRadius: "999px",
                          padding: "2px 4px 2px 12px",
                          minHeight: "44px",
                          gap: "6px",
                        }}
                      >
                        <button
                          type="button"
                          aria-pressed={true}
                          onClick={() => handleToggle(opt)}
                          style={{
                            background: "transparent",
                            border: "none",
                            color: "#CFE4FF",
                            fontSize: "13px",
                            fontWeight: 600,
                            cursor: "pointer",
                            padding: "0 4px 0 0",
                            minHeight: "44px",
                            minWidth: "44px",
                            display: "inline-flex",
                            alignItems: "center",
                          }}
                        >
                          {opt.name}
                        </button>
                        <div style={{ display: "inline-flex", alignItems: "center", gap: "2px" }}>
                          <button
                            type="button"
                            aria-label={`Snížit ${opt.name}`}
                            disabled={amount <= 1}
                            onClick={() => handleStep(opt, -1)}
                            style={{
                              background: "rgba(255, 255, 255, 0.08)",
                              border: "none",
                              color: amount <= 1 ? "#5A6270" : "#CFE4FF",
                              borderRadius: "999px",
                              width: "44px",
                              height: "44px",
                              minWidth: "44px",
                              minHeight: "44px",
                              fontSize: "16px",
                              cursor: amount <= 1 ? "default" : "pointer",
                              display: "inline-flex",
                              alignItems: "center",
                              justifyContent: "center",
                            }}
                          >
                            −
                          </button>
                          <span
                            style={{
                              fontSize: "13px",
                              fontWeight: 700,
                              padding: "0 4px",
                              whiteSpace: "nowrap",
                            }}
                          >
                            {amount} {opt.unit}
                          </span>
                          <button
                            type="button"
                            aria-label={`Zvýšit ${opt.name}`}
                            onClick={() => handleStep(opt, 1)}
                            style={{
                              background: "rgba(255, 255, 255, 0.08)",
                              border: "none",
                              color: "#CFE4FF",
                              borderRadius: "999px",
                              width: "44px",
                              height: "44px",
                              minWidth: "44px",
                              minHeight: "44px",
                              fontSize: "16px",
                              cursor: "pointer",
                              display: "inline-flex",
                              alignItems: "center",
                              justifyContent: "center",
                            }}
                          >
                            +
                          </button>
                        </div>
                      </div>
                    );
                  }

                  return (
                    <button
                      key={opt.behavior}
                      type="button"
                      aria-pressed={isActive}
                      onClick={() => handleToggle(opt)}
                      style={{
                        fontSize: "13px",
                        fontWeight: isActive ? 600 : 400,
                        padding: "8px 14px",
                        minHeight: "44px",
                        minWidth: "44px",
                        borderRadius: "999px",
                        border: "none",
                        cursor: "pointer",
                        background: isActive ? "#1F3550" : "#1D2127",
                        color: isActive ? "#CFE4FF" : "#9BA3AF",
                        display: "inline-flex",
                        alignItems: "center",
                        justifyContent: "center",
                      }}
                    >
                      {opt.name}
                    </button>
                  );
                })}
              </div>
            ) : data.yesterday && data.yesterday.length > 0 ? (
              <div style={{ display: "flex", flexWrap: "wrap", gap: "6px" }}>
                {data.yesterday.map((y, idx) => (
                  <span
                    key={idx}
                    style={{
                      fontSize: "13px",
                      padding: "6px 10px",
                      borderRadius: "999px",
                      background: y.active ? "#1F3550" : "#1D2127",
                      color: y.active ? "#CFE4FF" : "#9BA3AF",
                    }}
                  >
                    {y.name}
                  </span>
                ))}
              </div>
            ) : (
              <div style={{ fontSize: "13px", color: "#9BA3AF" }}>
                Žádné návyky pro včerejší den nebyly zapsány.
              </div>
            )}

            {saveError && (
              <div style={{ fontSize: "12px", color: "#FF6B6B" }}>
                {saveError}
              </div>
            )}

            <div style={{ fontSize: "12px", color: "#9BA3AF" }}>
              Klepnutím zapíšeš včerejší večer. Jiné věci (třeba „kafe v 15:00“) napiš koučovi v Claude.
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
                const diff = ins.difference_pp;
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
                      <span style={{ fontSize: "14px" }}>{ins.name}</span>
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

                    <span style={{ fontSize: "12px", color: "#9BA3AF" }}>
                      {ins.with_count} dní s · {ins.without_count} bez
                    </span>
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
                    {item.name} · {item.with_count} s / {item.without_count} bez
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
