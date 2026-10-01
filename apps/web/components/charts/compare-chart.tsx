"use client";

import { useMemo, useRef, useState } from "react";
import { cn } from "@/lib/utils";

// 여러 곡선을 한 축에 겹쳐 그리는 차트 — 벤치마크 비교용.
//
// ★`series-chart.tsx` 는 단일 시리즈 전용이라 비교선을 못 그린다. 그 파일을
//   일반화하는 대신 따로 뒀다 — 자산 추이 차트(단일)는 축 처리·툴팁 문구가
//   달라서, 하나로 합치면 양쪽 다 복잡해진다.
//
// ★색은 브랜드 팔레트 안에서만 쓴다(가이드 §8). 내 계좌는 BROWN(주인공),
//   벤치마크는 BLUE 계열·회색으로 물러난다.
//
// ⚠️값이 없는 점(null)은 **선을 끊는다.** 이어 버리면 없는 날의 움직임이 생긴다.

const MINE_COLOR = "#4C2C19";
const BENCH_COLORS = ["#6390BF", "#A6A6A6", "#C9A98C"];
const GRID = "#F2F2F2";
const AXIS_TEXT = "#7F7F7F";

const PAD_L = 46;
const PAD_R = 12;
const PAD_T = 10;
const PAD_B = 22;

export type CompareSeries = {
  name: string;
  /** 날짜별 값. null 이면 그 구간은 선이 끊긴다. */
  values: (number | null)[];
  emphasis?: boolean;
};

function useWidth() {
  const ref = useRef<HTMLDivElement | null>(null);
  const [width, setWidth] = useState(0);
  const observer = useRef<ResizeObserver | null>(null);

  const attach = (node: HTMLDivElement | null) => {
    ref.current = node;
    observer.current?.disconnect();
    if (!node) return;
    observer.current = new ResizeObserver((entries) => {
      setWidth(entries[0].contentRect.width);
    });
    observer.current.observe(node);
    setWidth(node.getBoundingClientRect().width);
  };

  return { attach, width };
}

export function CompareChart({
  dates,
  series,
  height = 280,
  valueFormat = (v: number) => `${v.toFixed(0)}`,
  legendFormat,
}: {
  dates: string[];
  series: CompareSeries[];
  height?: number;
  valueFormat?: (v: number) => string;
  /** 범례 숫자 형식. 없으면 축과 같다 — 축은 자리가 좁아 접은 단위(만)를 쓸 때 준다. */
  legendFormat?: (v: number) => string;
}) {
  const { attach, width } = useWidth();
  const [hover, setHover] = useState<number | null>(null);

  const model = useMemo(() => {
    if (width === 0 || dates.length === 0) return null;
    const all = series.flatMap((s) => s.values.filter((v): v is number => v != null));
    if (all.length === 0) return null;

    let min = Math.min(...all);
    let max = Math.max(...all);
    if (min === max) {
      min -= 1;
      max += 1;
    }
    // 위아래로 약간 여유를 둔다 — 선이 테두리에 붙으면 읽기 나쁘다.
    const pad = (max - min) * 0.08;
    min -= pad;
    max += pad;

    const innerW = Math.max(1, width - PAD_L - PAD_R);
    const innerH = Math.max(1, height - PAD_T - PAD_B);
    const x = (i: number) =>
      PAD_L + (dates.length === 1 ? innerW / 2 : (i / (dates.length - 1)) * innerW);
    const y = (v: number) => PAD_T + innerH - ((v - min) / (max - min)) * innerH;

    // ⚠️앞뒤가 다 null 인 **외딴 점**은 선이 될 수 없다. 예전에는 그냥 버려서
    //   값이 있는 날이 그래프에서 사라졌다 — 점으로 찍는다.
    const dots: { x: number; y: number }[][] = series.map(() => []);
    const paths = series.map((s, si) => {
      // null 에서 선을 끊는다 — 세그먼트를 나눠 그린다.
      const segments: string[] = [];
      let current: string[] = [];
      let lastIndex = -1;
      const close = () => {
        if (current.length > 1) segments.push(current.join(" "));
        else if (current.length === 1) {
          const v = s.values[lastIndex] as number;
          dots[si].push({ x: x(lastIndex), y: y(v) });
        }
        current = [];
      };
      s.values.forEach((v, i) => {
        if (v == null) {
          close();
          return;
        }
        current.push(`${current.length === 0 ? "M" : "L"} ${x(i)} ${y(v)}`);
        lastIndex = i;
      });
      close();
      return segments.join(" ");
    });

    const ticks = [0, 0.25, 0.5, 0.75, 1].map((t) => {
      const value = min + (max - min) * (1 - t);
      return { y: PAD_T + innerH * t, label: valueFormat(value) };
    });

    return { x, y, paths, dots, ticks, innerW };
  }, [width, height, dates, series, valueFormat]);

  const colorOf = (index: number, emphasis?: boolean) =>
    emphasis ? MINE_COLOR : BENCH_COLORS[index % BENCH_COLORS.length];

  return (
    <div ref={attach} className="w-full">
      {model && (
        <>
          <svg
            width={width}
            height={height}
            onMouseLeave={() => setHover(null)}
            onMouseMove={(e) => {
              const rect = e.currentTarget.getBoundingClientRect();
              const ratio = (e.clientX - rect.left - PAD_L) / model.innerW;
              const index = Math.round(ratio * (dates.length - 1));
              setHover(index >= 0 && index < dates.length ? index : null);
            }}
          >
            {model.ticks.map((t) => (
              <g key={t.y}>
                <line x1={PAD_L} x2={width - PAD_R} y1={t.y} y2={t.y} stroke={GRID} />
                <text
                  x={PAD_L - 6}
                  y={t.y + 3}
                  textAnchor="end"
                  fontSize={10}
                  fill={AXIS_TEXT}
                >
                  {t.label}
                </text>
              </g>
            ))}

            {series.map((s, i) => (
              <path
                key={s.name}
                d={model.paths[i]}
                fill="none"
                stroke={colorOf(i - (s.emphasis ? 0 : 1), s.emphasis)}
                strokeWidth={s.emphasis ? 2 : 1.25}
                strokeLinejoin="round"
              />
            ))}
            {series.map((s, i) =>
              model.dots[i].map((d) => (
                <circle
                  key={`${s.name}-${d.x}`}
                  cx={d.x}
                  cy={d.y}
                  r={2.5}
                  fill={colorOf(i - (s.emphasis ? 0 : 1), s.emphasis)}
                />
              )),
            )}

            {hover != null && (
              <line
                x1={model.x(hover)}
                x2={model.x(hover)}
                y1={PAD_T}
                y2={height - PAD_B}
                stroke="#A6A6A6"
                strokeDasharray="3 3"
              />
            )}

            <text x={PAD_L} y={height - 6} fontSize={10} fill={AXIS_TEXT}>
              {dates[0]}
            </text>
            <text
              x={width - PAD_R}
              y={height - 6}
              textAnchor="end"
              fontSize={10}
              fill={AXIS_TEXT}
            >
              {dates[dates.length - 1]}
            </text>
          </svg>

          <div className="mt-1.5 flex flex-wrap items-center gap-x-4 gap-y-1">
            {series.map((s, i) => {
              const value = hover == null ? s.values[s.values.length - 1] : s.values[hover];
              return (
                <span key={s.name} className="flex items-center gap-1.5">
                  <span
                    className="h-0.5 w-4 rounded-full"
                    style={{ background: colorOf(i - (s.emphasis ? 0 : 1), s.emphasis) }}
                  />
                  <span
                    className={cn(
                      "text-[11px]",
                      s.emphasis ? "font-extrabold text-ink" : "font-bold text-ink-secondary",
                    )}
                  >
                    {s.name}
                  </span>
                  <span className="text-[11px] font-bold tabular-nums text-ink-muted">
                    {value == null ? "—" : (legendFormat ?? valueFormat)(value)}
                  </span>
                </span>
              );
            })}
            {hover != null && (
              <span className="ml-auto text-[11px] font-bold tabular-nums text-ink-faint">
                {dates[hover]}
              </span>
            )}
          </div>
        </>
      )}
    </div>
  );
}
