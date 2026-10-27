import { addDays, formatDateCzech, formatTime, isToday } from "../helpers";

interface HeaderProps {
  title?: string;
  date?: string;
  onDateChange?: (newDate: string) => void;
  backHref?: string;
  backLabel?: string;
  asOf?: string | null;
  onRefresh?: () => void;
  isRefreshing?: boolean;
}

export function Header({
  title,
  date,
  onDateChange,
  backHref,
  backLabel = "Zpět",
  asOf,
  onRefresh,
  isRefreshing,
}: HeaderProps) {
  const syncTime = asOf ? formatTime(asOf) : null;
  const isCurrentDayToday = date ? isToday(date) : true;

  if (backHref) {
    return (
      <header
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          minHeight: "44px",
          gap: "8px",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: "8px", flexGrow: 1 }}>
          <a
            href={backHref}
            aria-label={backLabel}
            style={{
              width: "44px",
              height: "44px",
              borderRadius: "22px",
              background: "#16191E",
              color: "#F2F4F7",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              textDecoration: "none",
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
              <path d="M15 18l-6-6 6-6" />
            </svg>
          </a>
          <div style={{ display: "flex", flexDirection: "column" }}>
            <h1 style={{ fontSize: "17px", fontWeight: 700, margin: 0, color: "#F2F4F7" }}>{title}</h1>
            {syncTime && (
              <span style={{ fontSize: "12px", color: "#9BA3AF" }}>Synchronizováno v {syncTime}</span>
            )}
          </div>
        </div>
        {onRefresh && (
          <button
            type="button"
            onClick={onRefresh}
            aria-label="Aktualizovat data"
            style={{
              width: "44px",
              height: "44px",
              borderRadius: "22px",
              border: "none",
              background: "#16191E",
              color: "#F2F4F7",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              cursor: "pointer",
              flexShrink: 0,
            }}
          >
            <svg
              width="18"
              height="18"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="2"
              stroke-linecap="round"
              stroke-linejoin="round"
              aria-hidden="true"
              style={{
                animation: isRefreshing ? "spin 1s linear infinite" : "none",
              }}
            >
              <path d="M21.5 2v6h-6M2.5 22v-6h6M2 11.5a10 10 0 0 1 18.8-4.3M22 12.5a10 10 0 0 1-18.8 4.2" />
            </svg>
          </button>
        )}
      </header>
    );
  }

  // Date navigation header
  const formattedDate = date ? formatDateCzech(date) : "";
  const headerTitle = title || (isCurrentDayToday ? `Dnes · ${formattedDate}` : formattedDate);

  return (
    <header
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        minHeight: "44px",
        gap: "8px",
      }}
    >
      <button
        type="button"
        onClick={() => date && onDateChange?.(addDays(date, -1))}
        aria-label="Předchozí den"
        style={{
          width: "44px",
          height: "44px",
          borderRadius: "22px",
          border: "none",
          background: "#16191E",
          color: "#F2F4F7",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          cursor: "pointer",
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
          <path d="M15 18l-6-6 6-6" />
        </svg>
      </button>

      <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: "2px" }}>
        <h1 style={{ fontSize: "17px", fontWeight: 700, margin: 0, textAlign: "center", color: "#F2F4F7" }}>
          {headerTitle}
        </h1>
        <span style={{ fontSize: "12px", color: "#9BA3AF" }}>
          {syncTime ? `Synchronizováno v ${syncTime}` : "Synchronizováno"}
        </span>
      </div>

      <div style={{ display: "flex", alignItems: "center", gap: "4px" }}>
        <button
          type="button"
          onClick={() => date && onDateChange?.(addDays(date, 1))}
          disabled={isCurrentDayToday}
          aria-label="Další den"
          style={{
            width: "44px",
            height: "44px",
            borderRadius: "22px",
            border: "none",
            background: "#16191E",
            color: isCurrentDayToday ? "#5C636D" : "#F2F4F7",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            cursor: isCurrentDayToday ? "default" : "pointer",
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
            <path d="M9 18l6-6-6-6" />
          </svg>
        </button>

        {onRefresh && (
          <button
            type="button"
            onClick={onRefresh}
            aria-label="Aktualizovat data"
            style={{
              width: "44px",
              height: "44px",
              borderRadius: "22px",
              border: "none",
              background: "#16191E",
              color: "#F2F4F7",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              cursor: "pointer",
              flexShrink: 0,
            }}
          >
            <svg
              width="18"
              height="18"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="2"
              stroke-linecap="round"
              stroke-linejoin="round"
              aria-hidden="true"
              style={{
                animation: isRefreshing ? "spin 1s linear infinite" : "none",
              }}
            >
              <path d="M21.5 2v6h-6M2.5 22v-6h6M2 11.5a10 10 0 0 1 18.8-4.3M22 12.5a10 10 0 0 1-18.8 4.2" />
            </svg>
          </button>
        )}
      </div>
    </header>
  );
}
