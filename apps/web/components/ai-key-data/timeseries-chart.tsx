"use client";

import { useMemo, useState } from "react";
import { EMDASH } from "@/components/stock-monitor/format";
import type { AiSeries } from "@/lib/api";

// [AI Key Data] AI 사용량·Epoch 카드 공용 저수준 차트.
// 렌더 관례는 rate-chart-card.tsx / compute-index-card.tsx 와 같다(ResizeObserver
// + viewBox 를 px 와 1:1, SVG 는 raw hex, 바깥은 tailwind). 다만 이 두 카드는
// 그 관례만으로 못 푸는 것 둘을 더 다뤄서 헬퍼를 공용으로 뺐다(이 레포는 보통
// 차트 헬퍼를 카드마다 복붙하지만, 아래 둘은 그 선을 넘는다고 판단):
//   ① kind: "line" | "step" | "scatter" — Epoch 3종은 3년에 수십 행짜리 뉴스
//      이벤트라 연속선으로 그리면 없는 정밀도를 만든다(ws2 설계 §2.2). step 은
//      "다음 소식이 올 때까지 이전 값 유지"(step-after)로 그린다.
//   ② point 값의 null — "결측"이지 0 이 아니다(예: top-50 순위 이탈). 선을
//      잇지 않고 끊는다. incomplete_from 이 있으면 그 날짜부터는 부분 집계라
//      점을 속이 빈 원으로 구분한다(마지막 버킷이 하락처럼 보이는 착시 방지).
//   ③ anomaly_dates — 그 날짜의 값이 소급 정정된 점(예: VS Code 설치수가 MS
//      쪽 재계산으로 줄어든 날). rose 로 강조해 **숨기지 않고 보이게** 만든다
//      (2026-08-28 팀 지시 — 0으로 자르거나 안 그리면 관측 대상 자체가 사라진다).
//
// 어떤 계열을 그릴지(예: raw/ma7 토글)는 부르는 쪽이 정한다 — 이 컴포넌트는
// 받은 series 를 그대로 그릴 뿐 자기 상태를 갖지 않는다(RateChartCard 와 동형).

const GRID = "#EDF0F5";
const AXIS_TEXT = "#8a94a6";
const CROSS = "#B7C0CE";
const ANOMALY = "#e11d48"; // rose — 소급 정정 표시. 색 규약: rose=조치 필요(주목)

const PAD_L = 46; // y 라벨 — 토큰 수치(T/B)가 rate-chart-card 보다 길어 6px 더 준다
const PAD_R = 8;
const PAD_T = 4;
const XAXIS_H = 14;

const day = (d: string) => Date.parse(`${d}T00:00:00Z`) / 86_400_000;

// 뒤에서부터 첫 non-null 값 — API 의 `stats.last` 가 raw 기준인지 ma7 기준인지
// 확신할 수 없을 때(실측 계약이 필드마다 다르다) 계열 자신의 points 에서 직접
// 구한다. 두 카드(ai-usage-card·epoch-card)가 공용으로 쓴다.
export function lastValue(points: [string, number | null][]): number | null {
  for (let i = points.length - 1; i >= 0; i--) {
    const v = points[i][1];
    if (v != null) return v;
  }
  return null;
}

function niceTicks(lo: number, hi: number, count: number): number[] {
  const raw = (hi - lo) / count;
  if (!Number.isFinite(raw) || raw <= 0) return [lo];
  const mag = 10 ** Math.floor(Math.log10(Math.abs(raw)));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? 10 * mag;
  const out: number[] = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) out.push(+v.toFixed(10));
  return out;
}

// null 에서 끊어 subpath 배열을 낸다. step 은 이전 값을 다음 x 까지 수평으로
// 끌고 간 뒤 수직으로 다음 값에 붙는다(step-after) — 계단식 이벤트(매출·펀딩
// 등)를 "다음 공시가 올 때까지 유지"로 읽는 게 정직하다.
function buildPaths(
  points: [string, number | null][],
  kind: AiSeries["kind"],
  X: (d: string) => number,
  Y: (v: number) => number,
): string[] {
  if (kind === "scatter") return [];
  const segs: string[] = [];
  let cur = "";
  let prevY = 0;
  for (const [d, v] of points) {
    if (v == null) {
      if (cur) segs.push(cur);
      cur = "";
      continue;
    }
    const x = X(d);
    const y = Y(v);
    if (!cur) {
      cur = `M${x.toFixed(1)},${y.toFixed(1)}`;
    } else if (kind === "step") {
      cur += ` L${x.toFixed(1)},${prevY.toFixed(1)} L${x.toFixed(1)},${y.toFixed(1)}`;
    } else {
      cur += ` L${x.toFixed(1)},${y.toFixed(1)}`;
    }
    prevY = y;
  }
  if (cur) segs.push(cur);
  return segs;
}

export function TimeSeriesChart({
  series,
  w,
  h,
  fmt,
  colors,
}: {
  series: AiSeries[];
  w: number;
  h: number;
  fmt: (v: number) => string;
  colors: string[];
}) {
  const [hoverX, setHoverX] = useState<string | null>(null);

  const plotW = Math.max(1, w - PAD_L - PAD_R);
  const plotH = Math.max(12, h - PAD_T - XAXIS_H);
  const py1 = PAD_T + plotH;

  const { x0, x1, yLo, yHi, dates, lookup } = useMemo(() => {
    const ds = series.flatMap((s) => s.points.map((p) => day(p[0])));
    const vs = series
      .flatMap((s) => s.points.map((p) => p[1]))
      .filter((v): v is number => v != null && Number.isFinite(v));
    const lo = vs.length ? Math.min(...vs) : 0;
    const hi = vs.length ? Math.max(...vs) : 1;
    // 위아래 여백 4% — rate-chart-card.tsx 와 같은 비율(2026-08-28 "빈 공간 없이" 지시).
    const pad = (hi - lo) * 0.04 || Math.abs(hi) * 0.04 || 1;
    const uniq = [...new Set(series.flatMap((s) => s.points.map((p) => p[0])))].sort();
    return {
      x0: ds.length ? Math.min(...ds) : 0,
      x1: ds.length ? Math.max(...ds) : 1,
      yLo: lo - pad,
      yHi: hi + pad,
      dates: uniq,
      lookup: series.map((s) => new Map(s.points)),
    };
  }, [series]);

  const X = (d: string) => PAD_L + ((day(d) - x0) / (x1 - x0 || 1)) * plotW;
  const Y = (v: number) => py1 - ((v - yLo) / (yHi - yLo || 1)) * plotH;

  // x축 눈금 — 구간이 900일을 넘으면(Epoch 3년) 연 단위, 아니면 월 단위(±2개월).
  const xTicks = useMemo(() => {
    const spanDays = x1 - x0;
    const out: string[] = [];
    if (spanDays > 900) {
      const y0 = new Date((x0 + 0.5) * 86_400_000).getUTCFullYear();
      const y1 = new Date((x1 + 0.5) * 86_400_000).getUTCFullYear();
      for (let y = y0 + 1; y <= y1; y++) out.push(`${y}-01-01`);
    } else if (dates.length > 0) {
      let cur = new Date(`${dates[0]}T00:00:00Z`);
      cur = new Date(Date.UTC(cur.getUTCFullYear(), cur.getUTCMonth() + 1, 1));
      const end = new Date((x1 + 0.5) * 86_400_000);
      const stride = spanDays > 240 ? 2 : 1;
      while (cur <= end) {
        out.push(cur.toISOString().slice(0, 10));
        cur = new Date(Date.UTC(cur.getUTCFullYear(), cur.getUTCMonth() + stride, 1));
      }
    }
    return out;
  }, [x0, x1, dates]);

  const onMove = (e: React.MouseEvent<SVGSVGElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    if (r.width <= 0 || dates.length === 0) return;
    const t = x0 + (((e.clientX - r.left) / r.width) * w - PAD_L) / plotW * (x1 - x0);
    let best = dates[0];
    let bd = Infinity;
    for (const d of dates) {
      const g = Math.abs(day(d) - t);
      if (g < bd) {
        bd = g;
        best = d;
      }
    }
    setHoverX(best);
  };

  const hx = hoverX ? X(hoverX) : 0;

  return (
    <div className="relative h-full w-full">
      <svg
        width="100%"
        height={h}
        viewBox={`0 0 ${w} ${h}`}
        style={{ display: "block" }}
        onMouseMove={onMove}
        onMouseLeave={() => setHoverX(null)}
        role="img"
        aria-label={series.map((s) => s.label).join(", ")}
      >
        {niceTicks(yLo, yHi, 3).map((v) => {
          const y = Y(v);
          if (y < PAD_T - 0.5 || y > py1 + 0.5) return null;
          return (
            <g key={v}>
              <line x1={PAD_L} y1={y} x2={PAD_L + plotW} y2={y} stroke={GRID} strokeWidth={1} />
              <text
                x={PAD_L - 5}
                y={y + 3}
                fontSize={9.5}
                fill={AXIS_TEXT}
                textAnchor="end"
                style={{ fontVariantNumeric: "tabular-nums" }}
              >
                {fmt(v)}
              </text>
            </g>
          );
        })}

        {series.map((s, i) => {
          const color = colors[i % colors.length];
          const paths = buildPaths(s.points, s.kind, X, Y);
          return (
            <g key={s.key}>
              {paths.map((d, j) => (
                <path
                  key={j}
                  d={d}
                  fill="none"
                  stroke={color}
                  strokeWidth={1.5}
                  strokeLinejoin="round"
                  strokeLinecap="round"
                />
              ))}
              {/* 점: scatter 는 전 구간, line/step 은 incomplete·anomaly 구간의
                  점만 찍는다(빽빽한 일별 시계열에 점을 다 찍으면 선이 안 보인다). */}
              {s.points.map(([d, v]) => {
                if (v == null) return null;
                const incomplete = s.incomplete_from != null && d >= s.incomplete_from;
                const anomaly = s.anomaly_dates?.includes(d) ?? false;
                if (s.kind !== "scatter" && !incomplete && !anomaly) return null;
                return (
                  <circle
                    key={d}
                    cx={X(d)}
                    cy={Y(v)}
                    r={s.kind === "scatter" || anomaly ? 3.4 : 2.6}
                    fill={anomaly ? ANOMALY : incomplete ? "#ffffff" : color}
                    stroke={anomaly ? ANOMALY : color}
                    strokeWidth={1.6}
                  />
                );
              })}
            </g>
          );
        })}

        {xTicks.map((d) => (
          <text
            key={d}
            x={X(d)}
            y={h - 4}
            fontSize={9}
            fill={AXIS_TEXT}
            textAnchor="middle"
            style={{ fontVariantNumeric: "tabular-nums" }}
          >
            {d.slice(2, 7).replace("-", ".")}
          </text>
        ))}

        {hoverX ? (
          <g style={{ pointerEvents: "none" }}>
            <line x1={hx} y1={PAD_T} x2={hx} y2={py1} stroke={CROSS} strokeWidth={1} />
            {series.map((s, i) => {
              const v = lookup[i].get(hoverX);
              return v == null ? null : (
                <circle
                  key={s.key}
                  cx={hx}
                  cy={Y(v)}
                  r={3.2}
                  fill="#ffffff"
                  stroke={colors[i % colors.length]}
                  strokeWidth={2}
                />
              );
            })}
          </g>
        ) : null}
      </svg>

      {hoverX ? (
        <div
          className="pointer-events-none absolute top-1 z-10 rounded-lg border border-hairline bg-canvas/95 px-2.5 py-1.5 shadow-panel"
          style={{
            left: hx,
            transform: hx > w / 2 ? "translateX(calc(-100% - 10px))" : "translateX(10px)",
          }}
        >
          <div className="mb-0.5 text-[10px] tabular-nums text-ink-muted">{hoverX}</div>
          {series.map((s, i) => {
            const v = lookup[i].get(hoverX);
            return (
              <div key={s.key} className="flex items-center gap-1.5 text-[11px] leading-tight">
                <span
                  className="inline-block h-2 w-2 shrink-0 rounded-sm"
                  style={{ background: colors[i % colors.length] }}
                />
                <span className="text-ink-muted">{s.label}</span>
                <b className="ml-auto pl-2 tabular-nums text-ink">
                  {v == null ? EMDASH : fmt(v)}
                </b>
              </div>
            );
          })}
        </div>
      ) : null}
    </div>
  );
}
