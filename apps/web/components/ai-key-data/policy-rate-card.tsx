"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { getPolicyRate } from "@/lib/api";
import { EMDASH } from "@/components/stock-monitor/format";
import { cn } from "@/lib/utils";
import { POLL_MS } from "@/components/ai-key-data/poll";
import { useCardZoom, ZoomButton } from "@/components/ai-key-data/card-zoom";

// [정책금리] — [AI Key Data] 우상단 3칸 (2026-08-27).
// FOMC 금리 결정을 계단 차트로. 원천은 AI Key Data macro_releases.csv 의
// event=RATE 행 — collector policy_rate.py 가 뽑아 준다.
//
// ★★계단(step)으로 그리는 이유: 정책금리는 회의와 회의 사이에 그대로 유지된다.
//   점을 직선으로 이으면 "3월에 3.9%였다" 같은 **실제로 없던 중간값**이 생긴다.
//   그래서 결정일까지 수평으로 가다가 그 날 수직으로 꺾는다.
// 렌더 관례는 컴퓨팅 지수 카드와 같다(ResizeObserver + viewBox 를 px 와 1:1).

const LINE = "#4a7ab5";
const GRID = "#EDF0F5";
const AXIS_TEXT = "#8a94a6";
const CROSS = "#B7C0CE";

// ★2026-08-31 글자 상향(9~9.5 -> 11~11.5px)에 맞춰 축 여백도 넓혔다 —
//   안 넓히면 y 라벨이 잘리고 x 날짜가 서로 겹친다.
const PAD_L = 50;
const PAD_R = 12;
const PAD_T = 10;
const XAXIS_H = 20;

const day = (d: string) => Date.parse(`${d}T00:00:00Z`) / 86_400_000;

function niceTicks(lo: number, hi: number, count: number): number[] {
  const raw = (hi - lo) / count;
  if (!Number.isFinite(raw) || raw <= 0) return [lo];
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? 10 * mag;
  const out: number[] = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) out.push(+v.toFixed(10));
  return out;
}

const fmtPct = (v: number) => `${v.toFixed(2)}%`;
const mmdd = (d: string) => d.slice(5).replace("-", "/");

function Chart({
  points,
  w,
  h,
}: {
  points: [string, number][];
  w: number;
  h: number;
}) {
  const [hover, setHover] = useState<number | null>(null);

  const plotW = Math.max(1, w - PAD_L - PAD_R);
  const plotH = Math.max(12, h - PAD_T - XAXIS_H);
  const py1 = PAD_T + plotH;

  const { x0, x1, yLo, yHi } = useMemo(() => {
    const ds = points.map((p) => day(p[0]));
    const vs = points.map((p) => p[1]);
    const lo = Math.min(...vs);
    const hi = Math.max(...vs);
    // 위아래 여백 12% — 계단이 위아래로 잘리지 않을 만큼만(2026-08-28 35%→12%,
    // "빈 공간 없이" 지시). 값 폭이 0.5%p뿐이라 여백을 크게 주면 선이 가운데 눌린다.
    const pad = (hi - lo) * 0.12 || 0.25;
    // 마지막 결정 이후 오늘까지도 그 금리가 유지되고 있다 — 오른쪽 끝을 오늘로 민다.
    return {
      x0: ds[0],
      x1: Math.max(ds[ds.length - 1], Date.now() / 86_400_000),
      yLo: lo - pad,
      yHi: hi + pad,
    };
  }, [points]);

  const X = (d: number) => PAD_L + ((d - x0) / (x1 - x0 || 1)) * plotW;
  const Y = (v: number) => py1 - ((v - yLo) / (yHi - yLo)) * plotH;

  // 계단 path — 다음 결정일까지 수평, 그 날 수직. 마지막 구간은 오른쪽 끝(오늘)까지.
  const d = useMemo(() => {
    const seg: string[] = [];
    points.forEach((p, i) => {
      const x = X(day(p[0]));
      const y = Y(p[1]);
      if (i === 0) seg.push(`M${x.toFixed(1)},${y.toFixed(1)}`);
      else seg.push(`L${x.toFixed(1)},${y.toFixed(1)}`);
      const nx = i + 1 < points.length ? X(day(points[i + 1][0])) : PAD_L + plotW;
      seg.push(`L${nx.toFixed(1)},${y.toFixed(1)}`);
    });
    return seg.join(" ");
  }, [points, w, h, x0, x1, yLo, yHi]);

  const onMove = (e: React.MouseEvent<SVGSVGElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    if (r.width <= 0) return;
    const t = x0 + (((e.clientX - r.left) / r.width) * w - PAD_L) / plotW * (x1 - x0);
    // 그 시점에 유효한 결정 = t 이하의 마지막 결정(계단의 의미 그대로)
    let idx = 0;
    for (let i = 0; i < points.length; i++) if (day(points[i][0]) <= t) idx = i;
    setHover(idx);
  };

  const hv = hover == null ? null : points[hover];

  return (
    <div className="relative h-full w-full">
      <svg
        width="100%"
        height={h}
        viewBox={`0 0 ${w} ${h}`}
        style={{ display: "block" }}
        onMouseMove={onMove}
        onMouseLeave={() => setHover(null)}
        role="img"
        aria-label="FOMC 정책금리 계단 차트"
      >
        {/* count=4 라야 0.25%p 간격이 잡힌다 — 정책금리는 폭이 좁아(0.5%p) count 를
            낮추면 눈금이 4.00% 하나만 걸려 축이 안 읽힌다(실측 후 조정). */}
        {niceTicks(yLo, yHi, 4).map((v) => {
          const y = Y(v);
          if (y < PAD_T - 0.5 || y > py1 + 0.5) return null;
          return (
            <g key={v}>
              <line x1={PAD_L} y1={y} x2={PAD_L + plotW} y2={y} stroke={GRID} strokeWidth={1} />
              <text
                x={PAD_L - 5}
                y={y + 3}
                fontSize={11.5}
                fill={AXIS_TEXT}
                textAnchor="end"
                style={{ fontVariantNumeric: "tabular-nums" }}
              >
                {fmtPct(v)}
              </text>
            </g>
          );
        })}

        <path
          d={d}
          fill="none"
          stroke={LINE}
          strokeWidth={2}
          strokeLinejoin="round"
          strokeLinecap="round"
        />

        {/* 결정 시점 점 — 값이 바뀐 회의만 채우고 동결은 테두리만(눈으로 갈린다) */}
        {points.map((p, i) => {
          const changed = i === 0 || p[1] !== points[i - 1][1];
          return (
            <circle
              key={p[0]}
              cx={X(day(p[0]))}
              cy={Y(p[1])}
              r={changed ? 3.6 : 2.4}
              fill={changed ? LINE : "#ffffff"}
              stroke={LINE}
              strokeWidth={changed ? 1.5 : 1.5}
            />
          );
        })}

        {/* x축 — 첫·마지막 결정일만(칸이 좁아 촘촘히 넣으면 겹친다) */}
        <text x={PAD_L} y={h - 4} fontSize={11.5} fill={AXIS_TEXT} textAnchor="start"
              style={{ fontVariantNumeric: "tabular-nums" }}>
          {points[0][0].slice(2, 7).replace("-", ".")}
        </text>
        <text x={PAD_L + plotW} y={h - 4} fontSize={11.5} fill={AXIS_TEXT} textAnchor="end"
              style={{ fontVariantNumeric: "tabular-nums" }}>
          현재
        </text>

        {hv ? (
          <g style={{ pointerEvents: "none" }}>
            <line
              x1={X(day(hv[0]))}
              y1={PAD_T}
              x2={X(day(hv[0]))}
              y2={py1}
              stroke={CROSS}
              strokeWidth={1}
            />
            <circle cx={X(day(hv[0]))} cy={Y(hv[1])} r={4} fill="#ffffff" stroke={LINE} strokeWidth={2} />
          </g>
        ) : null}
      </svg>

      {hv ? (
        <div
          className="pointer-events-none absolute top-1 z-10 rounded-lg border border-hairline bg-canvas/95 px-2.5 py-1.5 shadow-panel"
          style={{
            left: X(day(hv[0])),
            transform:
              X(day(hv[0])) > w / 2 ? "translateX(calc(-100% - 10px))" : "translateX(10px)",
          }}
        >
          <div className="text-[12px] tabular-nums text-ink-muted">{hv[0]} FOMC</div>
          <div className="text-[15px] font-extrabold tabular-nums text-ink">{fmtPct(hv[1])}</div>
        </div>
      ) : null}
    </div>
  );
}

export function PolicyRateCard({
  colSpan = 3,
  tabs,
}: {
  colSpan?: 1 | 2 | 3;
  /** 탭 묶음에 들어갈 때 제목 자리에 끼우는 칩(page.tsx 가 상태를 든다). */
  tabs?: React.ReactNode;
}) {
  const { zoomed, toggle, zoomCls } = useCardZoom();
  const { data, isLoading, isError } = useQuery({
    queryKey: ["policy-rate"],
    queryFn: getPolicyRate,
    refetchInterval: POLL_MS,
  });
  const points = data?.points ?? [];

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

  const chg = data?.chg_bp ?? null;

  return (
    <section
      className={cn(
        zoomCls,
        "flex min-h-0 flex-col rounded-xl border border-hairline bg-canvas",
        colSpan === 3 ? "lg:col-span-3" : colSpan === 2 ? "lg:col-span-2" : "lg:col-span-1",
      )}
    >
      {/* 제목 띠는 강조색(ge-header) — 배경이 어두우므로 글자를 흰색 계열로 뒤집는다.
          탭 묶음에 들어가면 제목 자리를 칩이 대신한다(활성 칩이 곧 카드 이름). */}
      <header className="flex items-center gap-2 rounded-t-xl bg-ge-header px-3 py-1.5">
        {tabs ?? (
          <h2 className="shrink-0 text-[15px] font-extrabold text-white">정책금리</h2>
        )}
        <span className="min-w-0 truncate text-[13px] text-white/70">
          FOMC 결정 · 회의 사이는 유지(계단)
        </span>
        {data?.asof ? (
          <span className="ml-auto shrink-0 text-[13px] tabular-nums text-white/60">
            {data.asof} 기준
          </span>
        ) : null}
      <ZoomButton zoomed={zoomed} onToggle={toggle} />
      </header>

      {points.length > 0 ? (
        // 현재 수준을 크게 — 카드에서 제일 먼저 읽혀야 하는 숫자다.
        <div className="flex shrink-0 flex-wrap items-baseline gap-x-2 px-3 pt-1">
          <span className="text-[26px] font-extrabold leading-none tabular-nums text-ink">
            {data?.last == null ? EMDASH : fmtPct(data.last)}
          </span>
          {/* 동결 중이면 "N회 연속 동결", 방금 움직였으면 그 폭(bp). 색은 인상 빨강 /
              인하 파랑(화면 공통 등락 관례)이고 동결은 무채색이다. */}
          <span className="text-[13px] tabular-nums text-ink-muted">
            {data?.last_change_date ? (
              <>
                <b
                  className={cn(
                    "font-bold",
                    data.holds > 0 || chg == null || chg === 0
                      ? "text-ink-muted"
                      : chg > 0
                        ? "text-rose-600"
                        : "text-blue-600",
                  )}
                >
                  {data.holds > 0
                    ? `${data.holds}회 연속 동결`
                    : chg == null
                      ? EMDASH
                      : `${chg > 0 ? "+" : ""}${chg}bp`}
                </b>
                {" · 마지막 변경 "}
                {mmdd(data.last_change_date)}
              </>
            ) : null}
          </span>
        </div>
      ) : null}

      <div ref={wrapRef} className="min-h-0 flex-1 px-1 pb-0.5 pt-0.5">
        {isLoading ? (
          <Center msg="불러오는 중…" />
        ) : isError ? (
          <Center msg="collector 에 못 닿았습니다." tone="text-rose-600" />
        ) : points.length === 0 ? (
          <Center
            msg={data?.note ?? "macro_releases.csv 판독 대기 중 — 데이터가 들어오면 자동 표시됩니다."}
            tone={data?.note ? "text-amber-600" : undefined}
          />
        ) : box.w > 0 && box.h > 0 ? (
          <Chart points={points} w={box.w} h={box.h} />
        ) : null}
      </div>
    </section>
  );
}

function Center({ msg, tone }: { msg: string; tone?: string }) {
  return (
    <div className="flex h-full items-center justify-center px-6 text-center">
      <span className={cn("text-[13.5px] font-semibold leading-relaxed text-ink-muted", tone)}>
        {msg}
      </span>
    </div>
  );
}
