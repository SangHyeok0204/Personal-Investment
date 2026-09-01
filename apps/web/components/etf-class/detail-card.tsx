"use client";

import type { EtfIvKey, EtfPeriodKey, EtfRow } from "@/lib/api";
import { cn } from "@/lib/utils";
import { fmtEok, fmtPct, tone } from "./format";

// [국내상장 ETF] 고른 분류 안의 개별 ETF.
//
// 분류 수준의 합계만 보면 "그 분류가 통째로 그랬다"고 읽히기 쉽다. 실제로는 한두 종목이
// 분류 전체를 끌고 가는 경우가 흔해서(단일종목 레버리지 3종이 그 분류의 대부분) 항상
// 종목 단위를 같이 편다. 정렬은 고른 기간의 순매수 내림차순 — 랭킹 표와 같은 기준이다.

export function DetailCard({
  title,
  subtitle,
  rows,
  periodKey,
  mode,
  periodLabel,
  limit = 40,
}: {
  title: string;
  subtitle: string;
  rows: EtfRow[];
  periodKey: EtfPeriodKey;
  mode: "cum" | "iv";
  periodLabel: string;
  limit?: number;
}) {
  const netOf = (e: EtfRow) =>
    mode === "cum"
      ? e.net_cum[periodKey]
      : e.net_iv[periodKey as EtfIvKey] ?? null;
  const retOf = (e: EtfRow) =>
    mode === "cum"
      ? e.ret_cum[periodKey]
      : e.ret_iv[periodKey as EtfIvKey] ?? null;

  const sorted = [...rows].sort((a, b) => (netOf(b) ?? 0) - (netOf(a) ?? 0));
  const shown = sorted.slice(0, limit);
  const hidden = sorted.length - shown.length;

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden rounded-xl border border-hairline bg-canvas shadow-card">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1 border-b border-hairline bg-ge-header px-4 py-2.5">
        <h2 className="min-w-0 truncate text-[14px] font-extrabold tracking-tight text-white">
          {title}
        </h2>
        <span className="shrink-0 text-[11px] font-semibold text-white/70">
          {subtitle}
        </span>
      </div>

      <div className="grid grid-cols-[1fr_88px_74px_88px] items-center gap-x-2 border-b border-hairline bg-ge-th px-4 py-1.5 text-[11px] font-bold text-ink-secondary">
        <span>ETF</span>
        <span className="text-right">개인 순매수</span>
        <span className="text-right">수익률</span>
        <span className="text-right">시총</span>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
        {shown.length === 0 && (
          <div className="px-4 py-6 text-center text-[12px] text-ink-faint">
            분류를 고르면 그 안의 ETF 가 여기 나옵니다
          </div>
        )}
        {shown.map((e) => (
          <div
            key={e.code}
            className="grid grid-cols-[1fr_88px_74px_88px] items-center gap-x-2 border-b border-hairline/60 px-4 py-[6px]"
            title={`${e.code} · ${e.country} · ${e.small}`}
          >
            <span className="min-w-0">
              <span className="block truncate text-[12.5px] font-semibold text-ink">
                {e.interest && (
                  <span className="mr-1 rounded bg-ge-blue-bg px-1 text-[9.5px] font-extrabold text-ge-point align-middle">
                    관심
                  </span>
                )}
                {e.name}
              </span>
              <span className="block truncate text-[10px] font-medium text-ink-faint">
                {e.small || e.mid} · {e.country}
              </span>
            </span>
            <span
              className={cn(
                "text-right text-[12px] font-bold tabular-nums",
                tone(netOf(e)),
              )}
            >
              {fmtEok(netOf(e))}
            </span>
            <span
              className={cn(
                "text-right text-[12px] font-extrabold tabular-nums",
                tone(retOf(e)),
              )}
            >
              {fmtPct(retOf(e), 1)}
            </span>
            <span className="text-right text-[11.5px] font-semibold tabular-nums text-ink-muted">
              {fmtEok(e.mcap, false)}
            </span>
          </div>
        ))}
        {hidden > 0 && (
          <div className="px-4 py-2 text-center text-[11px] font-medium text-ink-faint">
            외 {hidden}종목 — {periodLabel} 순매수 상위 {limit}개만 표시
          </div>
        )}
      </div>
    </div>
  );
}
