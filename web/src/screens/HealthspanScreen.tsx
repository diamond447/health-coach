import { useEffect, useState } from "preact/hooks";
import { apiFetch } from "../api";
import { EmptyState } from "../components/EmptyState";
import { Header } from "../components/Header";
import { Skeleton } from "../components/Skeleton";
import {
  formatDecimal,
  formatFactorEffect,
  formatFactorValue,
  formatPace,
} from "../helpers";
import { HealthspanResponse } from "../types";

interface HealthspanScreenProps {
  date?: string;
}

export function HealthspanScreen({ date }: HealthspanScreenProps) {
  const [data, setData] = useState<HealthspanResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const loadData = async (isRef = false) => {
    if (isRef) setRefreshing(true);
    else setLoading(true);

    const res = await apiFetch<HealthspanResponse>("/api/healthspan?weeks=26");
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
  const latest = data?.latest;

  // Headline: the biological age ("22,3 roku") once the birth year is known, else
  // only the difference to the real age ("+2,3 roku"). Decimals take "roku" in Czech.
  let deltaStr = "—";
  let deltaUnit = "";
  let ageSubtitle = "oproti skutečnému věku";
  const delta = latest?.delta_years ?? null;
  if (latest?.biological_age !== null && latest?.biological_age !== undefined && delta !== null) {
    deltaStr = formatDecimal(latest.biological_age, 1);
    deltaUnit = "roku";
    const diff = formatDecimal(Math.abs(delta), 1);
    ageSubtitle =
      delta > 0
        ? `o ${diff} roku víc než tvůj věk ${latest.age}`
        : delta < 0
          ? `o ${diff} roku míň než tvůj věk ${latest.age}`
          : `stejně jako tvůj věk ${latest.age}`;
  } else if (delta !== null) {
    deltaStr = formatDecimal(delta, 1, true);
    deltaUnit = "roku";
    ageSubtitle = "oproti skutečnému věku (kouč zatím nezná tvůj rok narození)";
  }

  const paceFormatted = formatPace(latest?.pace);
  const factorsWithDataCount = latest?.factors_with_data ?? 0;
  const totalFactorsCount = latest?.factors?.length ?? 9;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
      <Header
        title="Healthspan"
        backHref={`/trendy${query}`}
        backLabel="Zpět na Trendy"
        asOf={data?.as_of}
        onRefresh={() => loadData(true)}
        isRefreshing={refreshing}
      />

      {loading && !data ? (
        <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
          <Skeleton height={180} />
          <Skeleton height={420} />
          <Skeleton height={60} />
        </div>
      ) : !data || !data.has_enough_data || !latest ? (
        <EmptyState
          message="Healthspan zatím nemá dost dat"
          submessage="Pro výpočet biologického věku jsou potřeba alespoň 4 týdny záznamů."
        />
      ) : (
        <>
          {/* Main Card: Biologický věk */}
          <div
            style={{
              background: "#16191E",
              borderRadius: "16px",
              padding: "20px 16px",
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              gap: "8px",
            }}
          >
            <div
              style={{
                fontSize: "12px",
                fontWeight: 600,
                letterSpacing: "0.08em",
                color: "#9BA3AF",
              }}
            >
              BIOLOGICKÝ VĚK
            </div>
            <div
              style={{
                fontSize: "52px",
                fontWeight: 800,
                lineHeight: 1,
                fontVariantNumeric: "tabular-nums",
              }}
            >
              {deltaStr}{" "}
              {deltaUnit && (
                <span style={{ fontSize: "20px", fontWeight: 700 }}>
                  {deltaUnit}
                </span>
              )}
            </div>
            <div style={{ fontSize: "14px", color: "#C9CED6" }}>
              {ageSubtitle}
            </div>
            <div style={{ display: "flex", gap: "24px", paddingTop: "8px" }}>
              <div
                style={{
                  display: "flex",
                  flexDirection: "column",
                  alignItems: "center",
                  gap: "2px",
                }}
              >
                <div
                  style={{
                    fontSize: "20px",
                    fontWeight: 700,
                    color: "#7DB8FF",
                  }}
                >
                  {paceFormatted}
                </div>
                <div style={{ fontSize: "12px", color: "#9BA3AF" }}>
                  tempo stárnutí
                </div>
              </div>
              <div
                style={{
                  display: "flex",
                  flexDirection: "column",
                  alignItems: "center",
                  gap: "2px",
                }}
              >
                <div style={{ fontSize: "20px", fontWeight: 700 }}>
                  {factorsWithDataCount} z {totalFactorsCount}
                </div>
                <div style={{ fontSize: "12px", color: "#9BA3AF" }}>
                  signálů s daty
                </div>
              </div>
            </div>
          </div>

          {/* Factor list card */}
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
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "baseline",
                paddingBottom: "6px",
              }}
            >
              <div style={{ fontSize: "15px", fontWeight: 700 }}>
                Co tě omlazuje a co stárne
              </div>
              <div style={{ fontSize: "12px", color: "#9BA3AF" }}>
                6 měsíců
              </div>
            </div>

            {latest.factors.map((f) => {
              const eff = formatFactorEffect(f.has_data ? f.years : null);
              const valStr = formatFactorValue(f.key, f.has_data ? f.value : null, f.unit);
              const goalStr = f.has_data ? f.goal : (f.key === "vo2max" ? "—" : f.goal);

              return (
                <div
                  key={f.key}
                  style={{
                    display: "grid",
                    gridTemplateColumns: "minmax(0, 1fr) auto",
                    gap: "8px",
                    alignItems: "center",
                    minHeight: "48px",
                    borderTop: "1px solid #23272E",
                  }}
                >
                  <div
                    style={{
                      display: "flex",
                      flexDirection: "column",
                      gap: "2px",
                    }}
                  >
                    <span style={{ fontSize: "14px" }}>{f.name}</span>
                    <span style={{ fontSize: "12px", color: "#9BA3AF" }}>
                      {valStr} · cíl {goalStr}
                    </span>
                  </div>
                  <span
                    style={{
                      fontSize: "14px",
                      fontWeight: 700,
                      color: eff.color,
                      fontVariantNumeric: "tabular-nums",
                    }}
                  >
                    {eff.text}
                  </span>
                </div>
              );
            })}
          </div>

          {/* Disclaimer footer */}
          <div
            style={{
              fontSize: "12px",
              color: "#9BA3AF",
              padding: "0 4px",
              lineHeight: 1.4,
            }}
          >
            Přepočítává se jednou týdně. Je to odhad podle zveřejněných studií, ne
            lékařské měření. VO2max se začne počítat, až hodinky pošlou první hodnotu
            (po prvních bězích).
          </div>
        </>
      )}
    </div>
  );
}
