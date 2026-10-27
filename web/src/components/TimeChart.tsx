import { useEffect, useRef, useState } from "preact/hooks";
import {
  findNearestIndex,
  formatDateCzech,
  formatDecimal,
  formatNumber,
  mapValueToY,
  niceTicks,
  pointX,
} from "../helpers";

export interface TimeChartPoint {
  date: string;
  label?: string;
  values: (number | null)[];
}

export interface TimeChartSeries {
  label: string;
  color: string;
  unit: string;
  format?: (v: number) => string;
  kind?: "line" | "bar" | "dots";
  strokeDasharray?: string;
  maxGap?: number;
  colors?: (string | null)[];
  colorOf?: (v: number | null, index: number) => string;
}

export interface TimeChartProps {
  points: TimeChartPoint[];
  series: TimeChartSeries[];
  band?: { lo: number | null; hi: number | null }[];
  bandColor?: string;
  target?: number;
  targetColor?: string;
  height?: number;
  yAxis?: boolean;
  xAxis?: boolean;
  tickFormat?: (v: number) => string;
  ariaLabel?: string;
  workoutWindows?: { start_minute: number; end_minute: number; name?: string }[];
}

export function TimeChart({
  points,
  series,
  band,
  bandColor,
  target,
  targetColor = "#FFB15C",
  height = 120,
  yAxis = true,
  xAxis = false,
  tickFormat,
  ariaLabel,
  workoutWindows,
}: TimeChartProps) {
  const svgRef = useRef<SVGSVGElement | null>(null);
  // Without a touch the readout shows the latest point that has a value.
  const latestIndex = () => {
    for (let i = points.length - 1; i >= 0; i--) {
      if (points[i].values.some((v) => v !== null && v !== undefined && !isNaN(v))) return i;
    }
    return Math.max(0, points.length - 1);
  };
  const [selectedIndex, setSelectedIndex] = useState<number>(latestIndex);

  // Reset when the data changes, not on every re-render of the parent.
  const last = points[points.length - 1];
  const dataKey = `${points.length}:${last?.date}:${last?.label}:${points.filter((p) => p.values.some((v) => v !== null)).length}`;
  useEffect(() => {
    setSelectedIndex(latestIndex());
  }, [dataKey]);

  const viewBoxWidth = 326;
  const plotLeft = yAxis ? 32 : 6;
  const plotRight = 320;
  const plotTop = 8;
  const plotBottom = xAxis ? height - 20 : height - 8;

  // Collect all values to determine range
  const allValues: number[] = [];
  for (const p of points) {
    for (const v of p.values) {
      if (v !== null && v !== undefined && !isNaN(v)) {
        allValues.push(v);
      }
    }
  }
  if (band) {
    for (const b of band) {
      if (b.lo !== null && b.lo !== undefined && !isNaN(b.lo)) allValues.push(b.lo);
      if (b.hi !== null && b.hi !== undefined && !isNaN(b.hi)) allValues.push(b.hi);
    }
  }
  if (target !== undefined && target !== null && !isNaN(target)) {
    allValues.push(target);
  }

  const hasBars = series.some((s) => s.kind === "bar");
  const rawMin = allValues.length > 0 ? Math.min(...allValues) : 0;
  const rawMax = allValues.length > 0 ? Math.max(...allValues) : 1;

  const domainMin = hasBars && rawMin >= 0 ? 0 : rawMin;
  const domainMax = rawMax === domainMin ? domainMin + 1 : rawMax;

  const ticks = yAxis ? niceTicks(domainMin, domainMax, 3) : [];
  const yDomainMin = ticks.length > 0 ? Math.min(domainMin, ticks[0]) : domainMin;
  const yDomainMax =
    ticks.length > 0 ? Math.max(domainMax, ticks[ticks.length - 1]) : domainMax;

  const yOf = (val: number) =>
    mapValueToY(val, yDomainMin, yDomainMax, plotTop, plotBottom);

  // Format tick labels
  const formatTick = (val: number) => {
    if (tickFormat) return tickFormat(val);
    if (Math.abs(val) >= 1000) return formatNumber(val);
    if (val % 1 !== 0) return formatDecimal(val, 1);
    return val.toString();
  };

  // Build band polygons for contiguous segments
  const bandPaths: string[] = [];
  if (band && band.length === points.length) {
    let segmentStart: number | null = null;
    for (let i = 0; i <= points.length; i++) {
      const b = i < points.length ? band[i] : null;
      const isValid = b && b.lo !== null && b.hi !== null && !isNaN(b.lo) && !isNaN(b.hi);
      if (isValid) {
        if (segmentStart === null) segmentStart = i;
      } else {
        if (segmentStart !== null) {
          const segEnd = i - 1;
          const topPts: string[] = [];
          const btmPts: string[] = [];
          for (let k = segmentStart; k <= segEnd; k++) {
            const x = pointX(k, points.length, plotLeft, plotRight);
            const yHi = yOf(band[k].hi!);
            const yLo = yOf(band[k].lo!);
            topPts.push(`${x.toFixed(1)},${yHi.toFixed(1)}`);
            btmPts.unshift(`${x.toFixed(1)},${yLo.toFixed(1)}`);
          }
          if (segmentStart === segEnd) {
            // Single point: add slight width so it renders
            const x = pointX(segmentStart, points.length, plotLeft, plotRight);
            const yHi = yOf(band[segmentStart].hi!);
            const yLo = yOf(band[segmentStart].lo!);
            bandPaths.push(
              `M ${(x - 2).toFixed(1)} ${yHi.toFixed(1)} L ${(x + 2).toFixed(1)} ${yHi.toFixed(1)} L ${(x + 2).toFixed(1)} ${yLo.toFixed(1)} L ${(x - 2).toFixed(1)} ${yLo.toFixed(1)} Z`
            );
          } else {
            bandPaths.push(`M ${topPts.join(" L ")} L ${btmPts.join(" L ")} Z`);
          }
          segmentStart = null;
        }
      }
    }
  }

  // Pointer scrub handler: mouse scrubs immediately; touch waits for horizontal drag
  const touchStateRef = useRef<{
    startX: number;
    startY: number;
    isScrubbing: boolean;
    pointerId: number;
  } | null>(null);

  const updateSelectionFromClientX = (clientX: number) => {
    if (points.length === 0 || !svgRef.current) return;
    const rect = svgRef.current.getBoundingClientRect();
    if (rect.width <= 0) return;
    const svgX = ((clientX - rect.left) / rect.width) * viewBoxWidth;
    const nearest = findNearestIndex(svgX, points.length, plotLeft, plotRight);
    setSelectedIndex(nearest);
  };

  const handlePointerDown = (e: PointerEvent) => {
    if (points.length === 0 || !svgRef.current) return;
    if (e.pointerType === "mouse") {
      updateSelectionFromClientX(e.clientX);
      return;
    }
    touchStateRef.current = {
      startX: e.clientX,
      startY: e.clientY,
      isScrubbing: false,
      pointerId: e.pointerId,
    };
  };

  const handlePointerMove = (e: PointerEvent) => {
    if (points.length === 0 || !svgRef.current) return;
    if (e.pointerType === "mouse") {
      if (e.buttons > 0) {
        updateSelectionFromClientX(e.clientX);
      }
      return;
    }
    const touch = touchStateRef.current;
    if (!touch || touch.pointerId !== e.pointerId) return;

    if (touch.isScrubbing) {
      updateSelectionFromClientX(e.clientX);
    } else {
      const dx = e.clientX - touch.startX;
      const dy = e.clientY - touch.startY;
      if (Math.abs(dx) > Math.abs(dy) && Math.abs(dx) > 6) {
        touch.isScrubbing = true;
        try {
          svgRef.current.setPointerCapture(e.pointerId);
        } catch {
          // ignore if capture fails
        }
        updateSelectionFromClientX(e.clientX);
      }
    }
  };

  const handlePointerUp = (e: PointerEvent) => {
    if (e.pointerType === "mouse") return;
    const touch = touchStateRef.current;
    if (!touch || touch.pointerId !== e.pointerId) return;

    if (!touch.isScrubbing) {
      // Tap (pointerup with little movement) selects tapped point
      const dx = Math.abs(e.clientX - touch.startX);
      const dy = Math.abs(e.clientY - touch.startY);
      if (dx <= 6 && dy <= 6) {
        updateSelectionFromClientX(e.clientX);
      }
    }
    try {
      if (svgRef.current && svgRef.current.hasPointerCapture(e.pointerId)) {
        svgRef.current.releasePointerCapture(e.pointerId);
      }
    } catch {
      // ignore
    }
    touchStateRef.current = null;
  };

  const handlePointerCancel = (e: PointerEvent) => {
    if (touchStateRef.current?.pointerId === e.pointerId) {
      try {
        if (svgRef.current && svgRef.current.hasPointerCapture(e.pointerId)) {
          svgRef.current.releasePointerCapture(e.pointerId);
        }
      } catch {
        // ignore
      }
      touchStateRef.current = null;
    }
  };

  // Build readout string
  const activeIndex =
    points.length > 0 ? Math.max(0, Math.min(points.length - 1, selectedIndex)) : -1;
  const activePoint = activeIndex >= 0 ? points[activeIndex] : null;

  let readout = "";
  if (activePoint) {
    const datePart =
      activePoint.label ||
      (activePoint.date.includes("-")
        ? formatDateCzech(activePoint.date)
        : activePoint.date);

    const seriesParts = series.map((s, sIdx) => {
      const val = activePoint.values[sIdx];
      let valFormatted = "–";
      if (val !== null && val !== undefined && !isNaN(val)) {
        valFormatted = s.format ? s.format(val) : s.unit ? `${val} ${s.unit}` : `${val}`;
      }
      return s.label ? `${s.label} ${valFormatted}` : valFormatted;
    });

    readout = [datePart, ...seriesParts].filter(Boolean).join(" · ");
  }

  // X axis tick dates
  const xAxisTicks: { index: number; label: string; x: number }[] = [];
  if (xAxis && points.length > 0) {
    let tickIndices: number[] = [];
    if (points.length <= 4) {
      tickIndices = points.map((_, i) => i);
    } else if (points.length <= 14) {
      tickIndices = [0, Math.floor((points.length - 1) / 2), points.length - 1];
    } else {
      tickIndices = [
        0,
        Math.floor((points.length - 1) / 3),
        Math.floor((2 * (points.length - 1)) / 3),
        points.length - 1,
      ];
    }

    for (const idx of tickIndices) {
      const p = points[idx];
      let label = p.label || "";
      if (!label && p.date) {
        const parts = p.date.split("-");
        if (parts.length === 3) {
          label = `${parseInt(parts[2], 10)}. ${parseInt(parts[1], 10)}.`;
        } else {
          label = p.date;
        }
      }
      xAxisTicks.push({
        index: idx,
        label,
        x: pointX(idx, points.length, plotLeft, plotRight),
      });
    }
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "6px", width: "100%" }}>
      {/* Readout above chart */}
      <div
        style={{
          fontSize: "12px",
          color: "#C9CED6",
          minHeight: "18px",
          display: "flex",
          alignItems: "center",
          minWidth: 0,
        }}
      >
        <span
          style={{
            display: "block",
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
            minWidth: 0,
            width: "100%",
          }}
        >
          {readout}
        </span>
      </div>

      <svg
        ref={svgRef}
        viewBox={`0 0 ${viewBoxWidth} ${height}`}
        role="img"
        aria-label={ariaLabel || readout || "Graf"}
        style={{
          width: "100%",
          height: "auto",
          touchAction: "pan-y",
          userSelect: "none",
          WebkitUserSelect: "none",
          WebkitTouchCallout: "none",
          cursor: "crosshair",
          overflow: "visible",
        }}
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        onPointerCancel={handlePointerCancel}
      >
        {/* Workout windows background overlay (for intraday HR) */}
        {workoutWindows &&
          workoutWindows.map((w, wIdx) => {
            const x1 = plotLeft + (w.start_minute / 1440) * (plotRight - plotLeft);
            const x2 = plotLeft + (w.end_minute / 1440) * (plotRight - plotLeft);
            const wWidth = Math.max(2, x2 - x1);
            return (
              <rect
                key={wIdx}
                x={x1.toFixed(1)}
                y={plotTop}
                width={wWidth.toFixed(1)}
                height={plotBottom - plotTop}
                fill="#14263B"
                rx="2"
              />
            );
          })}

        {/* Normal band shaded area */}
        {bandPaths.map((d, bIdx) => (
          <path
            key={bIdx}
            d={d}
            fill={bandColor || "rgba(255, 255, 255, 0.08)"}
            rx="2"
          />
        ))}

        {/* Y Axis grid lines & labels */}
        {yAxis &&
          ticks.map((t, tIdx) => {
            const y = yOf(t);
            return (
              <g key={tIdx}>
                <line
                  x1={plotLeft}
                  y1={y.toFixed(1)}
                  x2={plotRight}
                  y2={y.toFixed(1)}
                  stroke="#23272E"
                  stroke-width="1"
                />
                <text
                  x={(plotLeft - 4).toFixed(1)}
                  y={(y + 3.5).toFixed(1)}
                  text-anchor="end"
                  font-size="11"
                  fill="#9BA3AF"
                  font-family="inherit"
                >
                  {formatTick(t)}
                </text>
              </g>
            );
          })}

        {/* Target line */}
        {target !== undefined && target !== null && !isNaN(target) && (
          <line
            x1={plotLeft}
            y1={yOf(target).toFixed(1)}
            x2={plotRight}
            y2={yOf(target).toFixed(1)}
            stroke={targetColor}
            stroke-dasharray="4 3"
            stroke-width="1.5"
          />
        )}

        {/* Series rendering */}
        {points.length > 0 &&
          series.map((s, sIdx) => {
            if (s.kind === "bar") {
              const barWidth = Math.max(
                2,
                Math.min(14, ((plotRight - plotLeft) / points.length) * 0.7)
              );
              const baselineY = yOf(Math.max(0, yDomainMin));
              return (
                <g key={sIdx}>
                  {points.map((p, pIdx) => {
                    const v = p.values[sIdx];
                    if (v === null || v === undefined || isNaN(v)) return null;
                    const cx = pointX(pIdx, points.length, plotLeft, plotRight);
                    const y = yOf(v);
                    const h = Math.max(1, baselineY - y);
                    const barFill =
                      (s.colors && s.colors[pIdx]) ||
                      (s.colorOf ? s.colorOf(v, pIdx) : null) ||
                      s.color;
                    return (
                      <rect
                        key={pIdx}
                        x={(cx - barWidth / 2).toFixed(1)}
                        y={y.toFixed(1)}
                        width={barWidth.toFixed(1)}
                        height={h.toFixed(1)}
                        fill={barFill}
                        rx="1.5"
                      />
                    );
                  })}
                </g>
              );
            }

            if (s.kind === "dots") {
              return (
                <g key={sIdx}>
                  {points.map((p, pIdx) => {
                    const v = p.values[sIdx];
                    if (v === null || v === undefined || isNaN(v)) return null;
                    const cx = pointX(pIdx, points.length, plotLeft, plotRight);
                    const cy = yOf(v);
                    return (
                      <circle
                        key={pIdx}
                        cx={cx.toFixed(1)}
                        cy={cy.toFixed(1)}
                        r="2.5"
                        fill={s.color}
                      />
                    );
                  })}
                </g>
              );
            }

            // Line series with maxGap option (default 0 = break on every null)
            const maxGap = s.maxGap ?? 0;
            const lineSegments: { x: number; y: number }[][] = [];
            let currentSeg: { x: number; y: number }[] = [];
            let lastValidIdx: number | null = null;

            for (let i = 0; i < points.length; i++) {
              const v = points[i].values[sIdx];
              if (v !== null && v !== undefined && !isNaN(v)) {
                const x = pointX(i, points.length, plotLeft, plotRight);
                const y = yOf(v);
                if (lastValidIdx !== null && i - lastValidIdx - 1 > maxGap) {
                  if (currentSeg.length > 0) {
                    lineSegments.push(currentSeg);
                    currentSeg = [];
                  }
                }
                currentSeg.push({ x, y });
                lastValidIdx = i;
              }
            }
            if (currentSeg.length > 0) {
              lineSegments.push(currentSeg);
            }

            return (
              <g key={sIdx}>
                {lineSegments.map((seg, segIdx) => {
                  if (seg.length === 1) {
                    return (
                      <circle
                        key={segIdx}
                        cx={seg[0].x.toFixed(1)}
                        cy={seg[0].y.toFixed(1)}
                        r="2.5"
                        fill={s.color}
                      />
                    );
                  }
                  const pts = seg.map((p) => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(" ");
                  return (
                    <polyline
                      key={segIdx}
                      points={pts}
                      fill="none"
                      stroke={s.color}
                      stroke-width="2"
                      stroke-dasharray={s.strokeDasharray}
                      stroke-linejoin="round"
                      stroke-linecap="round"
                    />
                  );
                })}
              </g>
            );
          })}

        {/* X Axis date labels */}
        {xAxis &&
          xAxisTicks.map((t, idx) => (
            <text
              key={idx}
              x={t.x.toFixed(1)}
              y={(height - 4).toFixed(1)}
              text-anchor="middle"
              font-size="11"
              fill="#9BA3AF"
              font-family="inherit"
            >
              {t.label}
            </text>
          ))}

        {/* Scrub cursor line and dots */}
        {activePoint && points.length > 0 && (
          <g pointer-events="none">
            <line
              x1={pointX(activeIndex, points.length, plotLeft, plotRight).toFixed(1)}
              y1={plotTop}
              x2={pointX(activeIndex, points.length, plotLeft, plotRight).toFixed(1)}
              y2={plotBottom}
              stroke="#5C636D"
              stroke-width="1"
              stroke-dasharray="3 3"
            />
            {series.map((s, sIdx) => {
              const v = activePoint.values[sIdx];
              if (v === null || v === undefined || isNaN(v)) return null;
              const cx = pointX(activeIndex, points.length, plotLeft, plotRight);
              const cy = yOf(v);
              return (
                <circle
                  key={sIdx}
                  cx={cx.toFixed(1)}
                  cy={cy.toFixed(1)}
                  r="4"
                  fill={s.color}
                  stroke="#0B0D10"
                  stroke-width="1.5"
                />
              );
            })}
          </g>
        )}
      </svg>
    </div>
  );
}
