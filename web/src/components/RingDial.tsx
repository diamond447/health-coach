import { ringDash } from "../helpers";

interface RingDialProps {
  value: number | null | undefined;
  max: number;
  size?: number; // default 108
  strokeWidth?: number; // default 10
  color: string;
  bgStroke?: string;
  displayValue?: string;
  unit?: string;
  sublabel?: string;
  sublabelColor?: string;
  ariaLabel: string;
}

export function RingDial({
  value,
  max,
  size = 108,
  strokeWidth = 10,
  color,
  bgStroke = "#23272E",
  displayValue,
  unit,
  sublabel,
  sublabelColor,
  ariaLabel,
}: RingDialProps) {
  const radius = 60 - strokeWidth / 2;
  const dash = value !== null && value !== undefined ? ringDash(value, max, radius) : `0 ${2 * Math.PI * radius}`;
  const shownVal = displayValue !== undefined ? displayValue : value !== null && value !== undefined ? Math.round(value).toString() : "–";

  const isLarge = size >= 180;
  const isMedium = size >= 130 && size < 180;

  return (
    <div style={{ position: "relative", width: `${size}px`, height: `${size}px`, flexShrink: 0 }}>
      <svg width={size} height={size} viewBox="0 0 120 120" role="img" aria-label={ariaLabel}>
        <circle cx="60" cy="60" r={radius} fill="none" stroke={bgStroke} strokeWidth={strokeWidth} />
        <circle
          cx="60"
          cy="60"
          r={radius}
          fill="none"
          stroke={color}
          strokeWidth={strokeWidth}
          strokeLinecap="round"
          strokeDasharray={dash}
          transform="rotate(-90 60 60)"
        />
      </svg>
      <div
        style={{
          position: "absolute",
          inset: 0,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          gap: isLarge ? "2px" : "0px",
        }}
      >
        <div
          style={{
            fontSize: isLarge ? "52px" : isMedium ? "34px" : "26px",
            fontWeight: 800,
            lineHeight: 1,
            color: "#F2F4F7",
          }}
        >
          {shownVal}
          {unit && (
            <span
              style={{
                fontSize: isLarge ? "24px" : isMedium ? "17px" : "14px",
                fontWeight: isLarge ? 700 : 600,
              }}
            >
              {unit}
            </span>
          )}
        </div>
        {sublabel && (
          <div
            style={{
              fontSize: isLarge ? "12px" : "11px",
              fontWeight: 600,
              letterSpacing: "0.08em",
              color: sublabelColor || color,
              marginTop: isLarge ? "4px" : "2px",
            }}
          >
            {sublabel}
          </div>
        )}
      </div>
    </div>
  );
}
