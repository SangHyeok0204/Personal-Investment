"use client";

import { useState } from "react";
import type { StackColumn } from "@/components/charts/stacked-bar-chart";
import { cn } from "@/lib/utils";

// 일별 막대(건수). 뉴스 두 화면이 각자 복사해 쓰던 것을 한 곳으로 모았다.
//
// ⚠️공용 `StackedBarChart` 는 머리말에 "N개월", 눈금에 `YY-MM` 을 박아 둔다.
//   일별 막대에 그대로 쓰면 "7개월"이라고 거짓말하게 되므로 따로 둔다.
//   날짜가 며칠뿐이라 막대 폭을 72px 로 묶어 가운데 모은다.

export function DayBarChart({
  columns,
  colors,
  height,
  selected,
  onPick,
}: {
  columns: StackColumn[];
  /** 조각 키 → 색. 없으면 한 색(메인 브라운)으로 칠하고 구성 내역도 적지 않는다. */
  colors?: Record<string, string>;
  height: number;
  selected: string | null;
  onPick: (key: string) => void;
}) {
  const [hover, setHover] = useState<string | null>(null);
  const max = Math.max(1, ...columns.map((c) => c.total));
  const active = hover ?? selected;
  const shown = columns.find((c) => c.key === active);

  return (
    <div className="w-full">
      <div className="mb-1 flex items-baseline justify-between text-[10px] font-semibold text-ink-faint">
        <span>
          {shown ? (
            <>
              <b className="text-ge-navy">{shown.label.slice(5)}</b> {shown.total}건
              {colors && shown.segments.length > 0 &&
                ` · ${shown.segments.map((s) => `${s.label} ${s.value}`).join(" · ")}`}
            </>
          ) : (
            `최대 ${max}건`
          )}
        </span>
        <span>{columns.length}일</span>
      </div>
      <div
        className="relative flex w-full items-end justify-center gap-2 border-b border-hairline"
        style={{ height }}
        onMouseLeave={() => setHover(null)}
      >
        <div
          className="pointer-events-none absolute inset-x-0 border-t border-dashed border-hairline"
          style={{ bottom: height / 2 }}
        />
        {columns.map((col) => {
          const h = Math.max((col.total / max) * height, col.total > 0 ? 2 : 0);
          return (
            <button
              key={col.key}
              type="button"
              title={`${col.label} · ${col.total}건`}
              onMouseEnter={() => setHover(col.key)}
              onClick={() => onPick(col.key)}
              className={cn(
                "relative flex min-w-0 max-w-[72px] flex-1 flex-col justify-end transition-opacity",
                active != null && active !== col.key && "opacity-45",
              )}
              style={{ height }}
            >
              <span
                className="flex w-full flex-col-reverse overflow-hidden rounded-t-[2px]"
                style={{ height: h }}
              >
                {col.segments.map((seg) => (
                  <span
                    key={seg.key}
                    className="w-full"
                    style={{
                      height: `${(seg.value / Math.max(col.total, 1)) * 100}%`,
                      backgroundColor: colors ? (colors[seg.key] ?? "#D9D9D9") : "#4C2C19",
                    }}
                  />
                ))}
              </span>
            </button>
          );
        })}
      </div>
      <div className="mt-1 flex w-full justify-center gap-2">
        {columns.map((col) => (
          <span
            key={col.key}
            className={cn(
              "min-w-0 max-w-[72px] flex-1 truncate text-center text-[10px] font-semibold tabular-nums",
              active === col.key ? "text-ge-navy" : "text-ink-faint",
            )}
          >
            {col.label.slice(5).replace("-", "/")}
          </span>
        ))}
      </div>
    </div>
  );
}
