"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { getRateTopics, type RateSeries, type RateTopics } from "@/lib/api";
import { EMDASH } from "@/components/stock-monitor/format";
import { cn } from "@/lib/utils";

// [금리 주제 차트] — 금리_2.xlsx 의 시계열 주제(인플레·WTI·ADP·FOMC확률)를 그리는
// 공용 카드. 네 카드가 모양이 같아서 하나로 묶었다(이 레포는 차트를 파일마다 복붙하는
// 관례지만, 같은 payload·같은 축·같은 범례를 네 번 베끼는 건 값이 없다).
//
// ★한 카드 안의 계열은 **단위가 같은 것들만** 넣는다(인플레는 전부 %, WTI 는 전부
//   $/bbl). 그래서 y축이 하나여도 정직하다 — 단위가 다르면 카드를 나눈다.
// ★스케일이 크게 다른 계열(WTI 의 CL1−CL12 스프레드)은 차트에 넣지 않고 `statKeys`
//   로 헤더 숫자만 띄운다. 같이 그리면 바닥에 눌려 안 읽힌다.
//
// 렌더 관례는 컴퓨팅 지수 카드와 같다(ResizeObserver + viewBox 를 px 와 1:1).

const POLL_MS = 600_000; // 원천이 수기 복사본이라 자주 물을 이유가 없다

// 하우스 팔레트 4슬롯 — 흰 캔버스 기준 CVD·명도 검증 통과.
// 주황은 대비 2.65:1 이라 색만으로 두지 않고 범례에 이름+현재값을 같이 띄운다.
const PALETTE = ["#4a7ab5", "#e8871e", "#2aa876", "#7b5ea7"];

const GRID = "#EDF0F5";
const AXIS_TEXT = "#8a94a6";
const CROSS = "#B7C0CE";

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

const PAD_L = 40; // y 라벨
const PAD_R = 6;
const PAD_T = 4;
const XAXIS_H = 14;

// 제목 띠 강조색은 tailwind 토큰 `ge-header`(#483629) — 2026-08-28 카드 6장이
// 같이 쓰게 되면서 raw hex 를 토큰으로 승격했다.

export type RateTopicKey = "inflation" | "wti" | "adp" | "fomc_prob";

function Chart({
  series,
  w,
  h,
  fmt,
}: {
  series: RateSeries[];
  w: number;
  h: number;
  fmt: (v: number) => string;
}) {
  const [hoverX, setHoverX] = useState<string | null>(null);

  const plotW = Math.max(1, w - PAD_L - PAD_R);
  const plotH = Math.max(12, h - PAD_T - XAXIS_H);
  const py1 = PAD_T + plotH;

  const { x0, x1, yLo, yHi, dates, lookup } = useMemo(() => {
    const ds = series.flatMap((s) => s.points.map((p) => day(p[0])));
    const vs = series.flatMap((s) => s.points.map((p) => p[1]));
    const lo = Math.min(...vs);
    const hi = Math.max(...vs);
    // 위아래 여백 4% — 선이 테두리에 닿지 않을 만큼만 준다(2026-08-28 10%→4%,
    // "빈 공간 없이" 지시). 더 줄이면 최고·최저점이 잘려 보인다.
    const pad = (hi - lo) * 0.04 || 1;
    const uniq = [...new Set(series.flatMap((s) => s.points.map((p) => p[0])))].sort();
    return {
      x0: Math.min(...ds),
      x1: Math.max(...ds),
      yLo: lo - pad,
      yHi: hi + pad,
      dates: uniq,
      lookup: series.map((s) => new Map(s.points)),
    };
  }, [series]);

  const X = (d: number) => PAD_L + ((d - x0) / (x1 - x0 || 1)) * plotW;
  const Y = (v: number) => py1 - ((v - yLo) / (yHi - yLo)) * plotH;

  // x축 — 연 단위 눈금(구간이 10년이라 월 단위는 겹친다).
  const xTicks = useMemo(() => {
    const out: string[] = [];
    const y0 = new Date((x0 + 0.5) * 86_400_000).getUTCFullYear();
    const y1 = new Date((x1 + 0.5) * 86_400_000).getUTCFullYear();
    const stride = y1 - y0 > 6 ? 2 : 1;
    for (let y = y0 + 1; y <= y1; y += stride) out.push(`${y}-01-01`);
    return out;
  }, [x0, x1]);

  const onMove = (e: React.MouseEvent<SVGSVGElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    if (r.width <= 0) return;
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

  const hx = hoverX ? X(day(hoverX)) : 0;

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

        {series.map((s, i) => (
          <path
            key={s.key}
            d={s.points
              .map((p, j) => `${j ? "L" : "M"}${X(day(p[0])).toFixed(1)},${Y(p[1]).toFixed(1)}`)
              .join(" ")}
            fill="none"
            stroke={PALETTE[i % PALETTE.length]}
            strokeWidth={1.5}
            strokeLinejoin="round"
            strokeLinecap="round"
          />
        ))}

        {xTicks.map((d) => (
          <text
            key={d}
            x={X(day(d))}
            y={h - 4}
            fontSize={9.5}
            fill={AXIS_TEXT}
            textAnchor="middle"
            style={{ fontVariantNumeric: "tabular-nums" }}
          >
            {d.slice(2, 4)}
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
                  stroke={PALETTE[i % PALETTE.length]}
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
                  style={{ background: PALETTE[i % PALETTE.length] }}
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

export function RateChartCard({
  topic,
  title,
  sub,
  chartKeys,
  statKeys = [],
  digits = 2,
  suffix = "",
  colSpan = 2,
  tabs,
}: {
  topic: RateTopicKey;
  title: string;
  sub: string;
  chartKeys: string[];
  statKeys?: string[];
  digits?: number;
  suffix?: string;
  colSpan?: number;
  /** 탭 묶음에 들어갈 때 제목 자리에 끼우는 칩(page.tsx 가 상태를 든다). */
  tabs?: React.ReactNode;
}) {
  const { data, isLoading, isError } = useQuery<RateTopics>({
    queryKey: ["rate-topics"], // 네 카드가 같은 키 → fetch 는 한 번
    queryFn: getRateTopics,
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

  const group = data?.[topic] ?? null;
  const all = group?.series ?? [];
  const fmt = (v: number) =>
    `${v.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits })}${suffix}`;
  const plotted = chartKeys
    .map((k) => all.find((s) => s.key === k))
    .filter((s): s is RateSeries => !!s);
  const stats = statKeys
    .map((k) => all.find((s) => s.key === k))
    .filter((s): s is RateSeries => !!s);

  return (
    <section
      className={cn(
        "flex min-h-0 flex-col rounded-xl border border-hairline bg-canvas",
        // 정적 클래스로 적어야 tailwind 가 스캔한다(`lg:col-span-${n}` 은 안 나온다).
        colSpan === 3 ? "lg:col-span-3" : colSpan === 1 ? "lg:col-span-1" : "lg:col-span-2",
      )}
    >
      {/* 제목 띠는 강조색(ge-header) — 배경이 어두우므로 글자를 흰색 계열로 뒤집는다.
          ★2026-08-28 사용자 지시로 페이지의 카드가 전부 이 색이 되면서 accent 조건분기를
          걷어냈다(켜고 끄는 카드가 더는 없다). 탭 묶음에선 제목 자리를 칩이 대신한다. */}
      <header className="flex items-center gap-2 rounded-t-xl bg-ge-header px-3 py-1.5">
        {tabs ?? <h2 className="shrink-0 text-[13px] font-extrabold text-white">{title}</h2>}
        <span className="min-w-0 truncate text-[11px] text-white/70">{sub}</span>
        {group?.asof ? (
          <span className="ml-auto shrink-0 text-[11px] tabular-nums text-white/60">
            {group.asof} 기준
          </span>
        ) : null}
      </header>

      {/* 범례 = 이름 + 현재값. 색만으로 계열을 가르지 않게 하는 장치이자
          (주황 대비 2.65:1 보완) 카드에서 제일 먼저 읽히는 숫자다. */}
      {plotted.length > 0 ? (
        <div className="flex flex-wrap items-baseline gap-x-2.5 gap-y-0 px-3 pt-1 text-[11px]">
          {plotted.map((s, i) => (
            <span key={s.key} className="flex items-baseline gap-1">
              <span
                className="inline-block h-2 w-2 shrink-0 translate-y-[-1px] rounded-sm"
                style={{ background: PALETTE[i % PALETTE.length] }}
              />
              <span className="text-ink-muted">{s.label.replace(/\s*\(.*\)\s*$/, "")}</span>
              <b className="font-bold tabular-nums text-ink">{fmt(s.last)}</b>
            </span>
          ))}
          {stats.map((s) => (
            <span key={s.key} className="flex items-baseline gap-1">
              <span className="text-ink-muted">
                {s.label.replace(/\s*\(.*\)\s*$/, "")}
              </span>
              <b className="font-bold tabular-nums text-ink">{fmt(s.last)}</b>
            </span>
          ))}
        </div>
      ) : null}

      <div ref={wrapRef} className="min-h-0 flex-1 px-1 pb-0.5 pt-0.5">
        {isLoading ? (
          <Center msg="불러오는 중…" />
        ) : isError ? (
          <Center msg="collector 에 못 닿았습니다." tone="text-rose-600" />
        ) : plotted.length === 0 ? (
          <Center
            msg={data?.note ?? "금리_2.xlsx 판독 대기 중 — 데이터가 들어오면 자동 표시됩니다."}
            tone={data?.note ? "text-amber-600" : undefined}
          />
        ) : box.w > 0 && box.h > 0 ? (
          <Chart series={plotted} w={box.w} h={box.h} fmt={fmt} />
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
