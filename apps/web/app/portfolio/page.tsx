"use client";

import { useQuery } from "@tanstack/react-query";
import { getPortfolioOverview } from "@/lib/api";
import { ApiErrorBanner } from "@/components/states";
import { Topbar } from "@/components/layout/topbar";
import { SyncStatusLight } from "@/components/portfolio/sync-status-light";
import { SyncButton } from "@/components/portfolio/sync-button";
import { AllocationDonut } from "@/components/portfolio/allocation-donut";
import { PortfolioMetrics } from "@/components/portfolio/portfolio-metrics";
import { CashBox } from "@/components/portfolio/cash-box";
import { PositionsTable } from "@/components/portfolio/positions-table";
import { SetupCard } from "@/components/portfolio/setup-card";

export default function PortfolioDetailPage() {
  const overview = useQuery({
    queryKey: ["portfolio", "overview"],
    queryFn: getPortfolioOverview,
    refetchInterval: 5000,
  });

  const data = overview.data;
  const summary = data?.summary;
  const showSetup =
    data != null &&
    data.sync_status === "NEVER_SYNCED" &&
    !data.connection?.credentials_configured;

  // The API is the single source of this aggregation; empty only while loading.
  const breakdown = data?.asset_class_breakdown ?? [];

  return (
    <>
      <Topbar
        title="포트폴리오 상세"
        status={<SyncStatusLight />}
        actions={<SyncButton />}
      />

      <div className="mx-auto max-w-[1600px] px-6 py-6">
        {overview.isError && (
          <div className="mb-6">
            <ApiErrorBanner error={overview.error} />
          </div>
        )}

        {showSetup ? (
          <SetupCard />
        ) : (
          <div className="space-y-4">
            <div className="grid gap-4 xl:grid-cols-3">
              <AllocationDonut
                breakdown={breakdown}
                totalAssetsKrw={summary?.total_assets_krw}
                loading={overview.isLoading}
              />
              <div className="xl:col-span-2">
                <PortfolioMetrics
                  summary={summary}
                  loading={overview.isLoading}
                />
              </div>
            </div>

            <CashBox
              cashBalances={data?.cash_balances}
              cashValueKrw={summary?.cash_value_krw}
              loading={overview.isLoading}
            />

            <PositionsTable
              accounts={data?.accounts ?? []}
              syncStatus={data?.sync_status ?? "NEVER_SYNCED"}
              totalAssetsKrw={summary?.total_assets_krw}
            />
          </div>
        )}
      </div>
    </>
  );
}
