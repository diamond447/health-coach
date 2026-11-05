import { useEffect, useRef, useState } from "preact/hooks";
import { apiFetch, apiSend } from "../api";
import { EmptyState } from "../components/EmptyState";
import { Header } from "../components/Header";
import { Skeleton } from "../components/Skeleton";
import { addDays, formatDateCzech, formatTime } from "../helpers";
import { JournalEntry, JournalOption, JournalResponse } from "../types";

interface JournalScreenProps {
  date: string;
}

const SAVE_ERROR = "Nepodařilo se uložit, zkus to znovu";

/** "Dnes, čt 5. 11.", "Včera, st 4. 11." or "Út 3. 11.". */
function dayTitle(logDate: string, today: string): string {
  const formatted = formatDateCzech(logDate);
  if (logDate === today) return `Dnes, ${formatted}`;
  if (logDate === addDays(today, -1)) return `Včera, ${formatted}`;
  return formatted.charAt(0).toUpperCase() + formatted.slice(1);
}

function logHint(logDate: string, today: string): string {
  if (logDate === today) return "Klepnutím zapíšeš dnešní večer.";
  if (logDate === addDays(today, -1)) return "Klepnutím zapíšeš včerejší večer.";
  return `Klepnutím zapíšeš večer ${formatDateCzech(logDate)}`; // the date ends with a period
}

function DayArrow({
  label,
  path,
  disabled,
  onClick,
}: {
  label: string;
  path: string;
  disabled: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      disabled={disabled}
      onClick={onClick}
      style={{
        width: "44px",
        height: "44px",
        borderRadius: "22px",
        border: "none",
        background: "#1D2127",
        color: disabled ? "#5C636D" : "#F2F4F7",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        cursor: disabled ? "default" : "pointer",
        flexShrink: 0,
      }}
    >
      <svg
        width="20"
        height="20"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        stroke-width="2"
        stroke-linecap="round"
        stroke-linejoin="round"
        aria-hidden="true"
      >
        <path d={path} />
      </svg>
    </button>
  );
}

export function JournalScreen({ date }: JournalScreenProps) {
  const [data, setData] = useState<JournalResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  // The evening being loaded after a day switch; null once data shows it.
  const [pendingDate, setPendingDate] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saving, setSaving] = useState<Record<string, boolean>>({});
  const timersRef = useRef<Record<string, ReturnType<typeof setTimeout>>>({});
  const pendingSavesRef = useRef<Record<string, () => Promise<void>>>({});
  const seqRef = useRef<Record<string, number>>({});
  const inFlightRef = useRef<Record<string, Promise<unknown> | null>>({});
  const loadSeqRef = useRef(0);

  // logDate null loads the server's default, yesterday's evening.
  const loadData = async (logDate: string | null, isRef = false) => {
    const seq = ++loadSeqRef.current;
    if (isRef) setRefreshing(true);
    else setLoading(true);

    const query = logDate ? `&log_date=${logDate}` : "";
    const res = await apiFetch<JournalResponse>(`/api/journal?days=60${query}`);
    if (seq !== loadSeqRef.current) return; // a later switch or refresh owns the screen
    if (res.data) {
      setData(res.data);
    }
    setPendingDate(null);
    setLoading(false);
    setRefreshing(false);
  };

  // Stepper changes wait for a debounce; send them now so a day switch or leaving the
  // screen does not drop them.
  const flushPendingSaves = () => {
    for (const [behavior, save] of Object.entries(pendingSavesRef.current)) {
      clearTimeout(timersRef.current[behavior]);
      void save();
    }
  };

  useEffect(() => {
    loadData(null);
    return flushPendingSaves;
  }, [date]);

  const changeDay = (delta: number) => {
    if (!data) return;
    const next = addDays(pendingDate ?? data.log_date, delta);
    if (next < data.min_log_date || next > data.max_log_date) return;
    flushPendingSaves();
    setSaveError(null);
    setPendingDate(next);
    loadData(next);
  };

  // Changes the entries only while their evening is still the one on screen.
  const updateEntries = (logDate: string, change: (entries: JournalEntry[]) => JournalEntry[]) => {
    setData((current) =>
      current && current.log_date === logDate
        ? { ...current, entries: change(current.entries) }
        : current
    );
  };

  const mergeSuccessData = (current: JournalResponse | null, resData: JournalResponse, behavior: string) => {
    if (!current) return resData;
    if (current.log_date !== resData.log_date) return current; // saved an evening no longer shown
    const pendingBehaviors = new Set(
      Object.keys({ ...inFlightRef.current, ...timersRef.current }).filter(
        (b) => b !== behavior && (inFlightRef.current[b] || timersRef.current[b])
      )
    );
    if (pendingBehaviors.size === 0) return resData;
    const mergedEntries = resData.entries.filter((e) => !pendingBehaviors.has(e.behavior));
    for (const pb of pendingBehaviors) {
      const pendingEntry = current.entries.find((e) => e.behavior === pb);
      if (pendingEntry) mergedEntries.push(pendingEntry);
    }
    return { ...resData, entries: mergedEntries };
  };

  const handleToggle = async (opt: JournalOption) => {
    if (!data) return;
    const logDate = data.log_date;
    setSaveError(null);

    if (timersRef.current[opt.behavior]) {
      clearTimeout(timersRef.current[opt.behavior]);
      delete timersRef.current[opt.behavior];
      delete pendingSavesRef.current[opt.behavior];
    }

    // Toggle-off waits for an in-flight PUT if one is saving
    if (inFlightRef.current[opt.behavior]) {
      try {
        await inFlightRef.current[opt.behavior];
      } catch {
        // ignore in-flight error; toggle-off takes precedence
      }
    }

    const seq = (seqRef.current[opt.behavior] || 0) + 1;
    seqRef.current[opt.behavior] = seq;

    const prevEntry = data.entries.find((e) => e.behavior === opt.behavior);
    const wasActive = Boolean(prevEntry && prevEntry.active);
    const withoutThis = (entries: JournalEntry[]) =>
      entries.filter((e) => e.behavior !== opt.behavior);
    // Roll back ONLY this behavior
    const rollBack = () => {
      updateEntries(logDate, (entries) =>
        prevEntry ? [...withoutThis(entries), prevEntry] : withoutThis(entries)
      );
      setSaveError(SAVE_ERROR);
    };

    if (wasActive) {
      updateEntries(logDate, withoutThis);

      setSaving((s) => ({ ...s, [opt.behavior]: true }));
      const promise = apiSend(
        "DELETE",
        `/api/journal/entries?date=${logDate}&behavior=${opt.behavior}`
      );
      inFlightRef.current[opt.behavior] = promise;
      const res = await promise;
      inFlightRef.current[opt.behavior] = null;
      setSaving((s) => ({ ...s, [opt.behavior]: false }));

      if (seqRef.current[opt.behavior] !== seq) {
        return;
      }

      if (res.error && res.status !== 404) {
        rollBack();
      }
    } else {
      const initialAmount = opt.unit ? 1 : null;
      const newEntry: JournalEntry = {
        behavior: opt.behavior,
        name: opt.name,
        amount: initialAmount,
        note: null,
        active: true,
      };
      updateEntries(logDate, (entries) => [...withoutThis(entries), newEntry]);

      setSaving((s) => ({ ...s, [opt.behavior]: true }));
      const promise = apiSend<JournalResponse>("PUT", "/api/journal/entries", {
        date: logDate,
        behavior: opt.behavior,
        amount: initialAmount,
        note: null,
      });
      inFlightRef.current[opt.behavior] = promise;
      const res = await promise;
      inFlightRef.current[opt.behavior] = null;
      setSaving((s) => ({ ...s, [opt.behavior]: false }));

      if (seqRef.current[opt.behavior] !== seq) {
        return;
      }

      if (res.error || !res.data) {
        rollBack();
      } else {
        const resData = res.data;
        setData((current) => mergeSuccessData(current, resData, opt.behavior));
      }
    }
  };

  const handleStep = (opt: JournalOption, delta: number) => {
    if (!data) return;
    const logDate = data.log_date;
    setSaveError(null);

    const activeEntry = data.entries.find((e) => e.behavior === opt.behavior && e.active);
    if (!activeEntry) return;

    const currentAmount = activeEntry.amount ?? 1;
    const newAmount = Math.max(1, Math.round(currentAmount + delta));
    if (newAmount === currentAmount) return;

    const prevAmount = activeEntry.amount;
    const setAmount = (amount: number | null) =>
      updateEntries(logDate, (entries) =>
        entries.map((e) => (e.behavior === opt.behavior ? { ...e, amount } : e))
      );
    setAmount(newAmount);

    if (timersRef.current[opt.behavior]) {
      clearTimeout(timersRef.current[opt.behavior]);
    }

    const save = async () => {
      delete timersRef.current[opt.behavior];
      delete pendingSavesRef.current[opt.behavior];
      if (inFlightRef.current[opt.behavior]) {
        try {
          await inFlightRef.current[opt.behavior];
        } catch {
          // ignore
        }
      }

      const seq = (seqRef.current[opt.behavior] || 0) + 1;
      seqRef.current[opt.behavior] = seq;

      setSaving((s) => ({ ...s, [opt.behavior]: true }));
      const promise = apiSend<JournalResponse>("PUT", "/api/journal/entries", {
        date: logDate,
        behavior: opt.behavior,
        amount: newAmount,
        note: null,
      });
      inFlightRef.current[opt.behavior] = promise;
      const res = await promise;
      inFlightRef.current[opt.behavior] = null;
      setSaving((s) => ({ ...s, [opt.behavior]: false }));

      if (seqRef.current[opt.behavior] !== seq) {
        return;
      }

      if (res.error || !res.data) {
        // Roll back ONLY this behavior's amount
        setAmount(prevAmount);
        setSaveError(SAVE_ERROR);
      } else {
        const resData = res.data;
        setData((current) => mergeSuccessData(current, resData, opt.behavior));
      }
    };
    pendingSavesRef.current[opt.behavior] = save;
    timersRef.current[opt.behavior] = setTimeout(save, 600);
  };

  const shownDate = pendingDate ?? data?.log_date ?? "";
  const switching = pendingDate !== null;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
      <Header
        title="Deník · vliv na recovery"
        backHref="/trendy"
        backLabel="Zpět na Trendy"
        asOf={data?.as_of}
        onRefresh={() => loadData(pendingDate ?? data?.log_date ?? null, true)}
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
          {/* Evening card: one day of the edit window, yesterday by default */}
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
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: "8px" }}>
              <DayArrow
                label="Předchozí den"
                path="M15 18l-6-6 6-6"
                disabled={shownDate <= data.min_log_date}
                onClick={() => changeDay(-1)}
              />
              <div
                style={{
                  display: "flex",
                  flexDirection: "column",
                  alignItems: "center",
                  gap: "2px",
                  minWidth: 0,
                }}
              >
                <div style={{ fontSize: "15px", fontWeight: 700 }}>
                  {dayTitle(shownDate, data.max_log_date)}
                </div>
                {data.logged_time && !switching && (
                  <div style={{ fontSize: "12px", color: "#9BA3AF" }}>
                    zapsal kouč {formatTime(data.logged_time)}
                  </div>
                )}
              </div>
              <DayArrow
                label="Další den"
                path="M9 18l6-6-6-6"
                disabled={shownDate >= data.max_log_date}
                onClick={() => changeDay(1)}
              />
            </div>

            <div aria-busy={switching} style={{ opacity: switching ? 0.5 : 1 }}>
              {data.can_write ? (
                <div style={{ display: "flex", flexWrap: "wrap", gap: "8px" }}>
                  {data.options.map((opt) => {
                    const activeEntry = data.entries.find(
                      (e) => e.behavior === opt.behavior && e.active
                    );
                    const isActive = Boolean(activeEntry);
                    const amount = activeEntry?.amount ?? 1;

                    // While another day loads, the chips still show this one: lock them.
                    const isSaving = Boolean(saving[opt.behavior]) || switching;

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
                            disabled={switching}
                            onClick={() => handleToggle(opt)}
                            style={{
                              background: "transparent",
                              border: "none",
                              color: "#CFE4FF",
                              fontSize: "13px",
                              fontWeight: 600,
                              cursor: switching ? "default" : "pointer",
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
                              disabled={amount <= 1 || isSaving}
                              onClick={() => handleStep(opt, -1)}
                              style={{
                                background: "rgba(255, 255, 255, 0.08)",
                                border: "none",
                                color: amount <= 1 || isSaving ? "#5A6270" : "#CFE4FF",
                                borderRadius: "999px",
                                width: "44px",
                                height: "44px",
                                minWidth: "44px",
                                minHeight: "44px",
                                fontSize: "16px",
                                cursor: amount <= 1 || isSaving ? "default" : "pointer",
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
                              disabled={isSaving}
                              onClick={() => handleStep(opt, 1)}
                              style={{
                                background: "rgba(255, 255, 255, 0.08)",
                                border: "none",
                                color: isSaving ? "#5A6270" : "#CFE4FF",
                                borderRadius: "999px",
                                width: "44px",
                                height: "44px",
                                minWidth: "44px",
                                minHeight: "44px",
                                fontSize: "16px",
                                cursor: isSaving ? "default" : "pointer",
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
                        disabled={isSaving}
                        onClick={() => handleToggle(opt)}
                        style={{
                          fontSize: "13px",
                          fontWeight: isActive ? 600 : 400,
                          padding: "8px 14px",
                          minHeight: "44px",
                          minWidth: "44px",
                          borderRadius: "999px",
                          border: "none",
                          cursor: isSaving ? "default" : "pointer",
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
              ) : data.entries.length > 0 ? (
                <div style={{ display: "flex", flexWrap: "wrap", gap: "6px" }}>
                  {data.entries.map((e, idx) => (
                    <span
                      key={idx}
                      style={{
                        fontSize: "13px",
                        padding: "6px 10px",
                        borderRadius: "999px",
                        background: e.active ? "#1F3550" : "#1D2127",
                        color: e.active ? "#CFE4FF" : "#9BA3AF",
                      }}
                    >
                      {e.name}
                    </span>
                  ))}
                </div>
              ) : (
                <div style={{ fontSize: "13px", color: "#9BA3AF" }}>
                  Žádné návyky pro tento den nebyly zapsány.
                </div>
              )}
            </div>

            {saveError && (
              <div style={{ fontSize: "12px", color: "#FF6B6B" }}>
                {saveError}
              </div>
            )}

            <div style={{ fontSize: "12px", color: "#9BA3AF" }}>
              {logHint(shownDate, data.max_log_date)} Jiné věci (třeba „kafe v 15:00“) napiš koučovi v Claude.
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
