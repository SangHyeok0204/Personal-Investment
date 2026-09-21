"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { ArrowRight } from "lucide-react";
import { PageContainer } from "@/components/layout/page-header";
import { Topbar } from "@/components/layout/topbar";
import { useAccount } from "@/components/layout/account-context";
import {
  Cell,
  DataTable,
  NotConnectedBanner,
  PlannedList,
  StatRow,
  StatTile,
  StubCard,
  StubChart,
  toneOf,
} from "@/components/stub";
import {
  getPerformance,
  getPortfolioAllocation,
  getPortfolioHoldings,
  getPortfolioSummary,
  type PortfolioHolding,
  type PortfolioSummary,
} from "@/lib/api";
import { SeriesChart } from "@/components/charts/series-chart";
import { cn } from "@/lib/utils";
import {
  formatKrwSigned,
  formatKrwString,
  formatPercentString,
  formatPriceString,
  formatQuantityString,
} from "@/lib/format";

// 개인 대시보드의 1면 — 자산 현황.
//
// ★2026-09-21 2차: 상단 4칸·보유 종목 표를 실제 API(/api/v1/portfolio/*)에 물렸다.
//   계좌가 아직 없으면 서버가 합계를 null 로 주고, 화면은 "—" 와 연동 안내를 띄운다.
//   0원으로 그리지 않는다 — 0원과 미연동은 다른 상태다.
//
// 자산 추이·자산 배분은 아직 골격이다: 추이는 portfolio_snapshots 가 쌓여야 의미가
// 있고(수집 배치가 먼저), 배분은 종목 분류(0003) 를 붙여야 한다.

export default function PortfolioPage() {
  const { accountId, connected, isError: accountsError } = useAccount();

  const summary = useQuery({
    queryKey: ["portfolioSummary", accountId],
    queryFn: () => getPortfolioSummary(accountId),
    staleTime: 30_000,
  });

  const holdings = useQuery({
    queryKey: ["portfolioHoldings", accountId],
    queryFn: () => getPortfolioHoldings(accountId),
    staleTime: 30_000,
  });

  const allocation = useQuery({
    queryKey: ["portfolioAllocation", "sector", accountId],
    queryFn: () => getPortfolioAllocation("sector", accountId),
    staleTime: 30_000,
  });

  // 자산 추이 — 우리가 스냅샷을 쌓지 않고 증권사가 들고 있던 과거를 읽는다.
  const performance = useQuery({
    queryKey: ["performance", accountId, 365],
    queryFn: () => getPerformance(accountId, 365),
    staleTime: 60_000,
  });

  const s = summary.data;
  const rows = holdings.data?.items ?? [];
  const loading = summary.isLoading;

  return (
    <>
      <Topbar title="자산 현황" subtitle="전체 계좌 합산 · 실시간 평가" />
      <PageContainer wide>
        {!connected && (
          <NotConnectedBanner
            what="키움 계좌 API"
            message={
              accountsError
                ? "API 서버에 연결하지 못했습니다 — 백엔드(uvicorn)가 떠 있는지 확인하세요."
                : undefined
            }
          />
        )}

        <StatRow>
          <StatTile
            label="총 평가금액"
            value={formatKrwString(s?.total_assets_krw)}
            hint="보유종목 평가액 + 예수금"
            loading={loading}
          />
          <StatTile
            label="평가손익"
            value={formatKrwSigned(s?.unrealized_pnl_krw)}
            hint={
              s?.unrealized_return != null
                ? `매입원가 대비 ${formatPercentString(s.unrealized_return)}`
                : "매입원가 대비"
            }
            accent="auto"
            loading={loading}
          />
          <StatTile
            label="보유종목 평가액"
            value={formatKrwString(s?.securities_value_krw)}
            hint={
              s?.position_count ? `${s.position_count}종목` : "보유 종목 평가액"
            }
            loading={loading}
          />
          <StatTile
            label="예수금"
            value={formatKrwString(s?.cash_krw)}
            // 환율이 없어 KRW 합계에 못 들어간 외화를 여기서 드러낸다 —
            // 합계만 보여주면 그 돈이 화면에서 통째로 사라진다.
            hint={foreignCashHint(s) ?? "주문 가능 금액"}
            loading={loading}
          />
        </StatRow>

        <div className="grid gap-4 xl:grid-cols-[1.6fr_1fr]">
          <StubCard
            title="자산 추이"
            subtitle={
              performance.data?.first_date
                ? `${performance.data.first_date} ~ ${performance.data.last_date}`
                : "예탁자산 시계열"
            }
          >
            {performance.data && performance.data.items.length > 0 ? (
              <>
                <SeriesChart
                  height={230}
                  points={performance.data.items.map((p) => ({
                    date: p.base_date,
                    value: p.deposit_assets_krw == null ? null : Number(p.deposit_assets_krw),
                  }))}
                  tooltipFormat={(p) =>
                    formatKrwString(p.value == null ? null : String(Math.round(p.value)))
                  }
                />
                {/* ⚠️(끝-시작)을 수익이라 부르지 않는다 — 그 사이 입금이 수익으로 보인다. */}
                <dl className="mt-2 grid grid-cols-3 gap-2 border-t border-hairline pt-2.5 text-[11px]">
                  <div>
                    <dt className="text-ink-muted">순입금</dt>
                    <dd className="font-bold tabular-nums text-ink-secondary">
                      {formatKrwString(performance.data.net_deposit_krw)}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-ink-muted">입출금 제외 증감</dt>
                    <dd
                      className={cn(
                        "font-extrabold tabular-nums",
                        Number(performance.data.gain_krw ?? 0) >= 0 ? "text-bid" : "text-ask",
                      )}
                    >
                      {formatKrwSigned(performance.data.gain_krw)}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-ink-muted">기간</dt>
                    <dd className="font-bold tabular-nums text-ink-secondary">
                      {performance.data.items.length}일
                    </dd>
                  </div>
                </dl>
              </>
            ) : (
              <StubChart
                height={260}
                note={performance.isLoading ? "불러오는 중…" : "계좌 성과 데이터 없음"}
              />
            )}
          </StubCard>

          <StubCard
            title="섹터 배분"
            subtitle={
              allocation.data?.unclassified_market_value_krw &&
              Number(allocation.data.unclassified_market_value_krw) > 0
                ? `미분류 ${formatKrwString(allocation.data.unclassified_market_value_krw)} 포함`
                : "평가금액(KRW) 기준"
            }
          >
            {allocation.data && allocation.data.items.length > 0 ? (
              <div className="space-y-2.5">
                {allocation.data.items.slice(0, 7).map((slice) => {
                  const pct = Number(slice.weight) * 100;
                  return (
                    <div key={slice.key ?? "__none__"}>
                      <div className="mb-1 flex items-baseline justify-between gap-2">
                        <span
                          className={cn(
                            "text-[12px] font-extrabold",
                            slice.key == null ? "text-ink-muted" : "text-ge-navy",
                          )}
                        >
                          {slice.label}
                        </span>
                        <span className="text-[11px] font-bold tabular-nums text-ink-secondary">
                          {pct.toFixed(1)}%
                        </span>
                      </div>
                      <div className="h-1.5 w-full overflow-hidden rounded-full bg-canvas-soft">
                        <div
                          className={cn(
                            "h-full rounded-full",
                            slice.key == null ? "bg-slate-300" : "bg-ge-point",
                          )}
                          style={{ width: `${pct}%` }}
                        />
                      </div>
                    </div>
                  );
                })}
                <Link
                  href="/portfolio/allocation"
                  className="mt-1 inline-block text-[11px] font-bold text-ge-point hover:text-ge-navy"
                >
                  전체 배분 보기 →
                </Link>
              </div>
            ) : (
              <StubChart
                height={260}
                note={allocation.isLoading ? "불러오는 중…" : "분류된 보유 종목 없음"}
              />
            )}
          </StubCard>

          <StubCard
            title="보유 종목"
            subtitle={
              holdings.data?.total_market_value_krw
                ? `평가금액 합계 ${formatKrwString(holdings.data.total_market_value_krw)}`
                : "평가금액 순"
            }
            className="xl:col-span-2"
          >
            <DataTable
              columns={[
                "종목",
                "수량",
                "평단",
                "현재가",
                "평가금액",
                "평가손익",
                "수익률",
                "비중",
              ]}
              align={["left", "right", "right", "right", "right", "right", "right", "right"]}
              empty={
                holdings.isLoading
                  ? "불러오는 중…"
                  : connected
                    ? "보유 종목이 없습니다"
                    : "계좌를 연동하면 보유 종목이 표시됩니다"
              }
            >
              {rows.map((h) => (
                <HoldingRow
                  key={`${h.account_id}-${h.asset_id}`}
                  holding={h}
                  totalKrw={holdings.data?.total_market_value_krw ?? null}
                />
              ))}
            </DataTable>
          </StubCard>

          <StubCard title="오늘 체결" subtitle="당일 매매">
            <DataTable
              columns={["시각", "종목", "구분", "수량", "단가"]}
              empty="체결 수집이 아직 연결되지 않았습니다"
            >
              {null}
            </DataTable>
          </StubCard>

          <StubCard title="연동하면 채워질 것들">
            <PlannedList
              items={[
                "키움 REST 잔고조회 → 보유종목·평단·평가손익 (API 배선 완료, 수집기 대기)",
                "일별 잔고 스냅샷 적재 → 자산 추이 차트",
                "종목 분류(alembic 0003) 연결 → 자산 배분 원형",
                "체결 내역 수집 → 오늘 체결 · 매매일지 자동 초안",
                "토스 계좌 합산 → 계좌별/통합 뷰 전환",
              ]}
            />
          </StubCard>
        </div>

        <div className="mt-4">
          <Link
            href="/portfolio/holdings"
            className="group inline-flex items-center gap-2 text-[13px] font-bold text-ge-point transition-colors hover:text-ge-navy"
          >
            보유 종목 전체 보기
            <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" />
          </Link>
        </div>
      </PageContainer>
    </>
  );
}

function HoldingRow({
  holding: h,
  totalKrw,
}: {
  holding: PortfolioHolding;
  totalKrw: string | null;
}) {
  // 비중은 KRW 평가액 기준. 합계를 모르면 계산하지 않는다(빈칸이 거짓말보다 낫다).
  const weight =
    totalKrw && h.market_value_krw && Number(totalKrw) !== 0
      ? `${((Number(h.market_value_krw) / Number(totalKrw)) * 100).toFixed(1)}%`
      : "—";

  return (
    <tr className="border-t border-hairline transition-colors hover:bg-canvas-soft/60">
      <Cell left strong>
        <span className="flex items-center gap-2">
          {h.name ?? h.ticker}
          <span className="text-[10px] font-semibold text-ink-faint">
            {h.ticker}
          </span>
          {h.currency !== "KRW" && (
            <span className="rounded bg-ge-blue-bg px-1.5 py-0.5 text-[10px] font-bold text-ge-point">
              {h.currency}
            </span>
          )}
        </span>
      </Cell>
      <Cell>{formatQuantityString(h.quantity)}</Cell>
      <Cell>{formatPriceString(h.average_purchase_price, h.currency)}</Cell>
      <Cell>{formatPriceString(h.current_price, h.currency)}</Cell>
      <Cell strong>{formatKrwString(h.market_value_krw)}</Cell>
      <Cell tone={toneOf(h.unrealized_pnl_krw)}>
        {formatKrwSigned(h.unrealized_pnl_krw)}
      </Cell>
      <Cell tone={toneOf(h.unrealized_return)}>
        {formatPercentString(h.unrealized_return)}
      </Cell>
      <Cell tone="muted">{weight}</Cell>
    </tr>
  );
}

/** KRW 합계에 못 들어간 외화 예수금을 한 줄로. 없으면 null. */
function foreignCashHint(s: PortfolioSummary | undefined): string | null {
  if (!s) return null;
  const unconverted = (s.cash_by_currency ?? []).filter(
    (c) => c.currency !== "KRW" && c.krw_value == null,
  );
  if (unconverted.length === 0) {
    return s.available_cash_krw != null
      ? `주문가능 ${formatKrwString(s.available_cash_krw)}`
      : null;
  }
  const parts = unconverted.map(
    (c) => `${c.currency} ${formatQuantityString(c.cash_balance)}`,
  );
  return `+ ${parts.join(" · ")} (환율 없음, 합계 제외)`;
}
