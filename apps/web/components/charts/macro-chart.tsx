"use client";

import { useEffect, useMemo, useRef, useState } from "react";

// 매크로 소형 다중 차트(small multiples) 한 칸 — 월간 시계열.
//
// series-chart.tsx 와 같은 관례(ResizeObserver 로 폭, viewBox 1:1, SVG 안은 raw hex)를
// 따르되 따로 둔다. 그쪽은 **점 순서(index)** 가 x 축이라 여러 차트의 x 가 맞지 않고,
// 왼쪽 여백(62px)이 소형 차트에는 너무 크다. 여기는 **달력(월)** 이 x 축이다 —
// 16개 차트가 같은 구간·같은 눈금을 써야 "그때 금리가 오르고 실업률이 올랐다"를
// 세로로 훑어 읽을 수 있다.
//
// ⚠️점이 빠진 달(전년 값이 없어 yoy 를 못 낸 달 등)은 선을 끊는다. 이으면 없는
//   값이 그려진다.

const GRID = "#F2F2F2";
const AXIS_TEXT = "#7F7F7F";
const LINE = "#4C2C19"; // BROWN
const CROSS = "#A6A6A6";
const ZERO = "#BFBFBF";
const BAND = "rgba(127,127,127,0.13)"; // 침체 음영 — 선보다 한참 옅게

const PAD_L = 42;
const PAD_R = 8;
const PAD_T = 6;
const XAXIS_H = 16;

/** "YYYY-MM" → 월 번호(연속 정수). */
function monthIndex(ym: string): number {
  return Number(ym.slice(0, 4)) * 12 + Number(ym.slice(5, 7)) - 1;
}

function niceStep(raw: number): number {
  const p = 10 ** Math.floor(Math.log10(raw));
  const f = raw / p;
  return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 2.5 ? 2.5 : f <= 5 ? 5 : 10) * p;
}

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

export function MacroChart({
  points,
  start,
  end,
  bands = [],
  height = 130,
  zeroLine = false,
  axisFormat,
  tooltipFormat,
}: {
  /** [["YYYY-MM", 값]] 오름차순. */
  points: [string, number][];
  /** x 축 구간(YYYY-MM). 여러 차트가 같은 값을 받아야 세로로 맞는다. */
  start: string;
  end: string;
  /** 음영 구간 [시작월, 끝월] 양끝 포함(NBER 침체). */
  bands?: [string, string][];
  height?: number;
  /** 0 을 축에 넣고 0 선을 긋는다(금리차·증감처럼 부호가 뜻인 지표). */
  zeroLine?: boolean;
  axisFormat: (v: number) => string;
  tooltipFormat: (v: number) => string;
}) {
  const { ref, width } = useWidth();
  const [hover, setHover] = useState<number | null>(null);

  const model = useMemo(() => {
    if (points.length === 0 || width === 0) return null;
    const m0 = Math.min(monthIndex(start), monthIndex(points[0][0]));
    const m1 = Math.max(monthIndex(end), m0 + 1);
    const innerW = Math.max(width - PAD_L - PAD_R, 1);
    const innerH = Math.max(height - PAD_T - XAXIS_H, 1);
    const x = (m: number) => PAD_L + ((m - m0) / (m1 - m0)) * innerW;

    let min = Math.min(...points.map((p) => p[1]));
    let max = Math.max(...points.map((p) => p[1]));
    if (zeroLine) {
      min = Math.min(min, 0);
      max = Math.max(max, 0);
    }
    if (min === max) {
      const pad = Math.abs(min) * 0.05 || 1;
      min -= pad;
      max += pad;
    }
    // 눈금 3~4개 — 소형 차트라 더 찍으면 글자가 겹친다.
    const step = niceStep((max - min) / 3);
    const lo = Math.floor(min / step) * step;
    const hi = Math.ceil(max / step) * step;
    const ticks: number[] = [];
    for (let t = lo; t <= hi + step / 2; t += step) ticks.push(Number(t.toPrecision(12)));
    const y = (v: number) => PAD_T + innerH - ((v - lo) / (hi - lo)) * innerH;

    const months = points.map((p) => monthIndex(p[0]));
    let path = "";
    months.forEach((m, i) => {
      const gap = i === 0 || m - months[i - 1] > 1;
      path += `${gap ? "M" : "L"}${x(m).toFixed(1)},${y(points[i][1]).toFixed(1)}`;
    });

    // x 눈금 — 연 단위, 4~6개가 되게 간격을 고른다.
    const years = (m1 - m0) / 12;
    const yStep = [1, 2, 5, 10, 20, 25, 50].find((s) => years / s <= 5) ?? 50;
    const xTicks: number[] = [];
    const firstYear = Math.ceil(m0 / 12);
    for (let yr = Math.ceil(firstYear / yStep) * yStep; yr * 12 <= m1; yr += yStep) {
      xTicks.push(yr);
    }

    const rects = bands
      .map(([a, b]) => [Math.max(monthIndex(a), m0), Math.min(monthIndex(b) + 1, m1)])
      .filter(([a, b]) => b > a)
      .map(([a, b]) => ({ x: x(a), w: Math.max(x(b) - x(a), 1) }));

    return { m0, m1, x, y, ticks, innerW, innerH, path, months, xTicks, rects };
  }, [points, start, end, bands, width, height, zeroLine]);

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
            const rel = (e.clientX - box.left - PAD_L) / model.innerW;
            const target = model.m0 + rel * (model.m1 - model.m0);
            // 가장 가까운 점 — 월 번호가 오름차순이라 이분 탐색.
            const ms = model.months;
            let lo = 0;
            let hi = ms.length - 1;
            while (lo < hi) {
              const mid = (lo + hi) >> 1;
              if (ms[mid] < target) lo = mid + 1;
              else hi = mid;
            }
            if (lo > 0 && target - ms[lo - 1] < ms[lo] - target) lo -= 1;
            setHover(lo);
          }}
        >
          {model.rects.map((r, i) => (
            <rect key={i} x={r.x} y={PAD_T} width={r.w} height={model.innerH} fill={BAND} />
          ))}

          {model.ticks.map((t) => (
            <g key={t}>
              <line
                x1={PAD_L}
                x2={width - PAD_R}
                y1={model.y(t)}
                y2={model.y(t)}
                stroke={t === 0 && zeroLine ? ZERO : GRID}
                strokeDasharray={t === 0 && zeroLine ? "3 2" : undefined}
              />
              <text
                x={PAD_L - 5}
                y={model.y(t) + 3.5}
                textAnchor="end"
                fontSize="10"
                fill={AXIS_TEXT}
              >
                {axisFormat(t)}
              </text>
            </g>
          ))}

          <path d={model.path} fill="none" stroke={LINE} strokeWidth="1.5" />

          {model.xTicks.map((yr) => (
            <text
              key={yr}
              x={model.x(yr * 12)}
              y={height - 3}
              textAnchor="middle"
              fontSize="10"
              fill={AXIS_TEXT}
            >
              {model.m1 - model.m0 > 240 ? yr : `'${String(yr).slice(2)}`}
            </text>
          ))}

          {hovered && (
            <>
              <line
                x1={model.x(model.months[hover!])}
                x2={model.x(model.months[hover!])}
                y1={PAD_T}
                y2={PAD_T + model.innerH}
                stroke={CROSS}
                strokeDasharray="3 3"
              />
              <circle
                cx={model.x(model.months[hover!])}
                cy={model.y(hovered[1])}
                r="3"
                fill={LINE}
              />
            </>
          )}
        </svg>
      )}

      {hovered && (
        <div className="pointer-events-none absolute right-1 top-0 rounded-md bg-white/95 px-2 py-0.5 text-[11px] font-bold text-ge-navy shadow-card ring-1 ring-hairline">
          {hovered[0]}
          <span className="ml-1.5 tabular-nums">{tooltipFormat(hovered[1])}</span>
        </div>
      )}
    </div>
  );
}
