"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { PageContainer } from "@/components/layout/page-header";
import { Topbar } from "@/components/layout/topbar";
import { useAccount } from "@/components/layout/account-context";
import { Modal } from "@/components/ui/modal";
import { Cell, DataTable, SourceDownBanner, StatTile, StubCard } from "@/components/stub";
import {
  getEarnings,
  getEpsHistory,
  getPortfolioHoldings,
  getWatchlist,
  type EarningsEvent,
} from "@/lib/api";
import { cn } from "@/lib/utils";

// 미국 어닝 — 내 종목이 언제 실적을 내나.
//
// ★이 화면은 원래 원본 GE 의 collector 를 프록시해 503 이었다. Nasdaq 공개 API 로
//   다시 세웠다 — **키가 필요 없다**(야후는 막혔다: v7 quote 401,
//   v10 quoteSummary "Invalid Crumb").
//
// ★**60일을 본다.** 14일·30일 창에서는 내 보유 종목이 한 건도 안 걸렸다(실측).
//   미국 대형주는 분기 실적이라 한 달 창으로는 비는 구간이 길다.
//
// ★대상 종목은 **보유 + 관심종목**을 합친다. 관심종목에만 있는 것도 실적일에
//   움직이므로, 살지 말지 보는 중이라면 그 날짜를 알아야 한다.
//
// ⚠️먼 날짜의 발표 시각은 대개 "미정"이다. 발표가 가까워져야 장전/장후가 정해진다.

function eps(value: string | null): string {
  if (value == null) return "—";
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  return `${n > 0 ? "+" : ""}${n.toFixed(2)}`;
}

function dday(iso: string): number {
  const target = new Date(`${iso}T00:00:00`);
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  return Math.round((target.getTime() - today.getTime()) / 86_400_000);
}

function cap(value: string | null): string {
  if (value == null) return "—";
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  if (n >= 1e12) return `$${(n / 1e12).toFixed(1)}T`;
  if (n >= 1e9) return `$${(n / 1e9).toFixed(0)}B`;
  return `$${(n / 1e6).toFixed(0)}M`;
}

export default function EarningsPage() {
  const { accountId } = useAccount();
  const [picked, setPicked] = useState<EarningsEvent | null>(null);

  const holdings = useQuery({
    queryKey: ["portfolioHoldings", accountId],
    queryFn: () => getPortfolioHoldings(accountId),
    staleTime: 60_000,
  });
  const watchlist = useQuery({
    queryKey: ["watchlist"],
    queryFn: getWatchlist,
    staleTime: 60_000,
  });

  // 보유 + 관심을 합친다. 둘 다 로드된 뒤에야 조회한다 — 빈 목록으로 부르면
  // "내 종목 0건"이 캐시돼 새로고침 전까지 비어 보인다.
  const tickers = useMemo(() => {
    const set = new Set<string>();
    for (const h of holdings.data?.items ?? []) set.add(h.ticker);
    for (const w of watchlist.data?.items ?? []) set.add(w.ticker);
    return [...set].sort();
  }, [holdings.data, watchlist.data]);

  const ready = tickers.length > 0;
  const earnings = useQuery({
    queryKey: ["earnings", tickers],
    queryFn: () => getEarnings(tickers),
    enabled: ready,
    staleTime: 6 * 60 * 60_000,
  });

  const data = earnings.data;
  const mine = data?.mine ?? [];
  const soonest = mine[0];
  const withinTwoWeeks = mine.filter((e) => dday(e.report_date) <= 14).length;

  const loading = holdings.isLoading || watchlist.isLoading || earnings.isLoading;

  // ★"발표가 없다"와 "원천이 죽었다"는 **다른 상태**다. Nasdaq 이 응답하면 60일
  //   구간에는 언제나 수천 건이 있으므로(실측 4,201건), `total_scanned === 0` 은
  //   신뢰할 수 있는 장애 신호다. 이걸 구분하지 않으면 원천이 죽었을 때 화면이
  //   "향후 60일 안에 예정된 발표가 없습니다"라고 **거짓말**을 한다.
  const sourceDown =
    ready && !loading && (earnings.isError || (data?.total_scanned ?? 0) === 0);

  return (
    <>
      <Topbar title="미국 어닝" subtitle="내 종목 실적 발표 일정" />
      <PageContainer fit>
        {sourceDown && (
          <SourceDownBanner
            source="Nasdaq"
            detail="실적 일정 원천입니다. 발표가 없는 것이 아닙니다."
          />
        )}

        <div className="grid shrink-0 grid-cols-2 gap-2.5 lg:grid-cols-4">
          <StatTile
            label="내 종목 발표 예정"
            value={data ? `${mine.length}` : null}
            hint={data ? `향후 ${data.window_days}일` : "보유 + 관심종목"}
            loading={loading}
          />
          <StatTile
            label="가장 가까운 발표"
            value={soonest ? `D-${dday(soonest.report_date)}` : null}
            hint={soonest ? `${soonest.ticker} · ${soonest.report_date}` : "예정 없음"}
            loading={loading}
          />
          <StatTile
            label="2주 내"
            value={data ? `${withinTwoWeeks}` : null}
            hint="곧 발표하는 내 종목"
            accent={withinTwoWeeks > 0 ? "up" : "neutral"}
            loading={loading}
          />
          <StatTile
            label="추적 종목"
            value={ready ? `${tickers.length}` : null}
            hint={
              data
                ? `전체 ${data.total_scanned.toLocaleString()}건에서 추림`
                : "보유 + 관심종목"
            }
            loading={loading}
          />
        </div>

        <div
          className={cn(
            "grid min-h-0 flex-1 gap-3",
            "grid-cols-1 auto-rows-[minmax(0,1fr)]",
            "md:grid-cols-2 lg:auto-rows-auto",
            "lg:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]",
          )}
        >
          <StubCard
            title="내 종목 실적 일정"
            subtitle={data ? `향후 ${data.window_days}일 · ${mine.length}건` : "보유 + 관심종목"}
            scrollBody
          >
            {loading ? (
              <Empty text="불러오는 중…" />
            ) : !ready ? (
              <Empty text="보유 종목이나 관심종목이 있어야 표시됩니다" />
            ) : sourceDown ? (
              // ⚠️원천 장애일 때 "발표가 없습니다"라고 쓰면 안 된다 — 거짓이다.
              <Empty text="실적 일정을 받지 못했습니다" />
            ) : mine.length === 0 ? (
              <Empty text={`향후 ${data?.window_days ?? 60}일 안에 예정된 발표가 없습니다`} />
            ) : (
              <DataTable
                columns={["발표일", "종목", "컨센서스", "작년"]}
                align={["left", "left", "right", "right"]}
              >
                {mine.map((e) => {
                  const d = dday(e.report_date);
                  return (
                    <tr
                      key={`${e.report_date}-${e.ticker}`}
                      onClick={() => setPicked(e)}
                      className="cursor-pointer border-b border-hairline transition-colors hover:bg-canvas-soft"
                    >
                      <Cell left tone="muted">
                        <span className="flex items-baseline gap-1.5">
                          <span>{e.report_date}</span>
                          <span
                            className={cn(
                              "text-[10px] font-bold",
                              d <= 14 ? "text-ge-point" : "text-ink-faint",
                            )}
                          >
                            D-{d}
                          </span>
                        </span>
                      </Cell>
                      <Cell left strong>
                        <span className="flex items-center gap-1.5">
                          <span className="max-w-[130px] truncate">{e.company}</span>
                          <span className="shrink-0 text-[10px] font-bold text-ink-faint">
                            {e.ticker}
                          </span>
                        </span>
                      </Cell>
                      <Cell
                        strong
                        tone={
                          e.eps_forecast != null && Number(e.eps_forecast) < 0
                            ? "down"
                            : undefined
                        }
                      >
                        {eps(e.eps_forecast)}
                      </Cell>
                      <Cell tone="muted">{eps(e.last_year_eps)}</Cell>
                    </tr>
                  );
                })}
              </DataTable>
            )}
          </StubCard>

          <StubCard
            title="시장 맥락"
            subtitle={
              data ? `향후 ${data.major_window_days}일 대형주` : "근시일 대형주"
            }
            scrollBody
          >
            {loading ? (
              <Empty text="불러오는 중…" />
            ) : (data?.major.length ?? 0) === 0 ? (
              <Empty text="표시할 일정이 없습니다" />
            ) : (
              <>
                <p className="mb-2 text-[11px] leading-snug text-ink-muted">
                  내 종목은 아니지만 시장을 움직일 수 있는 발표입니다.
                </p>
                <DataTable
                  columns={["발표일", "종목", "시총"]}
                  align={["left", "left", "right"]}
                >
                  {(data?.major ?? []).map((e) => (
                    <tr
                      key={`${e.report_date}-${e.ticker}`}
                      onClick={() => setPicked(e)}
                      className="cursor-pointer border-b border-hairline transition-colors hover:bg-canvas-soft"
                    >
                      <Cell left tone="muted">
                        {e.report_date.slice(5)}
                      </Cell>
                      <Cell left strong>
                        <span className="flex items-center gap-1.5">
                          <span className="max-w-[110px] truncate">{e.company}</span>
                          <span className="shrink-0 text-[10px] font-bold text-ink-faint">
                            {e.ticker}
                          </span>
                        </span>
                      </Cell>
                      <Cell>{cap(e.market_cap)}</Cell>
                    </tr>
                  ))}
                </DataTable>
              </>
            )}
          </StubCard>
        </div>
      </PageContainer>

      <Modal
        open={picked != null}
        onClose={() => setPicked(null)}
        title={picked?.company ?? ""}
        subtitle={
          picked
            ? `${picked.ticker} · ${picked.report_date} · ${picked.timing}`
            : undefined
        }
      >
        {picked && <EventDetail event={picked} />}
      </Modal>
    </>
  );
}

function EventDetail({ event: e }: { event: EarningsEvent }) {
  const history = useQuery({
    queryKey: ["epsHistory", e.ticker],
    queryFn: () => getEpsHistory(e.ticker),
    staleTime: 6 * 60 * 60_000,
  });

  const rows = history.data ?? [];
  const past = rows.filter((r) => r.actual != null);
  const beats = past.filter((r) => r.surprise != null && Number(r.surprise) > 0).length;

  return (
    <div className="space-y-3">
      <dl className="grid grid-cols-2 gap-x-5 gap-y-0">
        <Row label="발표 예정일" value={`${e.report_date} (D-${dday(e.report_date)})`} />
        <Row label="발표 시각" value={e.timing} />
        <Row label="컨센서스 EPS" value={eps(e.eps_forecast)} />
        <Row label="작년 같은 분기" value={eps(e.last_year_eps)} />
        <Row label="추정치 수" value={e.estimate_count == null ? "—" : `${e.estimate_count}곳`} />
        <Row label="시가총액" value={cap(e.market_cap)} />
      </dl>

      {history.isLoading ? (
        <p className="text-[12px] text-ink-faint">실적 이력 불러오는 중…</p>
      ) : rows.length === 0 ? (
        <p className="text-[12px] text-ink-faint">분기별 실적 이력을 받지 못했습니다.</p>
      ) : (
        <div>
          <p className="mb-1.5 text-[11px] font-bold text-ink-muted">
            분기별 컨센서스 대비 실제
            {past.length > 0 && ` · 최근 ${past.length}회 중 ${beats}회 상회`}
          </p>
          <DataTable
            columns={["분기", "컨센서스", "실제", "서프라이즈"]}
            align={["left", "right", "right", "right"]}
          >
            {rows.map((r) => (
              <tr key={`${r.period}-${r.kind}`} className="border-b border-hairline">
                <Cell left strong>
                  <span className="flex items-center gap-1.5">
                    {r.period}
                    {r.actual == null && (
                      <span className="rounded bg-canvas-soft px-1 text-[9px] font-bold text-ink-muted">
                        예정
                      </span>
                    )}
                  </span>
                </Cell>
                <Cell>{eps(r.consensus)}</Cell>
                <Cell strong>{eps(r.actual)}</Cell>
                <Cell
                  tone={
                    r.surprise == null
                      ? undefined
                      : Number(r.surprise) > 0
                        ? "up"
                        : Number(r.surprise) < 0
                          ? "down"
                          : undefined
                  }
                >
                  {eps(r.surprise)}
                </Cell>
              </tr>
            ))}
          </DataTable>
        </div>
      )}

      <p className="text-[11px] leading-relaxed text-ink-muted">
        발표 전 분기는 실제 EPS 자리를 <strong>비워 둡니다</strong> — 원천(Nasdaq)은
        0.0 으로 주는데, 그대로 두면 &quot;컨센서스 대비 크게 하회&quot;라는 없는
        사실이 만들어집니다. 먼 날짜의 발표 시각이 &quot;미정&quot;인 것은
        정상입니다.
      </p>
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between border-b border-hairline py-2">
      <dt className="text-[12px] text-ink-secondary">{label}</dt>
      <dd className="text-[13px] font-bold tabular-nums text-ink">{value}</dd>
    </div>
  );
}

function Empty({ text }: { text: string }) {
  return (
    <div className="flex h-full items-center justify-center px-4 text-center">
      <span className="text-[12px] font-semibold text-ink-faint">{text}</span>
    </div>
  );
}
