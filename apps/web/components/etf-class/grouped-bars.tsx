"use client";

import { useEffect, useRef, useState } from "react";
import type { EtfGroupRow } from "@/lib/api";
import { cn } from "@/lib/utils";

// [국내상장 ETF] 분류별 묶음 막대 — 순매수 뷰와 수익률 뷰가 같이 쓴다.
//
// ★★한 줄 6개 × 2줄이고 두 줄이 **같은 y축**을 쓴다. 줄마다 축을 따로 잡으면 7~12위
//   막대가 1~6위만큼 커 보여서, 줄이 나뉜 것뿐인데 순위가 사라진다.
// ★★실측 픽셀에 **1:1** 로 그린다(viewBox = 실제 크기). 고정 viewBox +
//   `preserveAspectRatio="none"` 이면 SVG 를 눌러 늘리면서 **글자까지 같이 눌린다**
//   (2026-09-01 사용자 지적). 폭·높이가 화면마다 달라 상수 viewBox 로는 못 피한다.
// ★한 줄의 높이 = 스크롤 칸의 높이. 그래서 한 화면에 한 줄만 들어오고 둘째 줄은
//   스크롤해야 보인다.

export const PER_ROW = 6;
export const BAR_ROWS = 2;
export const BAR_TOP_N = PER_ROW * BAR_ROWS;

const PAD = { t: 16, r: 12, b: 44, l: 64 };

export type BarSpec = { key: string; label: string; fill: string };

function usePaneSize(ref: { current: HTMLDivElement | null }) {
  const [size, setSize] = useState({ w: 700, h: 420 });
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(() => {
      const w = el.clientWidth;
      const h = el.clientHeight;
      if (w > 0 && h > 0) setSize((p) => (p.w === w && p.h === h ? p : { w, h }));
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, [ref]);
  return size;
}

function niceTicks(lo: number, hi: number, count = 4): number[] {
  if (!isFinite(lo) || !isFinite(hi) || lo === hi) return [lo];
  const raw = (hi - lo) / count;
  const mag = Math.pow(10, Math.floor(Math.log10(Math.abs(raw))));
  const step = [1, 2, 2.5, 5, 10]
    .map((m) => m * mag)
    .reduce((p, c) => (Math.abs(c - raw) < Math.abs(p - raw) ? c : p));
  const out: number[] = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) {
    out.push(Number(v.toFixed(10)));
  }
  return out;
}

export function GroupedBars({
  rows,
  bars,
  valueOf,
  fmtAxis,
  fmtValue,
  footNote,
  selected,
  onSelect,
  tooltipExtra,
}: {
  rows: EtfGroupRow[];
  bars: BarSpec[];
  /** 막대 하나의 값. null 이면 그 막대만 건너뛴다(0 으로 그리지 않는다). */
  valueOf: (r: EtfGroupRow, barKey: string) => number | null;
  fmtAxis: (v: number) => string;
  fmtValue: (v: number | null) => string;
  footNote: string;
  selected: string | null;
  onSelect: (key: string) => void;
  /** 툴팁에 한 줄 더 붙이고 싶을 때(예: 총액). */
  tooltipExtra?: (r: EtfGroupRow, barKey: string) => string | null;
}) {
  const [hover, setHover] = useState<string | null>(null);
  const paneRef = useRef<HTMLDivElement>(null);
  const { w: VW, h: VH } = usePaneSize(paneRef);
  const PLOT = {
    w: Math.max(VW - PAD.l - PAD.r, 10),
    h: Math.max(VH - PAD.t - PAD.b, 10),
  };

  const charted = rows.slice(0, BAR_TOP_N);
  // ★스케일은 12개 전체에서 한 번만 잡는다 — 두 줄이 같은 축을 쓰게 하려는 것.
  const vals = charted.flatMap((r) =>
    bars.map((b) => valueOf(r, b.key)).filter((v): v is number => v != null),
  );
  const lo = Math.min(0, ...vals);
  const hi = Math.max(0, ...vals);
  const pad = Math.max((hi - lo) * 0.08, 1e-9);
  const y0 = lo - pad;
  const y1 = hi + pad;
  const sy = (v: number) => PAD.t + (1 - (v - y0) / (y1 - y0)) * PLOT.h;
  const ticks = niceTicks(y0, y1);

  const chunks: EtfGroupRow[][] = [];
  for (let i = 0; i < charted.length; i += PER_ROW) {
    chunks.push(charted.slice(i, i + PER_ROW));
  }
  const active = charted.find((r) => r.key === hover);

  const gw = PLOT.w / PER_ROW; // 칸 폭은 6개 기준 고정 — 두 줄의 막대 굵기가 같아야 한다
  const bw = Math.min((gw * 0.72) / bars.length, 24);

  return (
    <div className="relative flex h-full min-h-0 flex-col">
      <div ref={paneRef} className="min-h-0 flex-1 overflow-y-auto">
        {chunks.map((chunk, ri) => (
          <svg
            key={ri}
            width={VW}
            height={VH}
            viewBox={`0 0 ${VW} ${VH}`}
            className="block shrink-0"
          >
            {ticks.map((t) => (
              <g key={t}>
                <line
                  x1={PAD.l}
                  x2={PAD.l + PLOT.w}
                  y1={sy(t)}
                  y2={sy(t)}
                  stroke={Math.abs(t) < 1e-12 ? "#9aa3b0" : "#eef1f5"}
                />
                <text
                  x={PAD.l - 8}
                  y={sy(t) + 4}
                  textAnchor="end"
                  fontSize={12}
                  fill="#9aa3b0"
                >
                  {fmtAxis(t)}
                </text>
              </g>
            ))}

            {chunk.map((r, gi) => {
              const gx = PAD.l + gi * gw;
              const on = r.key === (hover ?? selected);
              return (
                <g
                  key={r.key}
                  onMouseEnter={() => setHover(r.key)}
                  onMouseLeave={() => setHover(null)}
                  onClick={() => onSelect(r.key)}
                  className="cursor-pointer"
                >
                  <rect
                    x={gx}
                    y={PAD.t}
                    width={gw}
                    height={PLOT.h}
                    fill={on ? "#e7f0fb" : "transparent"}
                  />
                  {bars.map((b, bi) => {
                    const v = valueOf(r, b.key);
                    if (v == null) return null;
                    const y = sy(Math.max(v, 0));
                    const h = Math.abs(sy(v) - sy(0));
                    const x = gx + gw / 2 - (bars.length * bw) / 2 + bi * bw + 1;
                    return (
                      <rect
                        key={b.key}
                        x={x}
                        y={y}
                        width={bw - 2}
                        height={Math.max(h, 1)}
                        fill={b.fill}
                        fillOpacity={on ? 1 : 0.82}
                        rx={1.5}
                      />
                    );
                  })}
                  <text
                    x={gx + gw / 2}
                    y={PAD.t + PLOT.h + 15}
                    textAnchor="middle"
                    fontSize={12.5}
                    fontWeight={on ? 800 : 600}
                    fill={on ? "#243b5e" : "#5a6573"}
                  >
                    {r.label.length > 7 ? `${r.label.slice(0, 7)}…` : r.label}
                  </text>
                </g>
              );
            })}

            {/* 범례는 첫 줄에만 — 두 줄에 같은 걸 두 번 쓰면 자리만 먹는다 */}
            {ri === 0 &&
              bars.map((b, i) => (
                <g key={b.key} transform={`translate(${PAD.l + i * 76} ${VH - 10})`}>
                  <rect width={10} height={10} y={-9} fill={b.fill} rx={1.5} />
                  <text x={15} fontSize={12} fontWeight={700} fill="#5a6573">
                    {b.label}
                  </text>
                </g>
              ))}
            {ri === chunks.length - 1 && (
              <text
                x={PAD.l + PLOT.w}
                y={VH - 10}
                textAnchor="end"
                fontSize={10.5}
                fill="#9aa3b0"
              >
                {footNote}
              </text>
            )}
          </svg>
        ))}
      </div>

      {active && (
        <div className="pointer-events-none absolute right-3 top-3 rounded-lg border border-hairline bg-white/95 px-3 py-2 shadow-panel">
          <div className="text-[12.5px] font-extrabold text-ge-navy">
            {active.label}
          </div>
          {active.path.length > 0 && (
            <div className="text-[10.5px] font-medium text-ink-faint">
              {active.path.join(" · ")} · {active.n}종목
            </div>
          )}
          <div className="mt-1 space-y-0.5">
            {bars.map((b) => {
              const extra = tooltipExtra?.(active, b.key);
              return (
                <div
                  key={b.key}
                  className="flex items-baseline gap-2 text-[11px] font-semibold tabular-nums"
                >
                  <span
                    className="inline-block h-2 w-2 shrink-0 rounded-[1px]"
                    style={{ background: b.fill }}
                  />
                  <span className="w-9 text-ink-secondary">{b.label}</span>
                  <span
                    className={cn(
                      "w-[76px] text-right",
                      (valueOf(active, b.key) ?? 0) > 0
                        ? "text-rose-600"
                        : (valueOf(active, b.key) ?? 0) < 0
                          ? "text-blue-600"
                          : "text-ink-muted",
                    )}
                  >
                    {fmtValue(valueOf(active, b.key))}
                  </span>
                  {extra && (
                    <span className="w-[74px] text-right text-ink-faint">{extra}</span>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
