"use client";

import { useState } from "react";
import type { PortfolioHistory } from "@/lib/api";
import { formatKrw } from "@/lib/format";
import { Skeleton } from "@/components/ui/skeleton";

const VIEW_W = 420;
const VIEW_H = 150;
const PAD_X = 6;
const PLOT_TOP = 10;
const PLOT_BOTTOM = 118;
const PLOT_W = VIEW_W - PAD_X * 2;
const PLOT_H = PLOT_BOTTOM - PLOT_TOP;

const TIP_W = 96;
const TIP_H = 26;

function shortDate(date: string): string {
  const [, month, day] = date.split("-");
  return `${Number(month)}.${Number(day)}`;
}

export function PerformanceChart({
  history,
  loading,
  isError,
}: {
  history: PortfolioHistory | undefined;
  loading: boolean;
  isError: boolean;
}) {
  const [hover, setHover] = useState<number | null>(null);

  if (loading) {
    return <Skeleton className="mt-2 h-36 w-full" />;
  }

  // A failed fetch is not the same fact as "no history yet" — say which it is.
  if (isError) {
    return (
      <div className="mt-2 flex h-36 items-center justify-center rounded-lg border border-dashed border-slate-200 bg-slate-50/50 px-4 text-center text-xs text-slate-400">
        자산 추이를 불러오지 못했습니다.
      </div>
    );
  }

  const points = history?.points ?? [];
  const distinctDays = history?.distinct_days ?? 0;

  // One point cannot describe a trend. Show the accumulating state rather than
  // drawing a line through a single value (performance-chart-spec §2).
  if (distinctDays < 2) {
    return (
      <AccumulatingState
        distinctDays={distinctDays}
        firstDate={points[0]?.date ?? null}
      />
    );
  }

  const values = points.map((p) => p.total_assets_krw);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min;
  // Every snapshot so far carries an identical total, so a flat series is the
  // expected case, not an edge case: pad a zero span instead of dividing by it.
  const pad = span === 0 ? Math.max(Math.abs(max) * 0.01, 1) : span * 0.15;
  const yMin = min - pad;
  const yMax = max + pad;

  const xAt = (i: number) => PAD_X + (i / (points.length - 1)) * PLOT_W;
  const yAt = (value: number) =>
    PLOT_BOTTOM - ((value - yMin) / (yMax - yMin)) * PLOT_H;

  const line = points
    .map(
      (p, i) =>
        `${i === 0 ? "M" : "L"} ${xAt(i).toFixed(2)} ${yAt(p.total_assets_krw).toFixed(2)}`,
    )
    .join(" ");
  const area = `${line} L ${xAt(points.length - 1).toFixed(2)} ${PLOT_BOTTOM} L ${xAt(0).toFixed(2)} ${PLOT_BOTTOM} Z`;

  const lastIndex = points.length - 1;
  const band = PLOT_W / Math.max(points.length - 1, 1);
  const labelIndexes =
    points.length <= 2
      ? [0, lastIndex]
      : [0, Math.floor(lastIndex / 2), lastIndex];

  return (
    <svg
      viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
      className="mt-2 h-36 w-full"
      role="img"
      aria-label="총자산 추이"
      onMouseLeave={() => setHover(null)}
    >
      <defs>
        <linearGradient id="perf-area" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#2878f0" stopOpacity="0.16" />
          <stop offset="100%" stopColor="#2878f0" stopOpacity="0" />
        </linearGradient>
      </defs>

      <g stroke="#e5e7eb" strokeWidth="1">
        {[0, 1, 2, 3].map((i) => {
          const y = PLOT_TOP + (i / 3) * PLOT_H;
          return <line key={i} x1={PAD_X} y1={y} x2={VIEW_W - PAD_X} y2={y} />;
        })}
      </g>

      <path d={area} fill="url(#perf-area)" />
      <path
        d={line}
        fill="none"
        stroke="#2878f0"
        strokeWidth="2.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />

      {/* Emphasised last point. */}
      <circle
        cx={xAt(lastIndex)}
        cy={yAt(values[lastIndex])}
        r="4"
        fill="#2878f0"
        stroke="#fff"
        strokeWidth="2"
      />

      <g fill="#94a3b8" fontSize="9">
        {labelIndexes.map((i, n) => (
          <text
            key={i}
            x={xAt(i)}
            y={134}
            textAnchor={n === 0 ? "start" : n === labelIndexes.length - 1 ? "end" : "middle"}
          >
            {shortDate(points[i].date)}
          </text>
        ))}
      </g>

      {/* Hover targets — one band per point. */}
      {points.map((p, i) => (
        <rect
          key={p.date}
          x={xAt(i) - band / 2}
          y={0}
          width={band}
          height={PLOT_BOTTOM}
          fill="transparent"
          onMouseEnter={() => setHover(i)}
        />
      ))}

      {hover != null && (
        <g pointerEvents="none">
          <line
            x1={xAt(hover)}
            y1={PLOT_TOP}
            x2={xAt(hover)}
            y2={PLOT_BOTTOM}
            stroke="#cbd5e1"
            strokeWidth="1"
            strokeDasharray="3 3"
          />
          <circle
            cx={xAt(hover)}
            cy={yAt(values[hover])}
            r="3.5"
            fill="#2878f0"
            stroke="#fff"
            strokeWidth="1.5"
          />
          <g
            transform={`translate(${Math.min(
              Math.max(xAt(hover) - TIP_W / 2, 0),
              VIEW_W - TIP_W,
            )}, ${Math.max(yAt(values[hover]) - TIP_H - 6, 2)})`}
          >
            <rect width={TIP_W} height={TIP_H} rx="4" fill="#0f172a" opacity="0.92" />
            <text x={TIP_W / 2} y="11" textAnchor="middle" fontSize="8" fill="#cbd5e1">
              {points[hover].date}
            </text>
            <text
              x={TIP_W / 2}
              y="21"
              textAnchor="middle"
              fontSize="9.5"
              fontWeight="600"
              fill="#fff"
            >
              {formatKrw(values[hover])}
            </text>
          </g>
        </g>
      )}
    </svg>
  );
}

function AccumulatingState({
  distinctDays,
  firstDate,
}: {
  distinctDays: number;
  firstDate: string | null;
}) {
  return (
    <div className="mt-2 flex h-36 flex-col items-center justify-center rounded-lg border border-dashed border-slate-200 bg-slate-50/50 px-4 text-center">
      <p className="text-xs font-medium text-slate-600">
        자산 추이는 동기화 기록이 쌓이면 표시됩니다.
      </p>
      <p className="mt-1 text-[11px] tabular-nums text-slate-400">
        현재 {distinctDays}일치
        {firstDate ? ` · 최초 기록 ${firstDate}` : ""}
      </p>
      <p className="mt-2 text-[11px] text-slate-400">
        매일 자동 동기화를 켜면 하루 한 점씩 쌓입니다.
      </p>
    </div>
  );
}
