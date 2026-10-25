interface EmptyStateProps {
  message: string;
  submessage?: string;
}

export function EmptyState({ message, submessage }: EmptyStateProps) {
  return (
    <div
      style={{
        background: "#16191E",
        borderRadius: "16px",
        padding: "24px 16px",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        gap: "6px",
        textAlign: "center",
        minHeight: "120px",
      }}
    >
      <div style={{ fontSize: "15px", fontWeight: 600, color: "#C9CED6" }}>{message}</div>
      {submessage && (
        <div style={{ fontSize: "13px", color: "#9BA3AF", maxWidth: "280px" }}>{submessage}</div>
      )}
    </div>
  );
}
