"use client";

import { useQuery } from "@tanstack/react-query";
import { getRateTopics, type RateTopics } from "@/lib/api";
import { cn } from "@/lib/utils";
import { POLL_MS } from "@/components/ai-key-data/poll";
import { useCardZoom, ZoomButton } from "@/components/ai-key-data/card-zoom";

// [하이퍼스케일러 채권 발행] — 금리_2.xlsx 금리(1) 시트.
// AI 인프라 자본지출이 부채 조달로 넘어간 정도를 재는 카드다: 연 $19B(2024) →
// $108B(2025) → 8개월 만에 $223B(2026).
//
// ★차트가 아니라 **막대 + 발행사 목록**인 이유: 관측치가 연도 7개뿐이라 선을 그으면
//   점 7개를 잇는 꼴이고(dataviz: 한 줌이면 표/막대), 정작 궁금한 "누가 얼마나"는
//   발행사별 합계가 답한다.
// ⚠️금액은 **발행 통화 액면을 그대로 합산**한 값이다(워크북 Year 요약 열의 정의).
//   USD 가 $400B 로 대부분이지만 EUR·CAD·GBP·CHF·AUD·JPY 가 섞여 있다 — 부제에 적어
//   숫자만 보고 순수 달러로 읽지 않게 한다.

const BAR = "#4a7ab5";
const BAR_SOFT = "#c9d9ec";
// 제목 띠 강조색은 tailwind 토큰 `ge-header`(#483629) — 2026-08-28 카드 6장이
// 같이 쓰게 되면서 raw hex 를 토큰으로 승격했다.

const fmtB = (v: number) => `$${v.toLocaleString("en-US", { maximumFractionDigits: 1 })}B`;

export function BondIssuanceCard({
  tabs,
  colSpan = 2,
}: {
  tabs?: React.ReactNode;
  colSpan?: 1 | 2 | 3;
}) {
  const { zoomed, toggle, zoomCls } = useCardZoom();
  const { data, isLoading, isError } = useQuery<RateTopics>({
    queryKey: ["rate-topics"],
    queryFn: getRateTopics,
    refetchInterval: POLL_MS,
  });
  const b = data?.bonds ?? null;
  const years = b?.by_year ?? [];
  const max = Math.max(1, ...years.map(([, v]) => v));
  const thisYear = years.length ? years[years.length - 1] : null;

  return (
    <section
      className={cn(
        zoomCls,
        "flex min-h-0 flex-col rounded-xl border border-hairline bg-canvas",
        // 정적 클래스로 적어야 tailwind 가 스캔한다(형제 카드들과 같은 이유).
        colSpan === 1 ? "lg:col-span-1" : colSpan === 3 ? "lg:col-span-3" : "lg:col-span-2",
      )}
    >
      {/* 강조 띠 — 배경이 어두우므로 글자를 흰색 계열로 뒤집는다. */}
      <header className="flex items-center gap-2 rounded-t-xl bg-ge-header px-3 py-1.5">
        {tabs ?? (
          <h2 className="shrink-0 text-[15px] font-extrabold text-white">
            하이퍼스케일러 채권 발행
          </h2>
        )}
        <span className="min-w-0 truncate text-[13px] text-white/70">
          발행 통화 액면 합산 · AI 자본지출의 부채 조달
        </span>
        {b?.asof ? (
          <span className="ml-auto shrink-0 text-[13px] tabular-nums text-white/60">
            {b.asof} 기준
          </span>
        ) : null}
      <ZoomButton zoomed={zoomed} onToggle={toggle} />
      </header>

      {isLoading ? (
        <Center msg="불러오는 중…" />
      ) : isError ? (
        <Center msg="collector 에 못 닿았습니다." tone="text-rose-600" />
      ) : !b || years.length === 0 ? (
        <Center
          msg={data?.note ?? "금리_2.xlsx 판독 대기 중 — 데이터가 들어오면 자동 표시됩니다."}
          tone={data?.note ? "text-amber-600" : undefined}
        />
      ) : (
        <div className="flex min-h-0 flex-1 flex-col gap-1.5 overflow-y-auto px-3 py-1.5">
          {/* 올해 발행액을 크게 — 카드의 논지가 이 숫자다. */}
          <div className="flex shrink-0 items-baseline gap-2">
            <span className="text-[24px] font-extrabold leading-none tabular-nums text-ink">
              {thisYear ? fmtB(thisYear[1]) : "—"}
            </span>
            <span className="text-[13px] text-ink-muted">
              {thisYear ? `${thisYear[0]}년 누계` : ""} · 총 {fmtB(b.total_b)} · {b.n}건
            </span>
          </div>

          {/* 연도별 막대 — 값이 7개뿐이라 가로 막대가 제일 곧게 읽힌다.
              행마다 flex-1 로 카드 세로를 나눠 갖는다(고정 높이면 아래가 텅 빈다). */}
          <div className="flex min-h-0 min-w-0 flex-1 flex-col gap-1">
            {years.map(([y, v]) => (
              <div key={y} className="flex min-h-[15px] flex-1 items-center gap-2">
                <span className="w-[34px] shrink-0 text-right text-[13px] tabular-nums text-ink-muted">
                  {y}
                </span>
                <div className="h-full min-w-0 flex-1 rounded-sm bg-canvas-soft">
                  <div
                    className="h-full rounded-sm"
                    style={{
                      width: `${Math.max(1, (v / max) * 100)}%`,
                      background: y === thisYear?.[0] ? BAR : BAR_SOFT,
                    }}
                  />
                </div>
                <span className="w-[56px] shrink-0 text-right text-[13px] font-bold tabular-nums text-ink">
                  {fmtB(v)}
                </span>
              </div>
            ))}
          </div>

          {/* 발행사별 — "누가 얼마나"가 이 데이터의 두 번째 질문이다. */}
          <div className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 border-t border-hairline pt-1.5 text-[13px]">
            {b.by_issuer
              .filter((g) => g.amt_b >= 0.1)
              .map((g) => (
                <span key={g.ticker} className="flex items-baseline gap-1">
                  <span className="font-bold text-ink">{g.ticker}</span>
                  <span className="tabular-nums text-ink-muted">
                    {fmtB(g.amt_b)}
                    <span className="text-slate-400"> ({g.n}건)</span>
                  </span>
                </span>
              ))}
          </div>
        </div>
      )}
    </section>
  );
}

function Center({ msg, tone }: { msg: string; tone?: string }) {
  return (
    <div className="flex min-h-0 flex-1 items-center justify-center px-6 text-center">
      <span className={cn("text-[13.5px] font-semibold leading-relaxed text-ink-muted", tone)}>
        {msg}
      </span>
    </div>
  );
}
