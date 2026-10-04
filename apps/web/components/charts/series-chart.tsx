"use client";

import { useEffect, useMemo, useRef, useState } from "react";

// 시계열 한 개를 그리는 저수준 차트.
//
// 이 레포의 차트 관례를 따른다(ai-key-data/ai-line-chart.tsx 참고):
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
// 보조 계열(오른쪽 축). 팔레트의 BLUE — 메인 BROWN 과 명도·색상이 둘 다 갈린다.
const LINE2 = "#6390BF";

const PAD_L = 62;
const PAD_R = 10;
const PAD_T = 8;
const XAXIS_H = 20;

export type SeriesPoint = { date: string; value: number | null };

/** x 축 위 표식(★2026-10-04 — 입출금 날짜). `index` 는 `points` 의 순서. */
export type SeriesMarker = { index: number; label: string; tone: "up" | "down" };

/** 오른쪽 축에 따로 눈금을 두는 두 번째 계열. `values` 는 `points` 와 같은 순서다. */
export type SecondarySeries = {
  label: string;
  values: (number | null)[];
  tooltipFormat?: (v: number) => string;
};

/** 1·2·2.5·5 × 10ⁿ 중 raw 이상인 가장 작은 값. */
function niceStep(raw: number): number {
  const p = 10 ** Math.floor(Math.log10(raw));
  const f = raw / p;
  return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 2.5 ? 2.5 : f <= 5 ? 5 : 10) * p;
}

/** min~max 를 **정확히 segments 칸**의 딱 떨어지는 눈금으로 덮는다.
 *  ⚠️칸 수를 두 축이 같이 쓰는 이유: 격자선은 한 벌이라, 칸 수가 다르면 오른쪽
 *    눈금이 격자선과 어긋난 자리에 찍혀 읽을 수 없다. */
function niceScale(min: number, max: number, segments: number) {
  if (min === max) {
    const pad = Math.abs(min) * 0.05 || 1;
    min -= pad;
    max += pad;
  }
  let step = niceStep((max - min) / segments);
  for (;;) {
    const lo = Math.floor(min / step) * step;
    if (lo + step * segments >= max) return { min: lo, max: lo + step * segments };
    step = niceStep(step * 1.01);
  }
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
  label,
  secondary,
  markers,
}: {
  points: SeriesPoint[];
  height?: number;
  valueFormat?: (v: number) => string;
  tooltipFormat?: (p: SeriesPoint) => string;
  includeZero?: boolean;
  /** 메인 계열 이름. `secondary` 와 같이 쓸 때 범례에 뜬다. */
  label?: string;
  /** 오른쪽 축 계열. 있으면 두 축 모두 딱 떨어지는 눈금으로 맞춘다. */
  secondary?: SecondarySeries;
  /** 아래쪽에 찍는 작은 세모 — 커서를 대면 툴팁에 라벨이 붙는다. */
  markers?: SeriesMarker[];
}) {
  const { ref, width } = useWidth();
  const [hover, setHover] = useState<number | null>(null);

  // 두 축일 때는 오른쪽 눈금 자리와 위쪽 범례 자리를 더 연다.
  const padR = secondary ? PAD_L : PAD_R;
  const padT = secondary ? 22 : PAD_T;

  const model = useMemo(() => {
    const valid = points.filter((p) => p.value != null) as { date: string; value: number }[];
    if (valid.length === 0 || width === 0) return null;

    let min = Math.min(...valid.map((p) => p.value));
    let max = Math.max(...valid.map((p) => p.value));
    if (includeZero) {
      min = Math.min(min, 0);
      max = Math.max(max, 0);
    }
    const innerW = Math.max(width - PAD_L - padR, 1);
    const innerH = Math.max(height - padT - XAXIS_H, 1);
    const x = (i: number) =>
      PAD_L + (points.length === 1 ? innerW / 2 : (i / (points.length - 1)) * innerW);

    const values2 = (secondary?.values ?? []).filter((v): v is number => v != null);
    let ticks: number[];
    let ticks2: number[] = [];
    let y2: ((v: number) => number) | null = null;
    let path2 = "";
    if (secondary && values2.length > 0) {
      ({ min, max } = niceScale(min, max, 4));
      const s2 = niceScale(Math.min(...values2), Math.max(...values2), 4);
      y2 = (v: number) => padT + innerH - ((v - s2.min) / (s2.max - s2.min)) * innerH;
      ticks2 = [0, 0.25, 0.5, 0.75, 1].map((t) => s2.min + (s2.max - s2.min) * t);
      let open2 = false;
      secondary.values.forEach((v, i) => {
        if (v == null) {
          open2 = false;
          return;
        }
        path2 += `${open2 ? "L" : "M"}${x(i).toFixed(1)},${y2!(v).toFixed(1)}`;
        open2 = true;
      });
    } else if (min === max) {
      // 평평한 계열 — 위아래로 여유를 줘야 선이 축에 붙지 않는다.
      const pad = Math.abs(min) * 0.05 || 1;
      min -= pad;
      max += pad;
    }
    ticks = [0, 0.25, 0.5, 0.75, 1].map((t) => min + (max - min) * t);
    const y = (v: number) => padT + innerH - ((v - min) / (max - min)) * innerH;

    // 결측을 만나면 선을 끊는다(M 으로 다시 시작).
    // ★2026-10-04: 끊긴 구간마다 면을 **그 구간 끝에서** 바닥으로 내려 닫는다 — 예전에는 마지막
    //   점까지 대각선으로 이어 칠해져 없는 면이 생겼다. 앞뒤가 비어 있는 외딴 점은 점으로 찍는다.
    let path = "";
    let area = "";
    let open = false;
    let lastValid = -1;
    const isolated: number[] = [];
    const bottom = (padT + innerH).toFixed(1);
    points.forEach((p, i) => {
      if (p.value == null) {
        if (open) area += `L${x(lastValid).toFixed(1)},${bottom}`;
        open = false;
        return;
      }
      const prev = points[i - 1]?.value;
      const next = points[i + 1]?.value;
      if (prev == null && next == null) isolated.push(i);
      lastValid = i;
      const cmd = open ? "L" : "M";
      path += `${cmd}${x(i).toFixed(1)},${y(p.value).toFixed(1)}`;
      if (!open) area += `${area ? "Z" : ""}M${x(i).toFixed(1)},${(padT + innerH).toFixed(1)}`;
      area += `L${x(i).toFixed(1)},${y(p.value).toFixed(1)}`;
      open = true;
    });
    if (open) area += `L${x(lastValid).toFixed(1)},${bottom}`;
    if (area) area += "Z";

    return { min, max, x, y, path, area, ticks, innerH, y2, ticks2, path2, isolated };
  }, [points, width, height, includeZero, secondary, padR, padT]);

  const hovered = hover != null ? points[hover] : null;
  const hovered2 = hover != null ? (secondary?.values[hover] ?? null) : null;
  const hoveredMarker = hover != null ? markers?.find((m) => m.index === hover) : undefined;

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
            const innerW = Math.max(width - PAD_L - padR, 1);
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
                x2={width - padR}
                y1={model.y(t)}
                y2={model.y(t)}
                stroke={GRID}
              />
              <text
                x={PAD_L - 8}
                y={model.y(t) + 4}
                textAnchor="end"
                fontSize="11"
                fill={secondary ? LINE : AXIS_TEXT}
              >
                {valueFormat(t)}
              </text>
              {/* 오른쪽 눈금 — 같은 격자선에 찍는다(niceScale 이 칸 수를 맞춘다).
                  글자색을 선 색과 맞춰 어느 축이 어느 선인지 읽히게 한다. */}
              {model.y2 && model.ticks2[i] != null && (
                <text
                  x={width - padR + 8}
                  y={model.y(t) + 4}
                  textAnchor="start"
                  fontSize="11"
                  fill={LINE2}
                >
                  {valueFormat(model.ticks2[i])}
                </text>
              )}
            </g>
          ))}

          {secondary && (
            <g fontSize="11" fontWeight="700">
              <line x1={PAD_L} x2={PAD_L + 14} y1={9} y2={9} stroke={LINE} strokeWidth="2" />
              <text x={PAD_L + 18} y={13} fill={LINE}>
                {label ?? "왼쪽 축"}
              </text>
              <line
                x1={width - padR - 14}
                x2={width - padR}
                y1={9}
                y2={9}
                stroke={LINE2}
                strokeWidth="2"
              />
              <text x={width - padR - 18} y={13} fill={LINE2} textAnchor="end">
                {secondary.label}
              </text>
            </g>
          )}

          <path d={model.area} fill="url(#seriesFill)" />
          <path d={model.path} fill="none" stroke={LINE} strokeWidth="1.8" />
          {model.isolated.map((i) => (
            <circle key={i} cx={model.x(i)} cy={model.y(points[i].value!)} r="2.5" fill={LINE} />
          ))}
          {model.path2 && (
            <path d={model.path2} fill="none" stroke={LINE2} strokeWidth="1.8" />
          )}

          {/* 표식은 x 축 바로 위 — ▲ 입금(BLUE) · ▼ 출금(회색). */}
          {markers?.map((m) => {
            const cx = model.x(m.index);
            const base = padT + model.innerH;
            return (
              <path
                key={`${m.index}-${m.label}`}
                d={
                  m.tone === "up"
                    ? `M${cx - 4},${base} L${cx + 4},${base} L${cx},${base - 7} Z`
                    : `M${cx - 4},${base - 7} L${cx + 4},${base - 7} L${cx},${base} Z`
                }
                fill={m.tone === "up" ? LINE2 : CROSS}
              >
                <title>{m.label}</title>
              </path>
            );
          })}

          {hovered?.value != null && hover != null && (
            <>
              <line
                x1={model.x(hover)}
                x2={model.x(hover)}
                y1={padT}
                y2={padT + model.innerH}
                stroke={CROSS}
                strokeDasharray="3 3"
              />
              <circle cx={model.x(hover)} cy={model.y(hovered.value)} r="3.5" fill={LINE} />
              {model.y2 && hovered2 != null && (
                <circle cx={model.x(hover)} cy={model.y2(hovered2)} r="3.5" fill={LINE2} />
              )}
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
          {hoveredMarker && (
            <span className="ml-2 text-[#6390BF]">{hoveredMarker.label}</span>
          )}
          {secondary && (
            <span className="ml-2 tabular-nums text-[#6390BF]">
              {secondary.label}{" "}
              {hovered2 == null
                ? "—"
                : secondary.tooltipFormat
                  ? secondary.tooltipFormat(hovered2)
                  : valueFormat(hovered2)}
            </span>
          )}
        </div>
      )}
    </div>
  );
}
