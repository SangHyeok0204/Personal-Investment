"use client";

import { useState } from "react";
import type { EtfGroupRow } from "@/lib/api";
import { cn } from "@/lib/utils";
import { fmtEok, fmtPct, fmtRatio } from "./format";

// [국내상장 ETF] 자금 ↔ 성과 사분면.
//
// 이 페이지가 답하려는 질문("돈이 몰린 곳의 수익률은 어땠나")을 한 장으로 만드는 그림이다.
//   x = 시총 대비 개인 순매수(%)  ·  y = 시총가중 수익률(%)  ·  원 크기 = 시총
// ★x 를 **강도(시총 대비)** 로 잡은 이유: 절대 억원이면 점 두어 개가 오른쪽 끝으로
//   날아가고 나머지가 0 근처에 뭉쳐 사분면이 안 읽힌다.
// ★축 범위는 데이터에서 잡되 **0 을 반드시 포함**한다 — 사분면 경계가 화면 밖으로
//   나가면 "몰렸는데 빠졌다"를 읽을 수 없다.
// ★원 반지름은 시총의 **제곱근**에 비례한다(면적이 시총에 비례). 지름에 비례시키면
//   큰 분류 하나가 화면을 덮는다.
// 외부 차트 라이브러리를 쓰지 않는 앱 규약을 따라 SVG 로 직접 그린다.

const VB = { w: 760, h: 560 };
const PAD = { t: 26, r: 22, b: 40, l: 56 };
const PLOT = {
  w: VB.w - PAD.l - PAD.r,
  h: VB.h - PAD.t - PAD.b,
};

function niceSpan(lo: number, hi: number): [number, number] {
  // 0 을 반드시 품고, 양쪽에 8% 숨통을 준다.
  const a = Math.min(lo, 0);
  const b = Math.max(hi, 0);
  const pad = Math.max((b - a) * 0.08, 1e-6);
  return [a - pad, b + pad];
}

function ticks(lo: number, hi: number, count = 4): number[] {
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

export function ScatterCard({
  rows,
  ratioOf,
  retOf,
  netOf,
  selected,
  onSelect,
  periodLabel,
  limit = 40,
}: {
  rows: EtfGroupRow[];
  ratioOf: (r: EtfGroupRow) => number | null;
  retOf: (r: EtfGroupRow) => number | null;
  netOf: (r: EtfGroupRow) => number | null;
  selected: string | null;
  onSelect: (key: string) => void;
  periodLabel: string;
  limit?: number;
}) {
  const [hover, setHover] = useState<string | null>(null);

  // 시총이 큰 순으로 자른다 — 종목 한둘짜리 소분류까지 다 찍으면 점이 205개다.
  const pts = [...rows]
    .filter((r) => ratioOf(r) != null && retOf(r) != null && (r.mcap ?? 0) > 0)
    .sort((a, b) => b.mcap - a.mcap)
    .slice(0, limit)
    .map((r) => ({ r, x: ratioOf(r)!, y: (retOf(r) ?? 0) * 100 }));

  if (pts.length < 2) {
    return (
      <Shell periodLabel={periodLabel}>
        <div className="flex h-full items-center justify-center text-[12px] text-ink-faint">
          그릴 분류가 없습니다
        </div>
      </Shell>
    );
  }

  const [x0, x1] = niceSpan(
    Math.min(...pts.map((p) => p.x)),
    Math.max(...pts.map((p) => p.x)),
  );
  const [y0, y1] = niceSpan(
    Math.min(...pts.map((p) => p.y)),
    Math.max(...pts.map((p) => p.y)),
  );
  const sx = (v: number) => PAD.l + ((v - x0) / (x1 - x0)) * PLOT.w;
  const sy = (v: number) => PAD.t + (1 - (v - y0) / (y1 - y0)) * PLOT.h;
  const maxCap = Math.max(...pts.map((p) => p.r.mcap));
  const sr = (m: number) => 4 + Math.sqrt(m / maxCap) * 20;

  const zx = sx(0);
  const zy = sy(0);
  const active = pts.find((p) => p.r.key === (hover ?? selected));

  return (
    <Shell periodLabel={periodLabel}>
      <div className="relative min-h-0 flex-1">
        <svg
          viewBox={`0 0 ${VB.w} ${VB.h}`}
          preserveAspectRatio="xMidYMid meet"
          className="h-full w-full"
        >
          {/* 사분면 바탕 — 오른쪽 위(몰렸고 올랐다)만 옅게 물들여 방향을 준다 */}
          <rect
            x={zx}
            y={PAD.t}
            width={Math.max(PAD.l + PLOT.w - zx, 0)}
            height={Math.max(zy - PAD.t, 0)}
            fill="#f1f7ef"
          />
          <rect
            x={zx}
            y={zy}
            width={Math.max(PAD.l + PLOT.w - zx, 0)}
            height={Math.max(PAD.t + PLOT.h - zy, 0)}
            fill="#fdf2f2"
          />

          {ticks(y0, y1).map((t) => (
            <g key={`y${t}`}>
              <line
                x1={PAD.l}
                x2={PAD.l + PLOT.w}
                y1={sy(t)}
                y2={sy(t)}
                stroke="#eef1f5"
              />
              <text
                x={PAD.l - 8}
                y={sy(t) + 4}
                textAnchor="end"
                className="fill-ink-faint"
                fontSize={11}
              >
                {t.toFixed(0)}%
              </text>
            </g>
          ))}
          {ticks(x0, x1).map((t) => (
            <g key={`x${t}`}>
              <line
                y1={PAD.t}
                y2={PAD.t + PLOT.h}
                x1={sx(t)}
                x2={sx(t)}
                stroke="#eef1f5"
              />
              <text
                x={sx(t)}
                y={PAD.t + PLOT.h + 16}
                textAnchor="middle"
                className="fill-ink-faint"
                fontSize={11}
              >
                {t.toFixed(t >= 10 || t <= -10 ? 0 : 1)}%
              </text>
            </g>
          ))}

          {/* 0 축 */}
          <line
            x1={PAD.l}
            x2={PAD.l + PLOT.w}
            y1={zy}
            y2={zy}
            stroke="#9aa3b0"
            strokeDasharray="3 3"
          />
          <line
            y1={PAD.t}
            y2={PAD.t + PLOT.h}
            x1={zx}
            x2={zx}
            stroke="#9aa3b0"
            strokeDasharray="3 3"
          />

          <text
            x={PAD.l + PLOT.w - 4}
            y={PAD.t + 13}
            textAnchor="end"
            fontSize={11}
            fontWeight={800}
            fill="#4d7c4d"
          >
            몰렸고 올랐다
          </text>
          <text
            x={PAD.l + PLOT.w - 4}
            y={PAD.t + PLOT.h - 6}
            textAnchor="end"
            fontSize={11}
            fontWeight={800}
            fill="#b0483f"
          >
            몰렸는데 빠졌다
          </text>
          <text
            x={PAD.l + 4}
            y={PAD.t + 13}
            fontSize={11}
            fontWeight={700}
            fill="#8a94a6"
          >
            안 몰렸는데 올랐다
          </text>
          <text
            x={PAD.l + 4}
            y={PAD.t + PLOT.h - 6}
            fontSize={11}
            fontWeight={700}
            fill="#8a94a6"
          >
            팔았고 빠졌다
          </text>

          {pts.map((p) => {
            const on = p.r.key === (hover ?? selected);
            return (
              <circle
                key={p.r.key}
                cx={sx(p.x)}
                cy={sy(p.y)}
                r={sr(p.r.mcap)}
                fill={p.y >= 0 ? "#e11d48" : "#2563eb"}
                fillOpacity={on ? 0.5 : 0.18}
                stroke={on ? "#243b5e" : p.y >= 0 ? "#e11d48" : "#2563eb"}
                strokeWidth={on ? 2 : 1}
                className="cursor-pointer"
                onMouseEnter={() => setHover(p.r.key)}
                onMouseLeave={() => setHover(null)}
                onClick={() => onSelect(p.r.key)}
              />
            );
          })}

          {/* 라벨은 상위 몇 개에만 — 40개를 다 쓰면 글자가 서로를 덮는다 */}
          {[...pts]
            .sort((a, b) => b.r.mcap - a.r.mcap)
            .slice(0, 8)
            .map((p) => (
              <text
                key={`l${p.r.key}`}
                x={sx(p.x)}
                y={sy(p.y) - sr(p.r.mcap) - 4}
                textAnchor="middle"
                fontSize={10.5}
                fontWeight={700}
                fill="#5a6573"
                pointerEvents="none"
              >
                {p.r.label}
              </text>
            ))}

          <text
            x={PAD.l + PLOT.w / 2}
            y={VB.h - 6}
            textAnchor="middle"
            fontSize={11}
            fontWeight={700}
            fill="#8a94a6"
          >
            시총 대비 개인 순매수 →
          </text>
          <text
            x={14}
            y={PAD.t + PLOT.h / 2}
            textAnchor="middle"
            fontSize={11}
            fontWeight={700}
            fill="#8a94a6"
            transform={`rotate(-90 14 ${PAD.t + PLOT.h / 2})`}
          >
            시총가중 수익률 →
          </text>
        </svg>

        {active && (
          <div className="pointer-events-none absolute left-3 top-3 rounded-lg border border-hairline bg-white/95 px-3 py-2 shadow-panel">
            <div className="text-[12.5px] font-extrabold text-ge-navy">
              {active.r.label}
            </div>
            {active.r.path.length > 0 && (
              <div className="text-[10.5px] font-medium text-ink-faint">
                {active.r.path.join(" · ")}
              </div>
            )}
            <div className="mt-1 space-y-0.5 text-[11.5px] font-semibold tabular-nums text-ink-secondary">
              <div>
                순매수 {fmtEok(netOf(active.r))} · 시총 대비{" "}
                {fmtRatio(ratioOf(active.r))}
              </div>
              <div>
                수익률 {fmtPct(retOf(active.r))} · {active.r.n}종목 · 시총{" "}
                {fmtEok(active.r.mcap, false)}
              </div>
            </div>
          </div>
        )}
      </div>
    </Shell>
  );
}

function Shell({
  periodLabel,
  children,
}: {
  periodLabel: string;
  children: React.ReactNode;
}) {
  return (
    <div
      className={cn(
        "flex h-full min-h-0 flex-col overflow-hidden rounded-xl border border-hairline bg-canvas shadow-card",
      )}
    >
      <div className="flex items-baseline justify-between gap-3 border-b border-hairline bg-ge-header px-4 py-2.5">
        <h2 className="text-[14px] font-extrabold tracking-tight text-white">
          자금 ↔ 성과 · {periodLabel}
        </h2>
        <span className="shrink-0 text-[11px] font-semibold text-white/70">
          원 크기 = 시총
        </span>
      </div>
      {children}
    </div>
  );
}
