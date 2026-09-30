"use client";

import { useState } from "react";
import { cn } from "@/lib/utils";

// 부호 있는 누적 세로막대 — 한 막대 안에서 **양수 조각은 0 선 위로, 음수 조각은 아래로** 쌓는다.
//
// 거장 13F 섹터 순유입처럼 한 기간 안에 들어온 섹터와 빠진 섹터가 같이 있는 값에 쓴다.
// 누적막대(stacked-bar-chart)는 합계가 양수라는 전제, 부호막대(signed-bar-chart)는 계열이
// 하나라는 전제라 둘 다 맞지 않는다.
//
// ⚠️0 선 위치는 (위로 쌓인 최대 합) : (아래로 쌓인 최대 합) 비율로 정한다(signed-bar-chart 와 같은 이유).

export type SignedStackColumn = {
  key: string;
  label: string;
  segments: { key: string; value: number }[];
  /** 막대 아래 흐린 표시(예: 커버리지 격차 경고). */
  flag?: boolean;
};

export function SignedStackedBarChart({
  columns,
  colors,
  height = 200,
  formatValue,
  selected,
  onPick,
  onHover,
  unit = "분기",
}: {
  columns: SignedStackColumn[];
  colors: Record<string, string>;
  height?: number;
  formatValue: (value: number) => string;
  selected?: string | null;
  onPick?: (key: string) => void;
  onHover?: (key: string | null) => void;
  /** 머리말 "N{unit}". */
  unit?: string;
}) {
  const [hover, setHover] = useState<string | null>(null);

  if (columns.length === 0) {
    return (
      <div className="flex h-40 items-center justify-center text-[12px] font-semibold text-ink-faint">
        표시할 데이터가 없습니다
      </div>
    );
  }

  const up = (c: SignedStackColumn) => c.segments.reduce((s, x) => s + Math.max(x.value, 0), 0);
  const down = (c: SignedStackColumn) => c.segments.reduce((s, x) => s + Math.min(x.value, 0), 0);
  const max = Math.max(0, ...columns.map(up));
  const min = Math.min(0, ...columns.map(down));
  const span = max - min || 1;
  const zero = (max / span) * height;
  const px = (v: number) => (Math.abs(v) / span) * height;
  const active = hover ?? selected ?? null;
  const set = (k: string | null) => {
    setHover(k);
    onHover?.(k);
  };

  return (
    <div className="w-full">
      <div className="mb-1 flex items-baseline justify-between text-[10px] font-semibold text-ink-faint">
        <span>
          위 최대 {formatValue(max)} · 아래 최대 {formatValue(min)}
        </span>
        <span>
          {columns.length}
          {unit}
        </span>
      </div>
      <div className="relative flex w-full gap-[6px]" style={{ height }} onMouseLeave={() => set(null)}>
        <div className="pointer-events-none absolute inset-x-0 border-t border-ink-faint/60" style={{ top: zero }} />
        {columns.map((col) => {
          const pos = col.segments.filter((s) => s.value > 0).sort((a, b) => b.value - a.value);
          const neg = col.segments.filter((s) => s.value < 0).sort((a, b) => a.value - b.value);
          let top = zero;
          let bottom = zero;
          return (
            <button
              key={col.key}
              type="button"
              title={col.label}
              onMouseEnter={() => set(col.key)}
              onClick={() => onPick?.(col.key)}
              className={cn(
                "relative min-w-0 flex-1 transition-opacity",
                onPick ? "cursor-pointer" : "cursor-default",
                active != null && active !== col.key && "opacity-45",
              )}
            >
              {pos.map((s) => {
                const h = px(s.value);
                top -= h;
                return (
                  <span
                    key={s.key}
                    className="absolute inset-x-0"
                    style={{ top, height: Math.max(h, 0.5), backgroundColor: colors[s.key] ?? "#D9D9D9" }}
                  />
                );
              })}
              {neg.map((s) => {
                const h = px(s.value);
                const y = bottom;
                bottom += h;
                return (
                  <span
                    key={s.key}
                    className="absolute inset-x-0"
                    style={{ top: y, height: Math.max(h, 0.5), backgroundColor: colors[s.key] ?? "#D9D9D9" }}
                  />
                );
              })}
            </button>
          );
        })}
      </div>
      <div className="mt-1 flex w-full gap-[6px]">
        {columns.map((col) => (
          <span
            key={col.key}
            className={cn(
              "min-w-0 flex-1 truncate text-center text-[9px] font-semibold tabular-nums",
              active === col.key ? "text-ge-navy" : "text-ink-faint",
            )}
          >
            {col.label}
            {col.flag ? "*" : ""}
          </span>
        ))}
      </div>
    </div>
  );
}
