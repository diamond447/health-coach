interface SkeletonProps {
  height?: string | number;
  width?: string | number;
  borderRadius?: string | number;
}

export function Skeleton({
  height = "60px",
  width = "100%",
  borderRadius = "16px",
}: SkeletonProps) {
  return (
    <div
      style={{
        height: typeof height === "number" ? `${height}px` : height,
        width: typeof width === "number" ? `${width}px` : width,
        borderRadius: typeof borderRadius === "number" ? `${borderRadius}px` : borderRadius,
        background: "linear-gradient(90deg, #16191E 25%, #23272E 50%, #16191E 75%)",
        backgroundSize: "200% 100%",
        animation: "pulse 1.5s ease-in-out infinite",
      }}
    />
  );
}
