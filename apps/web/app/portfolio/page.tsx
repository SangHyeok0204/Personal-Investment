"use client";

import { useQuery } from "@tanstack/react-query";
import { getPortfolioOverview } from "@/lib/api";
import { ApiErrorBanner } from "@/components/states";
import { PortfolioHeader } from "@/components/portfolio/portfolio-header";
import { SummaryCards } from "@/components/portfolio/summary-cards";
import { MarketCards } from "@/components/portfolio/market-cards";
import { PositionsTable } from "@/components/portfolio/positions-table";
import { DataStatusPanel } from "@/components/portfolio/data-status-panel";
import { SetupCard } from "@/components/portfolio/setup-card";

export default function PortfolioDetailPage() {
  const overview = useQuery({
    queryKey: ["portfolio", "overview"],
    queryFn: getPortfolioOverview,
    refetchInterval: 5000,
  });

  const data = overview.data;
  const showSetup =
    data != null &&
    data.sync_status === "NEVER_SYNCED" &&
    !data.connection?.credentials_configured;

  return (
    <div className="mx-auto max-w-[1600px] px-8 py-8">
      <header className="mb-6">
        <h1 className="text-2xl font-semibold tracking-tight text-slate-900">
          포트폴리오 상세
        </h1>
        <p className="mt-1 text-sm text-slate-500">
          키움증권 계좌의 전체 보유 종목. 메인 대시보드에서 제외한 종목도 모두 포함합니다.
        </p>
      </header>

      {overview.isError && (
        <div className="mb-6">
          <ApiErrorBanner error={overview.error} />
        </div>
      )}

      <section className="space-y-6">
        <PortfolioHeader
          connection={data?.connection ?? null}
          lastSyncedAt={data?.last_synced_at ?? null}
          syncStatus={data?.sync_status ?? "NEVER_SYNCED"}
          loading={overview.isLoading}
        />

        {showSetup ? (
          <SetupCard />
        ) : (
          <>
            <SummaryCards summary={data?.summary} loading={overview.isLoading} />
            <MarketCards
              marketBreakdown={data?.market_breakdown}
              cashBalances={data?.cash_balances}
              loading={overview.isLoading}
            />
            <PositionsTable
              accounts={data?.accounts ?? []}
              syncStatus={data?.sync_status ?? "NEVER_SYNCED"}
              totalSecuritiesKrw={data?.summary?.securities_value_krw}
            />
          </>
        )}

        <DataStatusPanel
          lastSyncedAt={data?.last_synced_at ?? null}
          syncStatus={data?.sync_status ?? "NEVER_SYNCED"}
          lastError={data?.connection?.last_error}
        />
      </section>
    </div>
  );
}
