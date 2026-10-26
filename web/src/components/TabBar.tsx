interface TabBarProps {
  currentPath: string;
  date?: string;
}

export function TabBar({ currentPath, date }: TabBarProps) {
  const query = date ? `?date=${encodeURIComponent(date)}` : "";

  const tabs = [
    {
      id: "today",
      href: `/${query}`,
      label: "Dnes",
      isActive: currentPath === "/",
      icon: (
        <svg
          width="24"
          height="24"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <circle cx="12" cy="12" r="9" />
          <path d="M12 7v5l3 2" />
        </svg>
      ),
    },
    {
      id: "sleep",
      href: `/spanek${query}`,
      label: "Spánek",
      isActive: currentPath === "/spanek",
      icon: (
        <svg
          width="24"
          height="24"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z" />
        </svg>
      ),
    },
    {
      id: "strain",
      href: `/strain${query}`,
      label: "Strain",
      isActive: currentPath === "/strain",
      icon: (
        <svg
          width="24"
          height="24"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <path d="M3 12h4l3-8 4 16 3-8h4" />
        </svg>
      ),
    },
    {
      id: "nutrition",
      href: `/jidlo${query}`,
      label: "Jídlo",
      isActive: currentPath === "/jidlo",
      icon: (
        <svg
          width="24"
          height="24"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <path d="M7 3v8M5 3v5a2 2 0 0 0 4 0V3M7 11v10M17 21V3c-2 1-3 4-3 7h3" />
        </svg>
      ),
    },
    {
      id: "trends",
      href: `/trendy${query}`,
      label: "Trendy",
      isActive:
        currentPath === "/trendy" ||
        currentPath === "/kalendar" ||
        currentPath === "/denik" ||
        currentPath === "/prehled",
      icon: (
        <svg
          width="24"
          height="24"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <path d="M4 19V5M4 19h16M8 15l4-4 3 3 5-6" />
        </svg>
      ),
    },
  ];

  return (
    <nav
      aria-label="Hlavní navigace"
      style={{
        // Fixed, not sticky: sticky breaks in iOS Safari because the body clips overflow-x.
        position: "fixed",
        bottom: 0,
        left: 0,
        right: 0,
        width: "100%",
        maxWidth: "480px",
        margin: "0 auto",
        background: "#111317",
        borderTop: "1px solid #23272E",
        padding: "6px 8px max(16px, env(safe-area-inset-bottom, 16px)) 8px",
        display: "grid",
        gridTemplateColumns: "repeat(5, minmax(0, 1fr))",
        boxSizing: "border-box",
        zIndex: 50,
      }}
    >
      {tabs.map((tab) => (
        <a
          key={tab.id}
          href={tab.href}
          aria-current={tab.isActive ? "page" : undefined}
          style={{
            textDecoration: "none",
            color: tab.isActive ? "#F2F4F7" : "#8A929D",
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            gap: "4px",
            minHeight: "48px",
            justifyContent: "center",
          }}
        >
          {tab.icon}
          <span style={{ fontSize: "11px", fontWeight: 600 }}>{tab.label}</span>
        </a>
      ))}
    </nav>
  );
}
