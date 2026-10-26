import { ComponentChildren } from "preact";
import { useEffect, useErrorBoundary } from "preact/hooks";
import { EmptyState } from "./EmptyState";

interface ScreenBoundaryProps {
  /** Changes on navigation, which clears a previous error. */
  resetKey: string;
  children: ComponentChildren;
}

/**
 * Catches a render error in one screen, so the tab bar and the other screens keep working
 * instead of the whole app freezing.
 */
export function ScreenBoundary({ resetKey, children }: ScreenBoundaryProps) {
  const [error, resetError] = useErrorBoundary((err) => console.error(err));

  useEffect(() => {
    if (error) resetError();
  }, [resetKey]);

  if (error) {
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
        <EmptyState
          message="Tuhle obrazovku se nepodařilo zobrazit"
          submessage="Ostatní části aplikace fungují dál."
        />
        <button
          type="button"
          onClick={resetError}
          style={{
            minHeight: "44px",
            borderRadius: "12px",
            border: "none",
            background: "#23272E",
            color: "#F2F4F7",
            fontSize: "15px",
            fontWeight: 600,
          }}
        >
          Zkusit znovu
        </button>
      </div>
    );
  }
  return <>{children}</>;
}
