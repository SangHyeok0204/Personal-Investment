"use client";

import { useMemo, useState } from "react";
import { cn } from "@/lib/utils";

// 누적 세로막대. x = 기간(월), y = 합계, 한 막대를 항목별로 쌓아 색으로 나눈다.
//
// 이 레포의 차트 관례를 따른다(SVG 안은 raw hex, 바깥은 tailwind). 색은
// `donut-chart` 의 팔레트를 **그대로 받아 쓴다** — 같은 화면의 도넛과 색이
// 어긋나면 눈이 두 그래프를 잇지 못한다.
//
// ⚠️막대 높이는 **합계에 비례**해야 한다. 조각마다 최소 높이를 주면 작은 값이
//   부풀어 막대끼리 비교가 깨진다. 대신 0 보다 큰 조각은 보이도록 아주 얇은
//   하한(0.5px)만 둔다.

export type StackSegment = {
  key: string;
  label: string;
  value: number;
};

export type StackColumn = {
  key: string;
  label: string;
  total: number;
  segments: StackSegment[];
};

export function StackedBarChart({
  columns,
  colors,
  height = 190,
  formatTotal,
  selected,
  onSelect,
}: {
  columns: StackColumn[];
  /** 항목 키 → 색. 도넛과 공유한다. */
  colors: Record<string, string>;
  height?: number;
  formatTotal: (value: number) => string;
  /** 지금 강조할 열(호버 또는 고정 선택). */
  selected?: string | null;
  /** 호버·클릭으로 열이 바뀔 때. null 이면 해제. */
  onSelect?: (key: string | null, sticky: boolean) => void;
}) {
  const [hover, setHover] = useState<string | null>(null);
  const max = useMemo(
    () => Math.max(1, ...columns.map((c) => c.total)),
    [columns],
  );

  if (columns.length === 0) {
    return (
      <div className="flex h-40 items-center justify-center text-[12px] font-semibold text-ink-faint">
        표시할 데이터가 없습니다
      </div>
    );
  }

  const active = hover ?? selected ?? null;
  // 막대가 많아지면 라벨이 겹친다. 겹치기 전에 **건너뛰어** 적는다.
  const labelStep = Math.ceil(columns.length / 8);

  return (
    <div className="w-full">
      <div className="mb-1 flex items-baseline justify-between">
        <span className="text-[10px] font-semibold text-ink-faint">
          최대 {formatTotal(max)}
        </span>
        <span className="text-[10px] font-semibold text-ink-faint">
          {columns.length}개월
        </span>
      </div>

      <div
        className="relative flex w-full items-end gap-[3px] border-b border-hairline"
        style={{ height }}
        onMouseLeave={() => {
          setHover(null);
          onSelect?.(null, false);
        }}
      >
        {/* 눈금선 — 절반 높이 하나만. 격자를 채우면 막대가 안 읽힌다. */}
        <div
          className="pointer-events-none absolute inset-x-0 border-t border-dashed border-hairline"
          style={{ bottom: height / 2 }}
        />
        {columns.map((col) => {
          const isActive = active === col.key;
          const colHeight = (col.total / max) * height;
          return (
            <button
              key={col.key}
              type="button"
              title={`${col.label} · ${formatTotal(col.total)}`}
              onMouseEnter={() => {
                setHover(col.key);
                onSelect?.(col.key, false);
              }}
              onClick={() => onSelect?.(col.key, true)}
              className={cn(
                "group relative flex min-w-0 flex-1 flex-col justify-end rounded-t-[2px] transition-opacity",
                active != null && !isActive && "opacity-45",
              )}
              style={{ height }}
            >
              <span
                className="flex w-full flex-col-reverse overflow-hidden rounded-t-[2px]"
                style={{ height: Math.max(colHeight, col.total > 0 ? 2 : 0) }}
              >
                {col.segments.map((seg) => (
                  <span
                    key={seg.key}
                    className="w-full"
                    style={{
                      // ⚠️합계 대비 비율 그대로. 조각별 최소 높이를 크게 주면
                      //   작은 값이 부풀어 막대끼리 비교가 깨진다.
                      height: `${Math.max((seg.value / Math.max(col.total, 1)) * 100, 0.5)}%`,
                      backgroundColor: colors[seg.key] ?? "#D9D9D9",
                    }}
                  />
                ))}
              </span>
              {isActive && (
                // ⚠️버튼은 차트 높이 전체를 차지한다. top 에 붙이면 표시선이
                //   **막대 위가 아니라 차트 맨 위**에 뜬다(실제로 그렇게 나왔다).
                //   막대 높이만큼 띄워 막대 머리에 얹는다.
                <span
                  className="pointer-events-none absolute inset-x-0 border-t-2"
                  style={{
                    borderColor: "#4C2C19",
                    bottom: Math.max(colHeight, col.total > 0 ? 2 : 0),
                  }}
                />
              )}
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
            {/* 겹치기 전에 건너뛰어 적는다. 활성 열은 언제나 적는다. */}
            {i % labelStep === 0 || active === col.key ? col.label.slice(2) : ""}
          </span>
        ))}
      </div>
    </div>
  );
}
