"use client";

import { useMemo, useState } from "react";
import type { LabSignal } from "@/lib/api-strategy";

// 괴리 시계열 + 직전 120일 상·하위 10% 경계 + 신호(적중 초록 · 실패 빨강 · 진행 중 회색).
// ★2026-10-29: 점이 200개 남짓이라 라이브러리 없이 SVG 로 그린다. 마우스를 올리면 그날 값을 보인다.

const W = 900;
const H = 240;
const P = { l: 44, r: 12, t: 12, b: 24 };

export function SpreadChart({
  dates,
  spread,
  lo,
  hi,
  signals,
  nameOf,
}: {
  dates: string[];
  spread: (number | null)[];
  lo: (number | null)[];
  hi: (number | null)[];
  signals: LabSignal[];
  nameOf: (key: string) => string;
}) {
  const [hover, setHover] = useState<number | null>(null);
  const { x, y, path, loPath, hiPath, ticks, yTicks } = useMemo(() => {
    const vals = [...spread, ...lo, ...hi].filter((v): v is number => v != null);
    const min = Math.min(...vals, 0);
    const max = Math.max(...vals, 0);
    const pad = (max - min) * 0.08 || 0.01;
    const lo_ = min - pad;
    const hi_ = max + pad;
    const x = (i: number) => P.l + ((W - P.l - P.r) * i) / Math.max(1, dates.length - 1);
    const y = (v: number) => P.t + ((H - P.t - P.b) * (hi_ - v)) / (hi_ - lo_);
    const line = (arr: (number | null)[]) => {
      let d = "";
      let pen = false;
      arr.forEach((v, i) => {
        if (v == null) {
          pen = false;
          return;
        }
        d += `${pen ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`;
        pen = true;
      });
      return d;
    };
    const ticks = dates
      .map((d, i) => ({ d, i }))
      .filter(({ d }, k, arr) => k === 0 || d.slice(0, 7) !== arr[k - 1].d.slice(0, 7))
      .map(({ d, i }) => ({ i, label: `${Number(d.slice(5, 7))}월` }));
    const step = (hi_ - lo_) / 4;
    const yTicks = [0, 1, 2, 3, 4].map((k) => lo_ + step * k);
    return { x, y, path: line(spread), loPath: line(lo), hiPath: line(hi), ticks, yTicks };
  }, [dates, spread, lo, hi]);

  const pos = useMemo(() => new Map(dates.map((d, i) => [d, i])), [dates]);
  const pct = (v: number | null) => (v == null ? "—" : `${(v * 100).toFixed(1)}%`);

  return (
    <div className="relative">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="h-auto w-full select-none"
        role="img"
        aria-label="괴리 시계열"
        onMouseLeave={() => setHover(null)}
        onMouseMove={(e) => {
          const r = (e.currentTarget as SVGSVGElement).getBoundingClientRect();
          const px = ((e.clientX - r.left) / r.width) * W;
          const i = Math.round(((px - P.l) / (W - P.l - P.r)) * (dates.length - 1));
          setHover(i >= 0 && i < dates.length ? i : null);
        }}
      >
        {yTicks.map((v) => (
          <g key={v}>
            <line x1={P.l} x2={W - P.r} y1={y(v)} y2={y(v)} stroke="#EEEEEE" />
            <text x={P.l - 6} y={y(v) + 3} textAnchor="end" fontSize="10" fill="#8A8A8A">
              {(v * 100).toFixed(0)}%
            </text>
          </g>
        ))}
        <line x1={P.l} x2={W - P.r} y1={y(0)} y2={y(0)} stroke="#BDBDBD" />
        <path d={hiPath} fill="none" stroke="#A33A2A" strokeDasharray="4 4" strokeWidth="1" opacity="0.7" />
        <path d={loPath} fill="none" stroke="#3A6B96" strokeDasharray="4 4" strokeWidth="1" opacity="0.7" />
        <path d={path} fill="none" stroke="#5A3A22" strokeWidth="1.6" />
        {signals.map((s) => {
          const i = pos.get(s.date);
          const v = i != null ? spread[i] : null;
          if (i == null || v == null) return null;
          const fill = s.hit == null ? "#9E9E9E" : s.hit ? "#2F7D4F" : "#B23B2B";
          return (
            <circle key={s.date} cx={x(i)} cy={y(v)} r={5} fill={fill} stroke="white" strokeWidth="1.5">
              <title>
                {`${s.date} · ${nameOf(s.bought)} 매수 · ${s.ret == null ? "진행 중" : `${(s.ret * 100).toFixed(1)}%`}`}
              </title>
            </circle>
          );
        })}
        {ticks.map(({ i, label }) => (
          <text key={i} x={x(i)} y={H - 6} fontSize="10" fill="#8A8A8A">
            {label}
          </text>
        ))}
        {hover != null && <line x1={x(hover)} x2={x(hover)} y1={P.t} y2={H - P.b} stroke="#9E9E9E" strokeDasharray="2 3" />}
      </svg>
      <p className="mt-1 min-h-[16px] text-[11px] font-semibold tabular-nums text-ink-muted">
        {hover != null ? (
          <>
            <span className="text-ink">{dates[hover]}</span> · 괴리 <b className="text-ink">{pct(spread[hover])}</b> · 상위10% 경계{" "}
            {pct(hi[hover])} · 하위10% 경계 {pct(lo[hover])}
          </>
        ) : (
          <>점선 = 직전 120 영업일 괴리의 상위·하위 10% · 점 = 매수 신호(초록 적중 · 빨강 실패 · 회색 진행 중)</>
        )}
      </p>
    </div>
  );
}
