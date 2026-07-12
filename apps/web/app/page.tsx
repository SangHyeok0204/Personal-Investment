"use client";

import { useQuery } from "@tanstack/react-query";
import {
  getHealth,
  getJobStats,
  getJobs,
  getPortfolioOverview,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import { formatDateTime } from "@/lib/format";
import { PageContainer, PageHeader } from "@/components/layout/page-header";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusBadge } from "@/components/status-badge";
import { ApiErrorBanner, EmptyState } from "@/components/states";
import { PortfolioHeader } from "@/components/portfolio/portfolio-header";
import { SummaryCards } from "@/components/portfolio/summary-cards";
import { MarketCards } from "@/components/portfolio/market-cards";
import { PositionsTable } from "@/components/portfolio/positions-table";
import { DataStatusPanel } from "@/components/portfolio/data-status-panel";
import { SetupCard } from "@/components/portfolio/setup-card";

export default function OverviewPage() {
  const overview = useQuery({
    queryKey: ["portfolio", "overview"],
    queryFn: getPortfolioOverview,
    refetchInterval: 5000,
  });
  const health = useQuery({
    queryKey: ["health"],
    queryFn: getHealth,
    refetchInterval: 5000,
  });
  const stats = useQuery({
    queryKey: ["jobStats"],
    queryFn: getJobStats,
    refetchInterval: 5000,
  });
  const recent = useQuery({
    queryKey: ["jobs", { limit: 5 }],
    queryFn: () => getJobs({ limit: 5 }),
    refetchInterval: 5000,
  });

  const data = overview.data;
  const showSetup =
    data != null &&
    data.sync_status === "NEVER_SYNCED" &&
    !data.connection?.credentials_configured;

  const tiles = [
    { label: "Total", value: stats.data?.total, dot: null },
    { label: "Pending", value: stats.data?.pending, dot: "bg-ink-faint" },
    { label: "Running", value: stats.data?.running, dot: "bg-status-running" },
    { label: "Success", value: stats.data?.success, dot: "bg-status-success" },
    { label: "Failed", value: stats.data?.failed, dot: "bg-status-failed" },
  ];

  return (
    <PageContainer>
      <PageHeader
        title="포트폴리오"
        description="키움증권 계좌 자산 및 보유 종목 현황"
      />

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
            />
          </>
        )}

        <DataStatusPanel
          lastSyncedAt={data?.last_synced_at ?? null}
          syncStatus={data?.sync_status ?? "NEVER_SYNCED"}
          lastError={data?.connection?.last_error}
        />
      </section>

      <div className="mt-12 border-t border-hairline pt-10">
        {health.isError && (
          <div className="mb-6">
            <ApiErrorBanner error={health.error} />
          </div>
        )}

        <div className="grid gap-6 lg:grid-cols-2">
          <Card>
            <CardHeader>
              <span className="eyebrow">System Status</span>
              <CardTitle>Connections</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <StatusLine
                label="API"
                loading={health.isLoading}
                ok={!health.isError}
                okText="Connected"
                failText="Unreachable"
              />
              <StatusLine
                label="Database"
                loading={health.isLoading}
                ok={!health.isError && health.data?.database === "connected"}
                okText="Connected"
                failText={health.isError ? "Unknown" : "Disconnected"}
              />
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <span className="eyebrow">Jobs</span>
              <CardTitle>Totals</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
                {tiles.map((t) => (
                  <StatTile
                    key={t.label}
                    label={t.label}
                    value={t.value}
                    dot={t.dot}
                    loading={stats.isLoading}
                    error={stats.isError}
                  />
                ))}
              </div>
            </CardContent>
          </Card>
        </div>

        <div className="mt-6">
          <Card>
            <CardHeader>
              <span className="eyebrow">Recent</span>
              <CardTitle>Latest jobs</CardTitle>
            </CardHeader>
            <CardContent>
              {recent.isLoading ? (
                <div className="space-y-2">
                  {[0, 1, 2].map((i) => (
                    <Skeleton key={i} className="h-10 w-full" />
                  ))}
                </div>
              ) : recent.isError ? (
                <p className="text-sm text-ink-muted">
                  Recent jobs are unavailable while the API is unreachable.
                </p>
              ) : recent.data && recent.data.items.length > 0 ? (
                <ul className="divide-y divide-hairline">
                  {recent.data.items.map((job) => (
                    <li
                      key={job.id}
                      className="flex items-center justify-between gap-4 py-2.5"
                    >
                      <div className="min-w-0">
                        <div className="truncate text-sm font-medium text-ink">
                          {job.job_type}
                        </div>
                        <div className="text-xs text-ink-faint">
                          {formatDateTime(job.created_at)}
                        </div>
                      </div>
                      <StatusBadge status={job.status} />
                    </li>
                  ))}
                </ul>
              ) : (
                <EmptyState message="No jobs yet." />
              )}
            </CardContent>
          </Card>
        </div>
      </div>
    </PageContainer>
  );
}

function StatusLine({
  label,
  loading,
  ok,
  okText,
  failText,
}: {
  label: string;
  loading: boolean;
  ok: boolean;
  okText: string;
  failText: string;
}) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-sm text-ink-secondary">{label}</span>
      {loading ? (
        <Skeleton className="h-4 w-20" />
      ) : (
        <span className="inline-flex items-center gap-1.5 text-sm font-medium">
          <span
            className={cn(
              "h-1.5 w-1.5 rounded-full",
              ok ? "bg-status-success" : "bg-status-failed",
            )}
          />
          <span className={ok ? "text-status-success" : "text-status-failed"}>
            {ok ? okText : failText}
          </span>
        </span>
      )}
    </div>
  );
}

function StatTile({
  label,
  value,
  dot,
  loading,
  error,
}: {
  label: string;
  value: number | undefined;
  dot: string | null;
  loading: boolean;
  error: boolean;
}) {
  return (
    <div className="rounded-md border border-hairline bg-canvas px-3 py-3">
      <div className="flex items-center gap-1.5">
        {dot && <span className={cn("h-1.5 w-1.5 rounded-full", dot)} />}
        <span className="eyebrow">{label}</span>
      </div>
      {loading ? (
        <Skeleton className="mt-2 h-7 w-10" />
      ) : (
        <div className="mt-1.5 text-2xl font-semibold tabular-nums tracking-tight text-ink">
          {error ? "—" : (value ?? 0)}
        </div>
      )}
    </div>
  );
}
