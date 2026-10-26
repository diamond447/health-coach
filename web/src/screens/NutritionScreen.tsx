import { useEffect, useState } from "preact/hooks";
import { apiFetch } from "../api";
import { EmptyState } from "../components/EmptyState";
import { Header } from "../components/Header";
import { RingDial } from "../components/RingDial";
import { Skeleton } from "../components/Skeleton";
import { foodColor, formatDateCzech, formatDecimal, formatNumber, formatTime } from "../helpers";
import { NutritionResponse } from "../types";

interface NutritionScreenProps {
  date: string;
  onDateChange: (date: string) => void;
}

// "B 29 g · S 70 g · T 12 g · V 8 g"; macros the entry does not know are left out.
function itemMacros(it: NutritionResponse["meals"][number]["items"][number]): string {
  return (
    [
      ["B", it.protein_g],
      ["S", it.carbs_g],
      ["T", it.fat_g],
      ["V", it.fiber_g],
    ] as const
  )
    .filter(([, g]) => g !== null)
    .map(([label, g]) => `${label} ${formatDecimal(g, 0)} g`)
    .join(" · ");
}

export function NutritionScreen({ date, onDateChange }: NutritionScreenProps) {
  const [data, setData] = useState<NutritionResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const loadData = async (isRef = false) => {
    if (isRef) setRefreshing(true);
    else setLoading(true);

    const res = await apiFetch<NutritionResponse>(`/api/nutrition?date=${encodeURIComponent(date)}`);
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
  const targetKcal = data?.target_kcal ?? 2400;
  const currentKcal = data?.kcal ?? 0;
  const remKcal = targetKcal - currentKcal;

  // Week chart geometry
  const maxKcal = Math.max(3000, targetKcal + 500, ...(data?.week.map((d) => d.kcal) || [3000]));
  const H = 100;
  const targetB = Math.round((targetKcal / maxKcal) * H);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
      <Header
        title={`Jídlo · ${dateFormatted}`}
        date={date}
        onDateChange={onDateChange}
        asOf={data?.as_of}
        onRefresh={() => loadData(true)}
        isRefreshing={refreshing}
      />

      {loading && !data ? (
        <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
          <Skeleton height={150} />
          <Skeleton height={180} />
          <Skeleton height={180} />
          <Skeleton height={200} />
        </div>
      ) : !data ? (
        <EmptyState
          message="Zatím žádná data o jídle"
          submessage="Pro tento den ještě nebyla zaznamenána žádná nutriční data."
        />
      ) : data.kcal === 0 && (!data.meals || data.meals.length === 0) ? (
        <EmptyState
          message="Zatím žádná zapsaná jídla"
          submessage="Zapisuješ v Google Health nebo přes kouče v Claude. Tady se data jen zobrazují."
        />
      ) : (
        <>
          {/* Ring dial & summary */}
          <div style={{ display: "flex", alignItems: "center", gap: "16px" }}>
            <RingDial
              value={currentKcal}
              max={targetKcal}
              size={132}
              strokeWidth={9}
              displayValue={formatNumber(currentKcal)}
              color={foodColor()}
              ariaLabel={`Příjem ${currentKcal} z ${targetKcal} kcal`}
              sublabel={`Z ${formatNumber(targetKcal)} KCAL`}
              sublabelColor="#FFC98A"
            />
            <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
              <div style={{ fontSize: "22px", fontWeight: 800 }}>
                {remKcal >= 0 ? `zbývá ${formatNumber(remKcal)} kcal` : `překročeno o ${formatNumber(-remKcal)} kcal`}
              </div>
              {data.phase && (
                <div style={{ fontSize: "14px", color: "#C9CED6" }}>
                  Fáze: {data.phase}
                  {data.weekly_rate_target_kg !== null &&
                    `, cíl ${formatDecimal(data.weekly_rate_target_kg, 1, true)} kg/týden`}
                </div>
              )}
              <div style={{ fontSize: "13px", color: "#9BA3AF" }}>
                Zapsáno {data.meals_count} {data.meals_count === 1 ? "jídlo" : data.meals_count < 5 ? "jídla" : "jídel"}
                {data.last_logged_time ? ` · poslední ${formatTime(data.last_logged_time)}` : ""}
              </div>
            </div>
          </div>

          {/* Macros card */}
          {data.macros && data.macros.length > 0 && (
            <div
              style={{
                background: "#16191E",
                borderRadius: "16px",
                padding: "16px",
                display: "flex",
                flexDirection: "column",
                gap: "12px",
              }}
            >
              <div style={{ fontSize: "15px", fontWeight: 700 }}>Makra</div>
              {data.macros.map((m, idx) => {
                const pct = m.target ? Math.min(100, Math.round((m.val / m.target) * 100)) : 0;
                return (
                  <div key={idx} style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
                    <div style={{ display: "flex", justifyContent: "space-between", fontSize: "14px" }}>
                      <span>{m.name}</span>
                      <span>
                        <span style={{ fontWeight: 700 }}>{formatNumber(m.val)}</span>
                        <span style={{ color: "#9BA3AF" }}> / {m.target} g</span>
                      </span>
                    </div>
                    <div style={{ height: "10px", borderRadius: "5px", background: "#23272E" }}>
                      <div
                        style={{
                          width: `${pct}%`,
                          height: "10px",
                          borderRadius: "5px",
                          background: m.color,
                        }}
                      />
                    </div>
                  </div>
                );
              })}
            </div>
          )}

          {/* Energy balance card */}
          {data.energy_balance && (
            <div
              style={{
                background: "#16191E",
                borderRadius: "16px",
                padding: "16px",
                display: "flex",
                flexDirection: "column",
                gap: "12px",
              }}
            >
              <div style={{ fontSize: "15px", fontWeight: 700 }}>Energetická bilance</div>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: "8px" }}>
                <div style={{ display: "flex", flexDirection: "column", gap: "2px" }}>
                  <div style={{ fontSize: "12px", color: "#9BA3AF" }}>Příjem</div>
                  <div style={{ fontSize: "18px", fontWeight: 700 }}>
                    {formatNumber(data.energy_balance.intake)}
                  </div>
                </div>
                <div style={{ display: "flex", flexDirection: "column", gap: "2px" }}>
                  <div style={{ fontSize: "12px", color: "#9BA3AF" }}>Výdej (TDEE)</div>
                  <div style={{ fontSize: "18px", fontWeight: 700 }}>
                    {data.energy_balance.tdee ? formatNumber(data.energy_balance.tdee) : "–"}
                  </div>
                </div>
                <div style={{ display: "flex", flexDirection: "column", gap: "2px" }}>
                  <div style={{ fontSize: "12px", color: "#9BA3AF" }}>Bilance</div>
                  <div
                    style={{
                      fontSize: "18px",
                      fontWeight: 700,
                      color:
                        (data.energy_balance.balance ?? 0) <= 0
                          ? "#5FE39E"
                          : "#FFB15C",
                    }}
                  >
                    {data.energy_balance.balance !== null
                      ? `${data.energy_balance.balance > 0 ? "+" : ""}${formatNumber(data.energy_balance.balance)}`
                      : "–"}
                  </div>
                </div>
              </div>

              {(data.energy_balance.mean_14_balance !== null ||
                data.energy_balance.expected_weekly_change !== null ||
                data.energy_balance.actual_weekly_change !== null) && (
                <div
                  style={{
                    display: "flex",
                    flexDirection: "column",
                    gap: "4px",
                    paddingTop: "10px",
                    borderTop: "1px solid #23272E",
                    fontSize: "13px",
                    color: "#C9CED6",
                  }}
                >
                  {data.energy_balance.mean_14_balance !== null && (
                    <div>
                      Za 14 dní Ø {formatNumber(data.energy_balance.mean_14_balance)} kcal/den
                      {data.energy_balance.expected_weekly_change !== null &&
                        ` → čekaná změna ${formatDecimal(data.energy_balance.expected_weekly_change, 2, true)} kg/týden`}
                    </div>
                  )}
                  {data.energy_balance.actual_weekly_change !== null && (
                    <div>
                      Skutečný trend váhy {formatDecimal(data.energy_balance.actual_weekly_change, 2, true)} kg/týden
                    </div>
                  )}
                </div>
              )}
            </div>
          )}

          {/* Meals list */}
          {data.meals && data.meals.length > 0 && (
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
              <div style={{ fontSize: "15px", fontWeight: 700, paddingBottom: "8px" }}>Jídla</div>
              {data.meals.map((meal, idx) => (
                <div
                  key={idx}
                  style={{
                    display: "flex",
                    flexDirection: "column",
                    gap: "4px",
                    padding: "10px 0",
                    borderTop: "1px solid #23272E",
                  }}
                >
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
                    <div style={{ fontSize: "14px", fontWeight: 700 }}>
                      {meal.name}{" "}
                      {meal.time && (
                        <span style={{ fontWeight: 400, color: "#9BA3AF" }}>
                          {formatTime(meal.time)}
                        </span>
                      )}
                    </div>
                    <div style={{ fontSize: "14px", fontWeight: 600 }}>{formatNumber(meal.kcal)} kcal</div>
                  </div>
                  {meal.items &&
                    meal.items.map((it, itemIdx) => (
                      <div
                        key={itemIdx}
                        style={{ display: "flex", flexDirection: "column", gap: "2px", fontSize: "13px" }}
                      >
                        <div style={{ display: "flex", justifyContent: "space-between", gap: "8px", color: "#C9CED6" }}>
                          <span>{it.name}</span>
                          <span style={{ color: "#9BA3AF", whiteSpace: "nowrap" }}>{formatNumber(it.kcal)} kcal</span>
                        </div>
                        <div style={{ fontSize: "12px", color: "#9BA3AF" }}>
                          {itemMacros(it)}
                        </div>
                      </div>
                    ))}
                </div>
              ))}
              <div style={{ fontSize: "12px", color: "#9BA3AF", paddingTop: "6px" }}>
                Zapisuješ v Google Health nebo přes kouče v Claude. Tady se jen zobrazuje.
              </div>
            </div>
          )}

          {/* Week calorie bars */}
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
                <div style={{ fontSize: "15px", fontWeight: 700 }}>Týden</div>
                <div style={{ fontSize: "13px", color: "#C9CED6" }}>
                  bílkoviny splněny {data.protein_hits_days} ze {data.week.length} dní
                </div>
              </div>

              <div
                style={{
                  position: "relative",
                  display: "grid",
                  gridTemplateColumns: "repeat(7, minmax(0, 1fr))",
                  gap: "10px",
                  alignItems: "end",
                  height: "100px",
                }}
              >
                <div
                  style={{
                    position: "absolute",
                    left: 0,
                    right: 0,
                    bottom: `${targetB}px`,
                    height: "2px",
                    background: "#FFB15C",
                    zIndex: 2,
                  }}
                />
                {data.week.map((d, idx) => {
                  const barH = Math.min(100, Math.round((d.kcal / maxKcal) * H));
                  const barColor = d.protein_hit ? "#FFB15C" : "#8A5A2B";

                  return (
                    <div
                      key={idx}
                      style={{
                        display: "flex",
                        flexDirection: "column",
                        justifyContent: "flex-end",
                        height: "100px",
                      }}
                    >
                      <div
                        style={{
                          height: `${barH}px`,
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
                {data.week.map((d, idx) => (
                  <span key={idx}>{d.weekday}</span>
                ))}
              </div>
              <div style={{ fontSize: "12px", color: "#9BA3AF" }}>
                Oranžová čára = cíl kcal · světlejší sloupec = splněné bílkoviny
              </div>
            </div>
          )}

          {/* Vitamíny a minerály card */}
          <div
            style={{
              background: "#16191E",
              borderRadius: "16px",
              padding: "16px",
              display: "flex",
              flexDirection: "column",
              gap: "12px",
            }}
          >
            <div style={{ fontSize: "15px", fontWeight: 700 }}>Vitamíny a minerály</div>

            {!data.micros || data.micros.length === 0 ? (
              <div style={{ fontSize: "13px", color: "#9BA3AF", lineHeight: 1.5 }}>
                Zatím žádná data o vitamínech a minerálech. Doplní se z Google Health u potravin, které je mají.
              </div>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
                {(
                  [
                    { key: "minerály", label: "Minerály" },
                    { key: "vitamíny", label: "Vitamíny" },
                    { key: "ostatní", label: "Ostatní" },
                  ] as const
                ).map((grp) => {
                  const grpMicros = data.micros.filter((m) => m.group === grp.key);
                  if (grpMicros.length === 0) return null;

                  return (
                    <div key={grp.key} style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
                      <div
                        style={{
                          display: "flex",
                          justifyContent: "space-between",
                          alignItems: "center",
                          fontSize: "12px",
                          fontWeight: 700,
                          color: "#9BA3AF",
                          textTransform: "uppercase",
                          letterSpacing: "0.5px",
                        }}
                      >
                        <span>{grp.label}</span>
                        <span style={{ fontSize: "11px", fontWeight: 500, textTransform: "none" }}>% DRH</span>
                      </div>

                      {grpMicros.map((m) => {
                        const hasRef = m.reference !== null && m.pct !== null;
                        let barColor = "#5A6270";
                        if (hasRef) {
                          if (m.kind === "target") {
                            barColor = m.pct! >= 100 ? foodColor() : "#5A6270";
                          } else if (m.kind === "limit") {
                            barColor = m.pct! > 100 ? "#EF4444" : "#5A6270";
                          }
                        }

                        const barWidth = hasRef ? Math.min(100, Math.max(0, m.pct!)) : 0;

                        return (
                          <div
                            key={m.key}
                            style={{
                              display: "grid",
                              gridTemplateColumns: "minmax(100px, 1fr) auto 70px 44px",
                              alignItems: "center",
                              gap: "8px",
                              fontSize: "13px",
                            }}
                          >
                            <span style={{ color: "#F0F2F5", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                              {m.name}
                            </span>
                            <span style={{ color: "#9BA3AF", textAlign: "right", whiteSpace: "nowrap" }}>
                              <span style={{ color: "#F0F2F5", fontWeight: 600 }}>
                                {m.amount < 1 && m.amount % 1 !== 0
                                  ? formatDecimal(m.amount, 2)
                                  : m.amount < 10 && m.amount % 1 !== 0
                                  ? formatDecimal(m.amount, 1)
                                  : formatNumber(m.amount)}
                              </span>{" "}
                              {m.unit}
                            </span>
                            <div
                              style={{
                                height: "6px",
                                borderRadius: "3px",
                                background: "#23272E",
                                overflow: "hidden",
                              }}
                            >
                              {hasRef && (
                                <div
                                  style={{
                                    width: `${barWidth}%`,
                                    height: "100%",
                                    borderRadius: "3px",
                                    background: barColor,
                                  }}
                                />
                              )}
                            </div>
                            <span
                              style={{
                                textAlign: "right",
                                fontSize: "12px",
                                color:
                                  hasRef && m.kind === "limit" && m.pct! > 100
                                    ? "#EF4444"
                                    : hasRef && m.kind === "target" && m.pct! >= 100
                                    ? foodColor()
                                    : "#9BA3AF",
                                whiteSpace: "nowrap",
                              }}
                            >
                              {hasRef ? `${m.pct} %` : "–"}
                            </span>
                          </div>
                        );
                      })}
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          <div style={{ fontSize: "12px", color: "#9BA3AF", padding: "0 4px" }}>
            Data z {data.micros_coverage?.entries_with ?? 0} z {data.micros_coverage?.entries_total ?? 0} záznamů · DRH = denní referenční hodnota EU
          </div>
        </>
      )}
    </div>
  );
}
