export function SessionExpiryBanner() {
  return (
    <div
      role="alert"
      style={{
        position: "sticky",
        top: 0,
        zIndex: 100,
        background: "#FF5A5F",
        color: "#FFFFFF",
        padding: "12px 16px",
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        gap: "12px",
        boxShadow: "0 2px 8px rgba(0,0,0,0.4)",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
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
          <circle cx="12" cy="12" r="10" />
          <line x1="12" y1="8" x2="12" y2="12" />
          <line x1="12" y1="16" x2="12.01" y2="16" />
        </svg>
        <span style={{ fontSize: "14px", fontWeight: 600 }}>Přihlášení vypršelo</span>
      </div>
      <button
        type="button"
        onClick={() => window.location.reload()}
        style={{
          background: "#FFFFFF",
          color: "#0B0D10",
          border: "none",
          borderRadius: "8px",
          padding: "8px 14px",
          fontSize: "13px",
          fontWeight: 700,
          cursor: "pointer",
          minHeight: "44px",
        }}
      >
        Znovu načíst
      </button>
    </div>
  );
}
