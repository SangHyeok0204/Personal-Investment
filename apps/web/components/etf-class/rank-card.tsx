"use client";

import type { EtfGroupRow } from "@/lib/api";
import { cn } from "@/lib/utils";
import { fmtEok, fmtPct, fmtRatio, tone } from "./format";

// [국내상장 ETF] 분류 랭킹 — "돈이 어디로 몰렸나" 를 한 눈에 세우는 표.
//
// ★막대는 **0 을 가운데 둔 발산형**이다. 순매수와 순매도를 같은 축에 놓아야 "몰린 곳"
//   옆에 "빠진 곳"이 보인다. 한쪽으로만 그리면 순매도가 짧은 막대로 뭉개진다.
// ★막대 길이의 분모는 **그 화면에 보이는 값들의 최대 절댓값** 이다. 고정 상한을 두면
//   축이 바뀔 때(구분 2개 ↔ 소분류 205개) 스케일이 안 맞는다.
// ★★금액(억)과 강도(시총 대비 %)를 토글로 가른 이유: 절대 억원은 언제나 규모가 이겨
//   S&P500·커버드콜이 상위를 고정한다. "그 분류 크기에 비해 얼마나 들어왔나"는 다른
//   질문이고, 순위가 실제로 뒤집힌다(주간가격모니터의 "저점 대비 픽" 과 같은 교훈).

export type RankMetric = "amount" | "ratio";

export function RankCard({
  rows,
  metric,
  netOf,
  ratioOf,
  retOf,
  selected,
  onSelect,
  periodLabel,
  windowLabel,
  limit = 18,
}: {
  rows: EtfGroupRow[];
  metric: RankMetric;
  netOf: (r: EtfGroupRow) => number | null;
  ratioOf: (r: EtfGroupRow) => number | null;
  retOf: (r: EtfGroupRow) => number | null;
  selected: string | null;
  onSelect: (key: string) => void;
  periodLabel: string;
  windowLabel: string;
  limit?: number;
}) {
  const valueOf = metric === "amount" ? netOf : ratioOf;
  const ranked = [...rows].sort(
    (a, b) => (valueOf(b) ?? 0) - (valueOf(a) ?? 0),
  );
  // 상위와 하위를 같이 보여준다 — 유입만 보면 "빠져나간 곳"을 영영 못 본다.
  const head = ranked.slice(0, limit);
  const tail = ranked.slice(-6).filter((r) => !head.includes(r));
  const shown = [...head, ...tail];
  const span = Math.max(
    ...shown.map((r) => Math.abs(valueOf(r) ?? 0)),
    Number.EPSILON,
  );

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden rounded-xl border border-hairline bg-canvas shadow-card">
      <div className="flex items-baseline justify-between gap-3 border-b border-hairline bg-ge-header px-4 py-2.5">
        <h2 className="text-[14px] font-extrabold tracking-tight text-white">
          분류별 개인 순매수 · {periodLabel}
        </h2>
        <span className="shrink-0 text-[11px] font-semibold text-white/70">
          {windowLabel}
        </span>
      </div>

      <div className="grid grid-cols-[1fr_34px_96px_82px_74px_78px] items-center gap-x-2 border-b border-hairline bg-ge-th px-4 py-1.5 text-[11px] font-bold text-ink-secondary">
        <span>분류</span>
        <span className="text-right">종목</span>
        <span />
        <span className="text-right">
          {metric === "amount" ? "개인 순매수" : "시총 대비"}
        </span>
        <span className="text-right">
          {metric === "amount" ? "시총 대비" : "순매수"}
        </span>
        <span className="text-right">수익률</span>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
        {shown.map((r, i) => {
          const v = valueOf(r) ?? 0;
          const w = (Math.abs(v) / span) * 50; // 좌우 각 50%
          const active = selected === r.key;
          const gap = i === head.length && tail.length > 0;
          return (
            <button
              key={r.key}
              type="button"
              onClick={() => onSelect(r.key)}
              title={`${[...r.path, r.label].join(" / ")} — ${r.n}종목 · 시총 ${fmtEok(r.mcap, false)}`}
              className={cn(
                "grid w-full grid-cols-[1fr_34px_96px_82px_74px_78px] items-center gap-x-2 border-b border-hairline/60 px-4 py-[7px] text-left transition-colors",
                active ? "bg-ge-blue-bg" : "hover:bg-canvas-soft",
                gap && "border-t-2 border-t-hairline",
              )}
            >
              <span className="min-w-0">
                <span
                  className={cn(
                    "block truncate text-[13px]",
                    active
                      ? "font-extrabold text-ge-point"
                      : "font-bold text-ink",
                  )}
                >
                  {r.label}
                </span>
                {r.path.length > 0 && (
                  <span className="block truncate text-[10.5px] font-medium text-ink-faint">
                    {r.path.join(" · ")}
                  </span>
                )}
              </span>

              <span className="text-right text-[11.5px] font-semibold tabular-nums text-ink-faint">
                {r.n}
              </span>

              {/* 0 을 가운데 둔 발산 막대. 숫자는 다음 칸에 따로 둔다 —
                  같은 칸에 겹치면 막대가 긴 행에서 글자가 막대 위로 올라간다. */}
              <span className="relative block h-[15px]">
                <span className="absolute inset-y-0 left-1/2 w-px bg-hairline" />
                <span
                  className={cn(
                    "absolute inset-y-[3px] rounded-[2px]",
                    v > 0 ? "left-1/2 bg-rose-500/85" : "right-1/2 bg-blue-500/85",
                  )}
                  style={{ width: `${w}%` }}
                />
              </span>

              <span
                className={cn(
                  "text-right text-[12px] font-extrabold tabular-nums",
                  tone(v),
                )}
              >
                {metric === "amount" ? fmtEok(v) : fmtRatio(v)}
              </span>

              <span
                className={cn(
                  "text-right text-[12px] font-semibold tabular-nums",
                  tone(metric === "amount" ? ratioOf(r) : netOf(r)),
                )}
              >
                {metric === "amount"
                  ? fmtRatio(ratioOf(r))
                  : fmtEok(netOf(r))}
              </span>

              <span
                className={cn(
                  "text-right text-[12.5px] font-extrabold tabular-nums",
                  tone(retOf(r)),
                )}
              >
                {fmtPct(retOf(r))}
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
