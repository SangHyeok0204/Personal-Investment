"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { getPriceBoard, type PriceBoard, type PriceCatKey } from "@/lib/api";
import { EMDASH } from "@/components/stock-monitor/format";
import { cn } from "@/lib/utils";

// [가격 모니터 · 차트] — 가운데 3~4번째 칸, 위 1행(2×1). 왼쪽 표와 **같은 쿼리**를
// 보고(자산군 탭 연동), 표에서 클릭한 시장의 3년 주간 종가를 그린다.
//
// ★한 줄만 그리는 이유: 자산군 하나에 최대 42개 시장이라 전부 그리면 스파게티가 되고,
//   스케일도 제각각(KOSPI 400 vs 닛케이 40,000)이라 한 축에 못 얹는다. "여러 자산
//   동시 관찰"은 왼쪽 표가 하고, 차트는 고른 하나를 자세히 본다.
// ★hover 하면 그 주의 날짜·값을 툴팁으로 — AI Key Data 카드와 같은 방식.
// 렌더 관례도 같다: ResizeObserver + viewBox 를 px 와 1:1(글자 안 늘어남).

const POLL_MS = 600_000;

const LINE = "#4a7ab5";
const AREA = "rgba(74,122,181,0.10)";
const GRID = "#EDF0F5";
const AXIS_TEXT = "#8a94a6";
const CROSS = "#B7C0CE";

const PAD_L = 46;
const PAD_R = 10;
const PAD_T = 8;
const XAXIS_H = 16;

const day = (d: string) => Date.parse(`${d}T00:00:00Z`) / 86_400_000;

function niceTicks(lo: number, hi: number, count: number): number[] {
  const raw = (hi - lo) / count;
  if (!Number.isFinite(raw) || raw <= 0) return [lo];
  const mag = 10 ** Math.floor(Math.log10(Math.abs(raw)));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? 10 * mag;
  const out: number[] = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) out.push(+v.toFixed(10));
  return out;
}

function Chart({
  points,
  w,
  h,
  fmt,
}: {
  points: [string, number][];
  w: number;
  h: number;
  fmt: (v: number) => string;
}) {
  const [hi, setHi] = useState<number | null>(null);

  const plotW = Math.max(1, w - PAD_L - PAD_R);
  const plotH = Math.max(12, h - PAD_T - XAXIS_H);
  const py1 = PAD_T + plotH;

  const { x0, x1, yLo, yHi } = useMemo(() => {
    const ds = points.map((p) => day(p[0]));
    const vs = points.map((p) => p[1]);
    const lo = Math.min(...vs);
    const hiV = Math.max(...vs);
    const pad = (hiV - lo) * 0.06 || Math.abs(hiV) * 0.02 || 1;
    return { x0: Math.min(...ds), x1: Math.max(...ds), yLo: lo - pad, yHi: hiV + pad };
  }, [points]);

  const X = (d: number) => PAD_L + ((d - x0) / (x1 - x0 || 1)) * plotW;
  const Y = (v: number) => py1 - ((v - yLo) / (yHi - yLo)) * plotH;

  const path = points
    .map((p, i) => `${i ? "L" : "M"}${X(day(p[0])).toFixed(1)},${Y(p[1]).toFixed(1)}`)
    .join(" ");
  // 면적을 옅게 깔면 한 줄짜리 차트가 허전하지 않고 추세 방향이 먼저 읽힌다.
  const area = `${path} L${X(day(points[points.length - 1][0])).toFixed(1)},${py1} L${X(day(points[0][0])).toFixed(1)},${py1} Z`;

  const xTicks = useMemo(() => {
    const out: string[] = [];
    const y0 = new Date((x0 + 0.5) * 86_400_000).getUTCFullYear();
    const y1 = new Date((x1 + 0.5) * 86_400_000).getUTCFullYear();
    for (let y = y0 + 1; y <= y1; y++) out.push(`${y}-01-01`);
    return out;
  }, [x0, x1]);

  const onMove = (e: React.MouseEvent<SVGSVGElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    if (r.width <= 0) return;
    const t = x0 + (((e.clientX - r.left) / r.width) * w - PAD_L) / plotW * (x1 - x0);
    let best = 0;
    let bd = Infinity;
    points.forEach((p, i) => {
      const g = Math.abs(day(p[0]) - t);
      if (g < bd) {
        bd = g;
        best = i;
      }
    });
    setHi(best);
  };

  const hp = hi == null ? null : points[hi];

  return (
    <div className="relative h-full w-full">
      <svg
        width="100%"
        height={h}
        viewBox={`0 0 ${w} ${h}`}
        style={{ display: "block" }}
        onMouseMove={onMove}
        onMouseLeave={() => setHi(null)}
        role="img"
        aria-label="선택 시장 3년 주간 종가"
      >
        {niceTicks(yLo, yHi, 4).map((v) => {
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

        <path d={area} fill={AREA} stroke="none" />
        <path d={path} fill="none" stroke={LINE} strokeWidth={1.8}
              strokeLinejoin="round" strokeLinecap="round" />

        {xTicks.map((d) => (
          <text key={d} x={X(day(d))} y={h - 4} fontSize={9.5} fill={AXIS_TEXT}
                textAnchor="middle" style={{ fontVariantNumeric: "tabular-nums" }}>
            {d.slice(0, 4)}
          </text>
        ))}

        {hp ? (
          <g style={{ pointerEvents: "none" }}>
            <line x1={X(day(hp[0]))} y1={PAD_T} x2={X(day(hp[0]))} y2={py1}
                  stroke={CROSS} strokeWidth={1} />
            <circle cx={X(day(hp[0]))} cy={Y(hp[1])} r={4}
                    fill="#ffffff" stroke={LINE} strokeWidth={2} />
          </g>
        ) : null}
      </svg>

      {hp ? (
        <div
          className="pointer-events-none absolute top-1 z-10 rounded-lg border border-hairline bg-canvas/95 px-2.5 py-1.5 shadow-panel"
          style={{
            left: X(day(hp[0])),
            transform:
              X(day(hp[0])) > w / 2 ? "translateX(calc(-100% - 10px))" : "translateX(10px)",
          }}
        >
          <div className="text-[10px] tabular-nums text-ink-muted">{hp[0]}</div>
          <div className="text-[13px] font-extrabold tabular-nums text-ink">{fmt(hp[1])}</div>
        </div>
      ) : null}
    </div>
  );
}

export function PriceChartCard({
  cat,
  selected,
}: {
  cat: PriceCatKey;
  selected: string | null;
}) {
  const { data, isLoading, isError } = useQuery<PriceBoard>({
    queryKey: ["price-board", cat], // 표 카드와 같은 키 → fetch 는 한 번
    queryFn: () => getPriceBoard(cat),
    refetchInterval: POLL_MS,
  });

  const wrapRef = useRef<HTMLDivElement>(null);
  const [box, setBox] = useState({ w: 0, h: 0 });
  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const read = () => setBox({ w: el.clientWidth, h: el.clientHeight });
    read();
    const ro = new ResizeObserver(read);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const isYield = !!data?.is_yield;
  // 탭을 바꾸면 선택이 그 자산군에 없을 수 있다 — 그땐 첫 시장으로 떨어진다.
  const series =
    data?.series.find((s) => s.key === selected) ?? data?.series[0] ?? null;
  const row = data?.rows.find((r) => r.key === series?.key) ?? null;

  const fmt = (v: number) =>
    isYield
      ? `${v.toFixed(2)}%`
      : v.toLocaleString("en-US", {
          minimumFractionDigits: Math.abs(v) >= 1000 ? 0 : 2,
          maximumFractionDigits: Math.abs(v) >= 1000 ? 0 : 2,
        });

  return (
    <section className="lg:col-span-2 flex min-h-0 flex-col rounded-xl border border-hairline bg-canvas">
      <header className="flex items-center gap-2 border-b border-hairline px-3 py-1.5">
        <h2 className="shrink-0 text-[13px] font-extrabold text-ink">
          {row?.label ?? "가격 추이"}
        </h2>
        <span className="min-w-0 truncate text-[11px] text-ink-muted">
          {data?.cat_label ?? ""}
          {row?.sub ? ` · ${row.sub}` : ""} · 3년 주간
        </span>
        {row ? (
          <span className="ml-auto shrink-0 text-[12px] font-extrabold tabular-nums text-ink">
            {fmt(row.price)}
          </span>
        ) : null}
      </header>

      <div ref={wrapRef} className="min-h-0 flex-1 px-1 pb-0.5 pt-0.5">
        {isLoading ? (
          <Center msg="불러오는 중…" />
        ) : isError ? (
          <Center msg="collector 에 못 닿았습니다." tone="text-rose-600" />
        ) : !series || series.points.length < 2 ? (
          <Center
            msg={data?.note ?? "표에서 시장을 고르면 추이가 표시됩니다."}
            tone={data?.note ? "text-amber-600" : undefined}
          />
        ) : box.w > 0 && box.h > 0 ? (
          <Chart points={series.points} w={box.w} h={box.h} fmt={fmt} />
        ) : null}
      </div>
    </section>
  );
}

function Center({ msg, tone }: { msg: string; tone?: string }) {
  return (
    <div className="flex h-full items-center justify-center px-6 text-center">
      <span className={cn("text-[12px] font-semibold leading-relaxed text-ink-muted", tone)}>
        {msg}
      </span>
    </div>
  );
}
