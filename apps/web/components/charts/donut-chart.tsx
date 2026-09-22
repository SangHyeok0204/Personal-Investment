"use client";

import { useState } from "react";
import { cn } from "@/lib/utils";

// 도넛 + 오른쪽 범례. 사용자가 보내 준 레퍼런스 형태다.
//
// 이 레포의 차트 관례를 따른다(SVG 안은 raw hex, 바깥은 tailwind).
// 조각 색은 **고정 팔레트를 순서대로** 쓴다 — 값에 따라 색이 바뀌면 다시 볼 때마다
// 같은 종목이 다른 색이 되어 눈이 기억하지 못한다.

// 가이드 §8 — 그래프 색은 **브랜드 팔레트(BROWN/BLUE 계열 + 그레이 스케일) 안에서만**
// 쓴다. 이전 팔레트는 코랄·민트·퍼플 같은 가이드 밖 색을 섞고 있었다.
//
// 두 계열을 번갈아 두고 명도를 단계적으로 낮춰, 인접 조각이 색상이 아니라
// **명도**로 구분되게 한다 — 같은 계열 안에서 채도만 바꾸면 붙은 조각이 뭉친다.
export const CHART_PALETTE = [
  "#4C2C19", // BROWN
  "#6390BF", // BLUE
  "#7B401F", // 포인트 브라운
  "#3A6B96", // BLUE 다크
  "#A0724F", // BROWN 라이트
  "#9DBBD6", // BLUE 라이트
  "#C9A98C", // BROWN 더 라이트
  "#BEDBE8", // Light Blue
  "#595959", // Dark Gray
  "#A6A6A6", // Gray
];
export const CHART_MUTED = "#D9D9D9"; // 기타/미분류 — 그레이 스케일

/** 키 → 색. **누적막대와 도넛이 같은 색을 써야** 눈이 두 그래프를 잇는다. */
export function colorForKeys(keys: string[]): Record<string, string> {
  const out: Record<string, string> = {};
  keys.forEach((k, i) => {
    out[k] = CHART_PALETTE[i % CHART_PALETTE.length];
  });
  return out;
}

const PALETTE = CHART_PALETTE;
const MUTED = CHART_MUTED;

export type DonutSlice = {
  key: string;
  label: string;
  value: number;
  /** 범례 오른쪽에 붙는 보조 문구(금액 등). */
  caption?: string;
  /** true 면 회색으로 그린다(미분류·기타). */
  muted?: boolean;
};

function arcPath(cx: number, cy: number, r: number, inner: number, from: number, to: number) {
  // 한 조각이 100% 일 때 시작=끝이라 호가 사라진다 — 아주 조금 줄여 그린다.
  const end = to - from >= Math.PI * 2 ? from + Math.PI * 2 - 0.0001 : to;
  const large = end - from > Math.PI ? 1 : 0;
  const x0 = cx + r * Math.cos(from);
  const y0 = cy + r * Math.sin(from);
  const x1 = cx + r * Math.cos(end);
  const y1 = cy + r * Math.sin(end);
  const xi0 = cx + inner * Math.cos(end);
  const yi0 = cy + inner * Math.sin(end);
  const xi1 = cx + inner * Math.cos(from);
  const yi1 = cy + inner * Math.sin(from);
  return `M${x0},${y0}A${r},${r} 0 ${large} 1 ${x1},${y1}L${xi0},${yi0}A${inner},${inner} 0 ${large} 0 ${xi1},${yi1}Z`;
}

export function DonutChart({
  slices,
  size = 200,
  thickness = 0.42,
  centerLabel,
  centerValue,
  onSliceClick,
  maxLegend = 8,
}: {
  slices: DonutSlice[];
  size?: number;
  /** 도넛 두께(반지름 대비 비율). */
  thickness?: number;
  centerLabel?: string;
  centerValue?: string;
  onSliceClick?: (slice: DonutSlice) => void;
  maxLegend?: number;
}) {
  const [hover, setHover] = useState<string | null>(null);

  const total = slices.reduce((sum, s) => sum + Math.max(s.value, 0), 0);
  if (total <= 0) {
    return (
      <div className="flex h-40 items-center justify-center text-[12px] font-semibold text-ink-faint">
        표시할 데이터가 없습니다
      </div>
    );
  }

  const r = size / 2;
  const inner = r * (1 - thickness);
  let angle = -Math.PI / 2; // 12시에서 시작
  const drawn = slices.map((slice, i) => {
    const sweep = (Math.max(slice.value, 0) / total) * Math.PI * 2;
    const path = arcPath(r, r, r, inner, angle, angle + sweep);
    angle += sweep;
    return {
      ...slice,
      path,
      color: slice.muted ? MUTED : PALETTE[i % PALETTE.length],
      pct: (slice.value / total) * 100,
    };
  });

  const legend = drawn.slice(0, maxLegend);

  return (
    // 좁으면 범례가 도넛 아래로 내려간다(@container 없이 flex-wrap 으로).
    <div className="flex flex-wrap items-center justify-center gap-4">
      <div className="relative shrink-0" style={{ width: size, height: size }}>
        <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
          {drawn.map((s) => (
            <path
              key={s.key}
              d={s.path}
              fill={s.color}
              stroke="#ffffff"
              strokeWidth="1.5"
              onMouseEnter={() => setHover(s.key)}
              onMouseLeave={() => setHover(null)}
              onClick={() => onSliceClick?.(s)}
              style={{
                cursor: onSliceClick ? "pointer" : "default",
                // 호버한 조각만 살짝 앞으로. 크기를 바꾸면 비중이 달라 보인다.
                opacity: hover && hover !== s.key ? 0.55 : 1,
                transition: "opacity 120ms",
              }}
            />
          ))}
        </svg>
        {/* 가운데 — 호버 중이면 그 조각을, 아니면 전체 요약을 보여준다. */}
        <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
          {hover ? (
            <>
              <span className="max-w-[70%] truncate text-[11px] font-bold text-ink-muted">
                {drawn.find((s) => s.key === hover)?.label}
              </span>
              <span className="text-[17px] font-extrabold tabular-nums text-ge-navy">
                {drawn.find((s) => s.key === hover)?.pct.toFixed(1)}%
              </span>
            </>
          ) : (
            <>
              {centerLabel && (
                <span className="text-[11px] font-bold text-ink-muted">
                  {centerLabel}
                </span>
              )}
              {centerValue && (
                <span className="text-[15px] font-extrabold tabular-nums text-ge-navy">
                  {centerValue}
                </span>
              )}
            </>
          )}
        </div>
      </div>

      <ul className="min-w-[150px] flex-1 space-y-1">
        {legend.map((s) => (
          <li key={s.key}>
            <button
              type="button"
              onClick={() => onSliceClick?.(s)}
              onMouseEnter={() => setHover(s.key)}
              onMouseLeave={() => setHover(null)}
              className={cn(
                "flex w-full items-center gap-2 rounded-lg px-1.5 py-1 text-left transition-colors",
                onSliceClick ? "hover:bg-canvas-soft" : "cursor-default",
                hover === s.key && "bg-canvas-soft",
              )}
            >
              <span
                className="h-2.5 w-2.5 shrink-0 rounded-full"
                style={{ background: s.color }}
              />
              <span className="min-w-0 flex-1 truncate text-[11px] font-bold text-ge-navy">
                {s.label}
              </span>
              <span className="shrink-0 text-[11px] font-bold tabular-nums text-ink-secondary">
                {s.pct.toFixed(1)}%
              </span>
            </button>
            {s.caption && (
              <span className="ml-[26px] block text-[10px] font-semibold text-ink-muted">
                {s.caption}
              </span>
            )}
          </li>
        ))}
        {drawn.length > maxLegend && (
          <li className="px-2 text-[11px] font-semibold text-ink-faint">
            외 {drawn.length - maxLegend}종목
          </li>
        )}
      </ul>
    </div>
  );
}
