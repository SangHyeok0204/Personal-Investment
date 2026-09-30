"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { EMDASH } from "@/components/format";

// [AI Key Data · S5] 날짜 x 축 다중 계열 선 차트.
//
// 관례는 macro-chart.tsx / timeseries-chart.tsx 와 같다(ResizeObserver 로 폭,
// viewBox 1:1, SVG 안은 raw hex, 바깥은 tailwind). 따로 둔 이유:
//   · macro-chart 는 **단일 계열·월 번호** 축이다 — 13개 CLI 를 한 판에 겹칠 수 없다.
//   · timeseries-chart 는 폭·높이를 부르는 쪽이 재서 넘겨야 하고, 계열마다 굵기·
//     음영·점선 구간·로그 축을 줄 수 없다(Epoch ARR 는 65B 와 0.4B 가 같이 있어
//     선형 축이면 7개 랩이 바닥에 눌린다).
//
// 색은 **엔티티가 정한다** — 부르는 쪽이 계열마다 color 를 박아 넘긴다. 이 차트는
// 순위를 보고 색을 다시 칠하지 않는다(필터로 계열 수가 바뀌어도 살아남은 선의 색이
// 그대로여야 눈이 따라간다).
//
// ⚠️점이 없는 날은 선을 끊지 않는다(일간 계열은 서버가 결측일을 비워 둘 뿐 드물다).
//   대신 `dashFrom` 이후 구간은 점선 — "집계가 덜 끝난 분기"가 하락처럼 읽히지 않게.

export interface ChartSeries {
  key: string;
  label: string;
  color: string;
  points: [string, number][];
  /** 선 굵기(기본 1.75). 강조 계열은 굵게, 배경 계열은 가늘게. */
  width?: number;
  /** step-after — "다음 공시가 올 때까지 이전 값 유지"(ARR·펀딩 같은 이벤트성 값). */
  step?: boolean;
  /** 선 아래를 옅게 채운다(누적 총량 한 줄에만). */
  area?: boolean;
  /** 이 날짜(포함) 이후 구간을 점선으로 — 부분 집계 표시. */
  dashFrom?: string | null;
  /** 툴팁에서 뺀다(배경 계열이 많을 때 툴팁이 길어지지 않게). */
  quiet?: boolean;
}

const GRID = "#F2F2F2";
const AXIS_TEXT = "#7F7F7F";
const CROSS = "#A6A6A6";

const PAD_R = 10;
const PAD_T = 8;
const XAXIS_H = 18;

const DAY = 86_400_000;
const toDay = (d: string) => Date.parse(`${d.slice(0, 10)}T00:00:00Z`) / DAY;

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

/** 오름차순 날짜 배열에서 t 이하 마지막 인덱스(없으면 -1). */
function onOrBefore(days: number[], t: number): number {
  let lo = 0;
  let hi = days.length - 1;
  let ans = -1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (days[mid] <= t) {
      ans = mid;
      lo = mid + 1;
    } else hi = mid - 1;
  }
  return ans;
}

export function AiLineChart({
  series,
  height = 220,
  fmt,
  axisFmt,
  log = false,
  padLeft = 46,
  ariaLabel,
  tooltipRows = 8,
}: {
  series: ChartSeries[];
  height?: number;
  /** 툴팁 값 표기. */
  fmt: (v: number) => string;
  /** 축 눈금 표기(생략하면 fmt). */
  axisFmt?: (v: number) => string;
  /** 로그 축 — 값이 자릿수 단위로 벌어진 계열(ARR·CLI 다운로드). 1 미만 점은 버린다. */
  log?: boolean;
  padLeft?: number;
  ariaLabel: string;
  /** 툴팁에 보일 최대 행 수(값 내림차순). */
  tooltipRows?: number;
}) {
  const { ref, width } = useWidth();
  const [hover, setHover] = useState<number | null>(null);
  const axis = axisFmt ?? fmt;

  const model = useMemo(() => {
    const clean = series.map((s) => {
      // 로그 축은 1 미만을 버린다 — 이 탭의 로그 계열(다운로드 수·달러)은 1 미만이
      // 출시 전 0 이 섞인 이평 꼬리뿐이라, 남기면 축이 0.1 까지 늘어난다.
      const pts = log ? s.points.filter((p) => p[1] >= 1) : s.points;
      return { ...s, pts, days: pts.map((p) => toDay(p[0])) };
    });
    const all = clean.flatMap((s) => s.pts);
    if (all.length === 0 || width === 0) return null;

    const innerW = Math.max(width - padLeft - PAD_R, 1);
    const innerH = Math.max(height - PAD_T - XAXIS_H, 1);
    const allDays = [...new Set(clean.flatMap((s) => s.days))].sort((a, b) => a - b);
    const d0 = allDays[0];
    const d1 = Math.max(allDays[allDays.length - 1], d0 + 1);
    const x = (d: number) => padLeft + ((d - d0) / (d1 - d0)) * innerW;

    const vals = all.map((p) => p[1]);
    let min = Math.min(...vals);
    let max = Math.max(...vals);
    const hasArea = clean.some((s) => s.area);

    let ticks: number[];
    let y: (v: number) => number;
    if (log) {
      const lo = Math.floor(Math.log10(min));
      const hi = Math.max(Math.ceil(Math.log10(max)), lo + 1);
      ticks = [];
      for (let e = lo; e <= hi; e++) ticks.push(10 ** e);
      y = (v: number) => PAD_T + innerH - ((Math.log10(v) - lo) / (hi - lo)) * innerH;
    } else {
      // 다운로드·도입률·H100e 는 전부 0 이상 — 0 을 바닥으로 둔다(바닥이 뜨면 증가폭이 과장된다).
      if (min >= 0) min = 0;
      if (hasArea) min = Math.min(min, 0);
      if (min === max) max = min + 1;
      const step = niceStep((max - min) / 4);
      const lo = Math.floor(min / step) * step;
      const hi = Math.ceil(max / step) * step;
      ticks = [];
      for (let t = lo; t <= hi + step / 2; t += step) ticks.push(Number(t.toPrecision(12)));
      y = (v: number) => PAD_T + innerH - ((v - lo) / (hi - lo)) * innerH;
    }
    const base = PAD_T + innerH;

    const paths = clean.map((s) => {
      let solid = "";
      let dashed = "";
      const cut = s.dashFrom ? toDay(s.dashFrom) : Infinity;
      let prev: [number, number] | null = null;
      s.pts.forEach((p, i) => {
        const px = x(s.days[i]);
        const py = y(p[1]);
        const inDash = s.days[i] >= cut;
        if (!prev) {
          solid += `M${px.toFixed(1)},${py.toFixed(1)}`;
        } else {
          const seg = s.step
            ? `L${px.toFixed(1)},${prev[1].toFixed(1)}L${px.toFixed(1)},${py.toFixed(1)}`
            : `L${px.toFixed(1)},${py.toFixed(1)}`;
          if (inDash) {
            dashed += `M${prev[0].toFixed(1)},${prev[1].toFixed(1)}${seg}`;
          } else {
            solid += seg;
          }
        }
        prev = [px, py];
      });
      // step 은 마지막 값을 오른쪽 끝까지 끌고 간다 — "지금도 그 값"으로 읽힌다.
      if (s.step && prev) {
        const last = prev as [number, number];
        const tail = `L${x(d1).toFixed(1)},${last[1].toFixed(1)}`;
        if (dashed) dashed += tail;
        else solid += tail;
      }
      let area = "";
      if (s.area && s.pts.length > 1) {
        area = `M${x(s.days[0]).toFixed(1)},${base}`;
        s.pts.forEach((p, i) => {
          area += `L${x(s.days[i]).toFixed(1)},${y(p[1]).toFixed(1)}`;
        });
        area += `L${x(s.days[s.days.length - 1]).toFixed(1)},${base}Z`;
      }
      return { solid, dashed, area };
    });

    // x 눈금 — 구간 길이에 맞춰 월/분기/연.
    const spanDays = d1 - d0;
    const first = new Date(d0 * DAY);
    const monthsStep =
      spanDays > 365 * 3 ? 12 : spanDays > 365 * 1.2 ? 6 : spanDays > 200 ? 3 : spanDays > 70 ? 1 : 0;
    const xTicks: { d: number; label: string }[] = [];
    if (monthsStep > 0) {
      let cur = new Date(Date.UTC(first.getUTCFullYear(), first.getUTCMonth() + 1, 1));
      while (cur.getUTCMonth() % monthsStep !== 0) {
        cur = new Date(Date.UTC(cur.getUTCFullYear(), cur.getUTCMonth() + 1, 1));
      }
      while (cur.getTime() / DAY <= d1) {
        const yy = String(cur.getUTCFullYear()).slice(2);
        const mm = String(cur.getUTCMonth() + 1).padStart(2, "0");
        xTicks.push({
          d: cur.getTime() / DAY,
          label: monthsStep === 12 ? String(cur.getUTCFullYear()) : `${yy}.${mm}`,
        });
        cur = new Date(Date.UTC(cur.getUTCFullYear(), cur.getUTCMonth() + monthsStep, 1));
      }
    } else {
      const n = 4;
      for (let i = 0; i <= n; i++) {
        const d = Math.round(d0 + ((d1 - d0) * i) / n);
        const dt = new Date(d * DAY);
        xTicks.push({ d, label: `${dt.getUTCMonth() + 1}/${dt.getUTCDate()}` });
      }
    }

    return { clean, allDays, d0, d1, x, y, ticks, innerW, innerH, paths, xTicks, base };
  }, [series, width, height, log, padLeft]);

  const hoverDay = model && hover != null ? model.allDays[hover] : null;
  const hoverRows = useMemo(() => {
    if (!model || hoverDay == null) return [];
    const rows: { key: string; label: string; color: string; v: number; py: number }[] = [];
    for (const s of model.clean) {
      if (s.quiet) continue;
      const i = onOrBefore(s.days, hoverDay);
      if (i < 0) continue;
      // 선 계열은 그 날 값이 없으면(범위 밖) 비운다. step 은 이전 값을 유지.
      if (!s.step && s.days[i] !== hoverDay && hoverDay > s.days[s.days.length - 1]) continue;
      const v = s.pts[i][1];
      rows.push({ key: s.key, label: s.label, color: s.color, v, py: model.y(v) });
    }
    return rows.sort((a, b) => b.v - a.v);
  }, [model, hoverDay]);

  const hx = model && hoverDay != null ? model.x(hoverDay) : 0;
  const hoverDate =
    hoverDay != null ? new Date(hoverDay * DAY).toISOString().slice(0, 10) : null;

  return (
    <div ref={ref} className="relative w-full" style={{ height }}>
      {model && (
        <svg
          width={width}
          height={height}
          viewBox={`0 0 ${width} ${height}`}
          role="img"
          aria-label={ariaLabel}
          onMouseLeave={() => setHover(null)}
          onMouseMove={(e) => {
            const box = e.currentTarget.getBoundingClientRect();
            const rel = (e.clientX - box.left - padLeft) / model.innerW;
            const t = model.d0 + Math.min(Math.max(rel, 0), 1) * (model.d1 - model.d0);
            const ds = model.allDays;
            let i = onOrBefore(ds, t);
            if (i < 0) i = 0;
            if (i < ds.length - 1 && ds[i + 1] - t < t - ds[i]) i += 1;
            setHover(i);
          }}
        >
          {model.ticks.map((t) => (
            <g key={t}>
              <line
                x1={padLeft}
                x2={width - PAD_R}
                y1={model.y(t)}
                y2={model.y(t)}
                stroke={GRID}
              />
              <text
                x={padLeft - 6}
                y={model.y(t) + 3.5}
                textAnchor="end"
                fontSize="10"
                fill={AXIS_TEXT}
                style={{ fontVariantNumeric: "tabular-nums" }}
              >
                {axis(t)}
              </text>
            </g>
          ))}

          {model.xTicks.map((t) => (
            <text
              key={t.d}
              x={model.x(t.d)}
              y={height - 4}
              textAnchor="middle"
              fontSize="10"
              fill={AXIS_TEXT}
              style={{ fontVariantNumeric: "tabular-nums" }}
            >
              {t.label}
            </text>
          ))}

          {model.clean.map((s, i) =>
            model.paths[i].area ? (
              <path key={`a-${s.key}`} d={model.paths[i].area} fill={s.color} fillOpacity={0.1} />
            ) : null,
          )}

          {model.clean.map((s, i) => (
            <g key={s.key}>
              <path
                d={model.paths[i].solid}
                fill="none"
                stroke={s.color}
                strokeWidth={s.width ?? 1.75}
                strokeLinejoin="round"
                strokeLinecap="round"
              />
              {model.paths[i].dashed && (
                <path
                  d={model.paths[i].dashed}
                  fill="none"
                  stroke={s.color}
                  strokeWidth={s.width ?? 1.75}
                  strokeDasharray="3 3"
                  strokeLinecap="round"
                />
              )}
            </g>
          ))}

          {hoverDay != null && (
            <g style={{ pointerEvents: "none" }}>
              <line
                x1={hx}
                x2={hx}
                y1={PAD_T}
                y2={model.base}
                stroke={CROSS}
                strokeDasharray="3 3"
              />
              {hoverRows.map((r) => (
                <circle
                  key={r.key}
                  cx={hx}
                  cy={r.py}
                  r="3.5"
                  fill={r.color}
                  stroke="#FFFFFF"
                  strokeWidth="2"
                />
              ))}
            </g>
          )}
        </svg>
      )}

      {hoverDate && hoverRows.length > 0 && (
        <div
          className="pointer-events-none absolute top-0 z-10 min-w-[150px] rounded-lg bg-white/95 px-2.5 py-1.5 shadow-panel ring-1 ring-hairline"
          style={{
            left: hx,
            transform: hx > width / 2 ? "translateX(calc(-100% - 12px))" : "translateX(12px)",
          }}
        >
          <div className="mb-0.5 text-[11px] font-bold tabular-nums text-ink-muted">
            {hoverDate}
          </div>
          {hoverRows.slice(0, tooltipRows).map((r) => (
            <div key={r.key} className="flex items-center gap-1.5 text-[11.5px] leading-[1.45]">
              <span
                className="inline-block h-[3px] w-2.5 shrink-0 rounded-full"
                style={{ background: r.color }}
              />
              <span className="truncate text-ink-secondary">{r.label}</span>
              <b className="ml-auto pl-3 tabular-nums text-ink">
                {Number.isFinite(r.v) ? fmt(r.v) : EMDASH}
              </b>
            </div>
          ))}
          {hoverRows.length > tooltipRows && (
            <div className="text-[10.5px] text-ink-faint">외 {hoverRows.length - tooltipRows}개</div>
          )}
        </div>
      )}
    </div>
  );
}
