"use client";

import { useState } from "react";
import { cn } from "@/lib/utils";

// 부호 있는 세로막대. 0 선을 기준으로 양수는 위(bid), 음수는 아래(ask).
//
// 누적막대(stacked-bar-chart)는 합계가 양수라는 전제로 그린다. 입출금·
// "배당 − 비용"처럼 **달마다 부호가 바뀌는 값**은 그 전제가 깨져서 따로 둔다.
//
// ⚠️0 선의 위치는 **최댓값·최솟값 비율**로 정한다. 가운데 고정하면 한쪽만 있는
//   계열에서 차트 절반이 비고 막대가 반토막 난다.

export type SignedColumn = { key: string; label: string; value: number };

export function SignedBarChart({
  columns,
  height = 180,
  formatValue,
  selected,
  onPick,
  unit = "개월",
  formatLabel = (label: string) => label.slice(2),
}: {
  columns: SignedColumn[];
  height?: number;
  formatValue: (value: number) => string;
  selected?: string | null;
  /** 막대를 눌렀을 때. 호버만으로는 부르지 않는다. */
  onPick?: (key: string) => void;
  /** 머리말 "N{unit}". 월별이 아니면 바꾼다(예: 연도별 "년"). */
  unit?: string;
  /** 축 라벨. 기본은 'YYYY-MM' → 'YY-MM'. */
  formatLabel?: (label: string) => string;
}) {
  const [hover, setHover] = useState<string | null>(null);

  if (columns.length === 0) {
    return (
      <div className="flex h-40 items-center justify-center text-[12px] font-semibold text-ink-faint">
        표시할 데이터가 없습니다
      </div>
    );
  }

  const max = Math.max(0, ...columns.map((c) => c.value));
  const min = Math.min(0, ...columns.map((c) => c.value));
  const span = max - min || 1;
  const zero = (max / span) * height; // 위에서 0 선까지의 거리
  const active = hover ?? selected ?? null;
  const labelStep = Math.ceil(columns.length / 8);
  const shown = columns.find((c) => c.key === active);

  return (
    <div className="w-full">
      <div className="mb-1 flex items-baseline justify-between text-[10px] font-semibold text-ink-faint">
        <span>
          {shown ? (
            <>
              <b className="text-ge-navy">{shown.label}</b> {formatValue(shown.value)}
            </>
          ) : (
            `최대 ${formatValue(max)}${min < 0 ? ` · 최소 ${formatValue(min)}` : ""}`
          )}
        </span>
        <span>
          {columns.length}
          {unit}
        </span>
      </div>

      <div
        className="relative flex w-full gap-[3px]"
        style={{ height }}
        onMouseLeave={() => setHover(null)}
      >
        <div
          className="pointer-events-none absolute inset-x-0 border-t border-ink-faint/60"
          style={{ top: zero }}
        />
        {columns.map((col) => {
          const h = (Math.abs(col.value) / span) * height;
          const up = col.value >= 0;
          return (
            <button
              key={col.key}
              type="button"
              title={`${col.label} · ${formatValue(col.value)}`}
              onMouseEnter={() => setHover(col.key)}
              onClick={() => onPick?.(col.key)}
              className={cn(
                "relative min-w-0 flex-1 transition-opacity",
                onPick ? "cursor-pointer" : "cursor-default",
                active != null && active !== col.key && "opacity-45",
              )}
            >
              <span
                className={cn("absolute inset-x-0", up ? "rounded-t-[2px] bg-bid" : "rounded-b-[2px] bg-ask")}
                style={
                  up
                    ? { top: zero - Math.max(h, col.value !== 0 ? 2 : 0), height: Math.max(h, col.value !== 0 ? 2 : 0) }
                    : { top: zero, height: Math.max(h, 2) }
                }
              />
            </button>
          );
        })}
      </div>

      <div className="mt-1 flex w-full gap-[3px]">
        {columns.map((col, i) => (
          <span
            key={col.key}
            className={cn(
              "min-w-0 flex-1 truncate text-center text-[9px] font-semibold tabular-nums",
              active === col.key ? "text-ge-navy" : "text-ink-faint",
            )}
          >
            {i % labelStep === 0 || active === col.key ? formatLabel(col.label) : ""}
          </span>
        ))}
      </div>
    </div>
  );
}
