"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { getEtfClassHistory, type EtfAxisKey } from "@/lib/api";
import { cn } from "@/lib/utils";
import { fmtEok, mmdd } from "./format";

// [국내상장 ETF] 일별 누적 — 적재된 스냅샷으로 그리는 진짜 시계열.
//
// ★★원천 워크북은 매일 **덮어쓰기**라 과거가 없다. collector 가 판독할 때마다 그날
//   스냅샷을 sqlite 에 적재하므로 이 계열은 **적재를 시작한 날부터** 자란다.
//   그래서 점이 2개 미만이면 선을 그리지 않고 그 사실을 그대로 쓴다 — 며칠짜리를
//   선으로 이으면 없는 추세를 만들어 보인다. 과거가 필요하면 구간 분해 카드를 본다.
// ★그리는 값은 **누적** 순매수다. 일별 값은 하루하루가 요동쳐 어느 분류로 돈이
//   흘러가는지가 안 읽힌다. 누적은 기울기가 곧 유입 속도라 눈으로 비교된다.

const VB = { w: 1000, h: 300 };
const PAD = { t: 16, r: 96, b: 26, l: 62 };
const PLOT = { w: VB.w - PAD.l - PAD.r, h: VB.h - PAD.t - PAD.b };

// 계열색 — 블루 한 계열인 브랜드색과 부딪히지 않게 채도를 낮춘 8색.
const LINE = [
  "#4a7ab5", "#e11d48", "#2f9e6e", "#d98324",
  "#8b5cf6", "#0a9bc4", "#b0483f", "#6b7280",
];

export function HistoryCard({ axis }: { axis: EtfAxisKey }) {
  const [hover, setHover] = useState<number | null>(null);
  const { data, isLoading } = useQuery({
    queryKey: ["etf-class-history", axis],
    queryFn: () => getEtfClassHistory(axis),
    refetchInterval: 600_000,
  });

  const dates = data?.dates ?? [];
  // 유입·유출 양쪽 끝을 같이 본다 — 상위만 그리면 "빠져나간 곳"이 화면에서 사라진다.
  const all = data?.series ?? [];
  const series = [...all.slice(0, 5), ...all.slice(-3)].filter(
    (s, i, arr) => arr.findIndex((x) => x.key === s.key) === i,
  );

  const flat = series.flatMap((s) => s.cum);
  const lo = Math.min(0, ...flat);
  const hi = Math.max(0, ...flat);
  const pad = Math.max((hi - lo) * 0.08, 1);
  const y0 = lo - pad;
  const y1 = hi + pad;
  const sx = (i: number) =>
    PAD.l + (dates.length <= 1 ? PLOT.w / 2 : (i / (dates.length - 1)) * PLOT.w);
  const sy = (v: number) => PAD.t + (1 - (v - y0) / (y1 - y0)) * PLOT.h;

  const enough = dates.length >= 2;

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden rounded-xl border border-hairline bg-canvas shadow-card">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1 border-b border-hairline bg-ge-header px-4 py-2.5">
        <h2 className="text-[14px] font-extrabold tracking-tight text-white">
          일별 누적 개인 순매수
        </h2>
        <span className="shrink-0 text-[11px] font-semibold text-white/70">
          적재 {dates.length}일
          {dates.length > 0 && ` · ${mmdd(dates[0])}~${mmdd(dates[dates.length - 1])}`}
        </span>
      </div>

      {!enough ? (
        <div className="flex flex-1 flex-col items-center justify-center gap-1 px-6 py-8 text-center">
          <p className="text-[13px] font-bold text-ink-secondary">
            {isLoading ? "불러오는 중" : `아직 ${dates.length}일치만 쌓였습니다`}
          </p>
          <p className="max-w-xl text-[11.5px] leading-relaxed text-ink-faint">
            원천 워크북은 매일 덮어쓰기라 과거가 남지 않습니다. 대시보드가 워크북을
            읽을 때마다 그날치를 적재하므로, 거래일이 지날수록 이 그래프가 자랍니다.
            지금 시점의 과거는 위의 <b className="text-ink-muted">구간 분해</b> 카드가
            1주·1개월·3개월·6개월 창으로 보여줍니다.
          </p>
        </div>
      ) : (
        <div className="relative min-h-0 flex-1">
          <svg
            viewBox={`0 0 ${VB.w} ${VB.h}`}
            preserveAspectRatio="none"
            className="h-full w-full"
            onMouseLeave={() => setHover(null)}
            onMouseMove={(ev) => {
              const box = ev.currentTarget.getBoundingClientRect();
              const px = ((ev.clientX - box.left) / box.width) * VB.w;
              const t = Math.round(
                ((px - PAD.l) / PLOT.w) * (dates.length - 1),
              );
              setHover(Math.max(0, Math.min(dates.length - 1, t)));
            }}
          >
            <line
              x1={PAD.l}
              x2={PAD.l + PLOT.w}
              y1={sy(0)}
              y2={sy(0)}
              stroke="#c3cad4"
              strokeDasharray="3 3"
            />
            {series.map((s, i) => (
              <polyline
                key={s.key}
                fill="none"
                stroke={LINE[i % LINE.length]}
                strokeWidth={1.8}
                strokeLinejoin="round"
                points={s.cum.map((v, j) => `${sx(j)},${sy(v)}`).join(" ")}
              />
            ))}
            {hover != null && (
              <line
                x1={sx(hover)}
                x2={sx(hover)}
                y1={PAD.t}
                y2={PAD.t + PLOT.h}
                stroke="#9aa3b0"
              />
            )}
            {series.map((s, i) => (
              <text
                key={`e${s.key}`}
                x={PAD.l + PLOT.w + 6}
                y={sy(s.cum[s.cum.length - 1]) + 4}
                fontSize={11}
                fontWeight={700}
                fill={LINE[i % LINE.length]}
              >
                {s.label}
              </text>
            ))}
            <text x={PAD.l - 8} y={sy(y1) + 12} textAnchor="end" fontSize={11} fill="#9aa3b0">
              {fmtEok(hi, false)}
            </text>
            <text x={PAD.l - 8} y={sy(0) + 4} textAnchor="end" fontSize={11} fill="#9aa3b0">
              0
            </text>
            <text x={PAD.l} y={VB.h - 8} fontSize={11} fill="#9aa3b0">
              {mmdd(dates[0])}
            </text>
            <text
              x={PAD.l + PLOT.w}
              y={VB.h - 8}
              textAnchor="end"
              fontSize={11}
              fill="#9aa3b0"
            >
              {mmdd(dates[dates.length - 1])}
            </text>
          </svg>

          {hover != null && (
            <div className="pointer-events-none absolute right-3 top-3 rounded-lg border border-hairline bg-white/95 px-3 py-2 shadow-panel">
              <div className="text-[11.5px] font-extrabold text-ge-navy">
                {dates[hover]}
              </div>
              <div className="mt-1 space-y-0.5">
                {series.map((s, i) => (
                  <div
                    key={s.key}
                    className={cn(
                      "flex items-baseline gap-2 text-[11px] font-semibold tabular-nums",
                    )}
                  >
                    <span
                      className="inline-block h-2 w-2 shrink-0 rounded-full"
                      style={{ background: LINE[i % LINE.length] }}
                    />
                    <span className="flex-1 text-ink-secondary">{s.label}</span>
                    <span className="text-ink">{fmtEok(s.cum[hover])}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
