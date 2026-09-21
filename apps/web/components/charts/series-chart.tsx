"use client";

import { useEffect, useMemo, useRef, useState } from "react";

// 시계열 한 개를 그리는 저수준 차트.
//
// 이 레포의 차트 관례를 따른다(ai-key-data/timeseries-chart.tsx 참고):
// ResizeObserver 로 폭을 재고 viewBox 를 px 와 1:1 로 두며, SVG 안에서는 raw hex,
// 바깥은 tailwind 를 쓴다. 차트 헬퍼는 카드마다 복붙하는 것이 이 레포의 관행이라
// 범용 추상화를 만들지 않고 필요한 만큼만 둔다.
//
// ⚠️값이 null 인 점은 **결측**이지 0 이 아니다. 선을 끊어서 그린다 — 0 으로 이으면
//   "그날 자산이 0원이었다"는 없는 사실이 그려진다.

// 가이드 §6·§8 — 팔레트 안에서만. 선은 BROWN(메인), 격자·축은 그레이 스케일.
const GRID = "#F2F2F2"; // Light Gray
const AXIS_TEXT = "#7F7F7F"; // Gray
const LINE = "#4C2C19"; // BROWN
const FILL_TOP = "rgba(76,44,25,0.14)";
const FILL_BOTTOM = "rgba(76,44,25,0.01)";
const CROSS = "#A6A6A6";

const PAD_L = 62;
const PAD_R = 10;
const PAD_T = 8;
const XAXIS_H = 20;

export type SeriesPoint = { date: string; value: number | null };

function useWidth() {
  const ref = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return { ref, width };
}

/** 큰 금액 축 라벨 — 억/만 단위로 접는다. 축은 자릿수를 다 보여줄 자리가 없다. */
function axisLabel(value: number): string {
  const abs = Math.abs(value);
  const sign = value < 0 ? "-" : "";
  if (abs >= 100_000_000) return `${sign}${(abs / 100_000_000).toFixed(1)}억`;
  if (abs >= 10_000) return `${sign}${Math.round(abs / 10_000).toLocaleString("ko-KR")}만`;
  return `${sign}${Math.round(abs).toLocaleString("ko-KR")}`;
}

export function SeriesChart({
  points,
  height = 240,
  valueFormat = axisLabel,
  tooltipFormat,
  /** 0 을 축에 포함할지. 자산 곡선은 포함하면 변화가 안 보여 기본 false. */
  includeZero = false,
}: {
  points: SeriesPoint[];
  height?: number;
  valueFormat?: (v: number) => string;
  tooltipFormat?: (p: SeriesPoint) => string;
  includeZero?: boolean;
}) {
  const { ref, width } = useWidth();
  const [hover, setHover] = useState<number | null>(null);

  const model = useMemo(() => {
    const valid = points.filter((p) => p.value != null) as { date: string; value: number }[];
    if (valid.length === 0 || width === 0) return null;

    let min = Math.min(...valid.map((p) => p.value));
    let max = Math.max(...valid.map((p) => p.value));
    if (includeZero) {
      min = Math.min(min, 0);
      max = Math.max(max, 0);
    }
    if (min === max) {
      // 평평한 계열 — 위아래로 여유를 줘야 선이 축에 붙지 않는다.
      const pad = Math.abs(min) * 0.05 || 1;
      min -= pad;
      max += pad;
    }
    const innerW = Math.max(width - PAD_L - PAD_R, 1);
    const innerH = Math.max(height - PAD_T - XAXIS_H, 1);
    const x = (i: number) =>
      PAD_L + (points.length === 1 ? innerW / 2 : (i / (points.length - 1)) * innerW);
    const y = (v: number) => PAD_T + innerH - ((v - min) / (max - min)) * innerH;

    // 결측을 만나면 선을 끊는다(M 으로 다시 시작).
    let path = "";
    let area = "";
    let open = false;
    points.forEach((p, i) => {
      if (p.value == null) {
        open = false;
        return;
      }
      const cmd = open ? "L" : "M";
      path += `${cmd}${x(i).toFixed(1)},${y(p.value).toFixed(1)}`;
      if (!open) area += `${area ? "Z" : ""}M${x(i).toFixed(1)},${(PAD_T + innerH).toFixed(1)}`;
      area += `L${x(i).toFixed(1)},${y(p.value).toFixed(1)}`;
      open = true;
    });
    if (area) area += `L${x(points.length - 1).toFixed(1)},${(PAD_T + innerH).toFixed(1)}Z`;

    const ticks = [0, 0.25, 0.5, 0.75, 1].map((t) => min + (max - min) * t);
    return { min, max, x, y, path, area, ticks, innerH };
  }, [points, width, height, includeZero]);

  const hovered = hover != null ? points[hover] : null;

  return (
    <div ref={ref} className="relative w-full" style={{ height }}>
      {model && (
        <svg
          width={width}
          height={height}
          viewBox={`0 0 ${width} ${height}`}
          onMouseLeave={() => setHover(null)}
          onMouseMove={(e) => {
            const box = e.currentTarget.getBoundingClientRect();
            const rel = e.clientX - box.left - PAD_L;
            const innerW = Math.max(width - PAD_L - PAD_R, 1);
            const idx = Math.round((rel / innerW) * (points.length - 1));
            setHover(Math.min(Math.max(idx, 0), points.length - 1));
          }}
        >
          <defs>
            <linearGradient id="seriesFill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={FILL_TOP} />
              <stop offset="100%" stopColor={FILL_BOTTOM} />
            </linearGradient>
          </defs>

          {model.ticks.map((t, i) => (
            <g key={i}>
              <line
                x1={PAD_L}
                x2={width - PAD_R}
                y1={model.y(t)}
                y2={model.y(t)}
                stroke={GRID}
              />
              <text
                x={PAD_L - 8}
                y={model.y(t) + 4}
                textAnchor="end"
                fontSize="11"
                fill={AXIS_TEXT}
              >
                {valueFormat(t)}
              </text>
            </g>
          ))}

          <path d={model.area} fill="url(#seriesFill)" />
          <path d={model.path} fill="none" stroke={LINE} strokeWidth="1.8" />

          {hovered?.value != null && hover != null && (
            <>
              <line
                x1={model.x(hover)}
                x2={model.x(hover)}
                y1={PAD_T}
                y2={PAD_T + model.innerH}
                stroke={CROSS}
                strokeDasharray="3 3"
              />
              <circle cx={model.x(hover)} cy={model.y(hovered.value)} r="3.5" fill={LINE} />
            </>
          )}

          {/* x 축 — 양 끝과 가운데만. 촘촘히 찍으면 겹쳐서 못 읽는다. */}
          {[0, Math.floor(points.length / 2), points.length - 1]
            .filter((i, idx, arr) => points[i] && arr.indexOf(i) === idx)
            .map((i) => (
              <text
                key={i}
                x={model.x(i)}
                y={height - 5}
                textAnchor={i === 0 ? "start" : i === points.length - 1 ? "end" : "middle"}
                fontSize="11"
                fill={AXIS_TEXT}
              >
                {points[i].date.slice(2)}
              </text>
            ))}
        </svg>
      )}

      {hovered && (
        <div className="pointer-events-none absolute left-1/2 top-1 -translate-x-1/2 rounded-lg bg-white/95 px-2.5 py-1 text-[11px] font-bold text-ge-navy shadow-card ring-1 ring-hairline">
          {hovered.date}
          <span className="ml-2 tabular-nums">
            {hovered.value == null
              ? "—"
              : tooltipFormat
                ? tooltipFormat(hovered)
                : valueFormat(hovered.value)}
          </span>
        </div>
      )}
    </div>
  );
}
