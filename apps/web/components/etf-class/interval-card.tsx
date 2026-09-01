"use client";

import type { EtfGroupRow, EtfIntervalSpec, EtfIvKey } from "@/lib/api";
import { cn } from "@/lib/utils";
import { fmtEok, fmtPct, tone } from "./format";

// [국내상장 ETF] 구간 분해 — "언제 들어왔고, 그때 얼마였나".
//
// ★★이 카드가 이 페이지의 HISTORICAL 을 **첫날부터** 성립시킨다. 원천 워크북은 매일
//   덮어써서 과거가 없지만, 시트가 1주·1개월·3개월·6개월 **누적**을 같이 주므로 누적을
//   빼면 겹치지 않는 네 구간이 나온다(계산은 서버에서 한다 — etf_class._etf_metrics).
//   합·체인 항등식은 서버 테스트에서 오차 0 으로 확인했다.
// ★열 순서는 **왼쪽이 과거**다. 시트 순서(1w→6m)를 그대로 쓰면 시간이 거꾸로 흐른다.
// ★한 칸에 순매수 막대와 구간 수익률을 겹쳐 둔 이유: 둘을 따로 두면 "들어온 구간"과
//   "빠진 구간"을 눈으로 맞춰야 한다. 이 카드의 요점이 바로 그 대응이다.

export function IntervalCard({
  rows,
  intervals,
  selected,
  onSelect,
  limit = 14,
}: {
  rows: EtfGroupRow[];
  intervals: EtfIntervalSpec[];
  selected: string | null;
  onSelect: (key: string) => void;
  limit?: number;
}) {
  // 왼쪽이 과거 — 3~6개월 → 1~3개월 → 1주~1개월 → 최근 1주
  const cols = [...intervals].reverse();
  const ranked = [...rows]
    .filter((r) => r.net_cum["6m"] != null)
    .sort((a, b) => Math.abs(b.net_cum["6m"] ?? 0) - Math.abs(a.net_cum["6m"] ?? 0))
    .slice(0, limit);

  // 막대 스케일은 화면에 보이는 모든 칸의 최대 절댓값 하나로 — 열마다 따로 잡으면
  // "최근 1주 200억" 이 "1~3개월 11조" 와 같은 길이로 그려진다.
  const span = Math.max(
    ...ranked.flatMap((r) => cols.map((c) => Math.abs(r.net_iv[c.key as EtfIvKey] ?? 0))),
    Number.EPSILON,
  );

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden rounded-xl border border-hairline bg-canvas shadow-card">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1 border-b border-hairline bg-ge-header px-4 py-2.5">
        <h2 className="text-[14px] font-extrabold tracking-tight text-white">
          구간 분해 — 언제 들어왔고, 그 구간 수익률은
        </h2>
        <span className="shrink-0 text-[11px] font-semibold text-white/70">
          겹치지 않는 4구간 · 막대 = 개인 순매수 · 숫자 = 시총가중 수익률
        </span>
      </div>

      <div
        className="grid items-center gap-x-2 border-b border-hairline bg-ge-th px-4 py-1.5 text-[11px] font-bold text-ink-secondary"
        style={{ gridTemplateColumns: `minmax(0,1.4fr) repeat(${cols.length}, minmax(0,1fr))` }}
      >
        <span>분류</span>
        {cols.map((c) => (
          <span key={c.key} className="text-center">
            {c.label}
            <span className="ml-1 font-medium text-ink-faint">
              {c.start ? c.start.slice(5).replace("-", "/") : ""}~
              {c.end ? c.end.slice(5).replace("-", "/") : ""}
            </span>
          </span>
        ))}
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
        {ranked.map((r) => {
          const active = selected === r.key;
          return (
            <button
              key={r.key}
              type="button"
              onClick={() => onSelect(r.key)}
              className={cn(
                "grid w-full items-center gap-x-2 border-b border-hairline/60 px-4 py-[7px] text-left transition-colors",
                active ? "bg-ge-blue-bg" : "hover:bg-canvas-soft",
              )}
              style={{ gridTemplateColumns: `minmax(0,1.4fr) repeat(${cols.length}, minmax(0,1fr))` }}
            >
              <span className="min-w-0">
                <span
                  className={cn(
                    "block truncate text-[13px]",
                    active ? "font-extrabold text-ge-point" : "font-bold text-ink",
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

              {cols.map((c) => {
                const k = c.key as EtfIvKey;
                const net = r.net_iv[k];
                const ret = r.ret_iv[k];
                const w = (Math.abs(net ?? 0) / span) * 50;
                return (
                  <span key={c.key} className="block min-w-0 px-1">
                    <span className="relative block h-[14px]">
                      <span className="absolute inset-y-0 left-1/2 w-px bg-hairline" />
                      <span
                        className={cn(
                          "absolute inset-y-[3px] rounded-[2px]",
                          (net ?? 0) > 0
                            ? "left-1/2 bg-rose-500/80"
                            : "right-1/2 bg-blue-500/80",
                        )}
                        style={{ width: `${w}%` }}
                      />
                    </span>
                    <span className="mt-0.5 flex items-baseline justify-between gap-1">
                      <span
                        className={cn(
                          "truncate text-[10.5px] font-semibold tabular-nums",
                          tone(net),
                        )}
                      >
                        {fmtEok(net)}
                      </span>
                      <span
                        className={cn(
                          "shrink-0 text-[11.5px] font-extrabold tabular-nums",
                          tone(ret),
                        )}
                      >
                        {fmtPct(ret, 1)}
                      </span>
                    </span>
                  </span>
                );
              })}
            </button>
          );
        })}
      </div>
    </div>
  );
}
