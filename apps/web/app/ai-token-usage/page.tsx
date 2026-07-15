"use client";

import { useQuery } from "@tanstack/react-query";
import { AlertTriangle } from "lucide-react";
import {
  getAiTokenUsage,
  type AiUsageAccount,
  type AiUsageMeter,
} from "@/lib/api";
import { formatDateTime, formatRelativeTime } from "@/lib/format";
import { PageContainer } from "@/components/layout/page-header";
import { Topbar } from "@/components/layout/topbar";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiErrorBanner, EmptyState } from "@/components/states";
import { cn } from "@/lib/utils";

export default function AiTokenUsagePage() {
  const usage = useQuery({
    queryKey: ["aiTokenUsage"],
    queryFn: getAiTokenUsage,
    refetchInterval: 60000,
  });

  const data = usage.data;
  const staleCodexSince = (data?.codex ?? [])
    .filter((a) => a.stale && a.captured_at)
    .map((a) => a.captured_at as string)
    .sort()[0];

  return (
    <>
      <Topbar
        title="AI Token Usage"
        subtitle="기타 · Claude / Codex 사용량 한도 실시간 모니터링"
      />
      <PageContainer>
        {usage.isError && (
          <div className="mb-6">
            <ApiErrorBanner error={usage.error} />
          </div>
        )}

        {data && !data.reachable && (
          <WarningBanner>
            모니터에 연결할 수 없습니다 ({data.monitor_base_url})
            {data.error ? ` — ${data.error}` : ""}
          </WarningBanner>
        )}

        {staleCodexSince && (
          <WarningBanner>
            Codex 데이터가 {formatDateTime(staleCodexSince)}부터 갱신되지 않았습니다.
          </WarningBanner>
        )}

        {usage.isLoading ? (
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            {[0, 1, 2, 3].map((i) => (
              <Skeleton key={i} className="h-48 w-full" />
            ))}
          </div>
        ) : usage.isError ? (
          <p className="text-sm text-ink-muted">
            API가 응답하지 않아 사용량 데이터를 표시할 수 없습니다.
          </p>
        ) : (
          <>
            <AccountsSection label="Claude" accounts={data?.claude ?? []} />
            <AccountsSection
              label="Codex"
              accounts={data?.codex ?? []}
              className="mt-8"
            />
          </>
        )}
      </PageContainer>
    </>
  );
}

function WarningBanner({ children }: { children: React.ReactNode }) {
  return (
    <div className="mb-6 flex items-start gap-2.5 rounded-lg border border-amber-400/40 bg-amber-400/[0.08] px-4 py-3 text-sm text-amber-700">
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" strokeWidth={2} />
      <div>{children}</div>
    </div>
  );
}

function AccountsSection({
  label,
  accounts,
  className,
}: {
  label: string;
  accounts: AiUsageAccount[];
  className?: string;
}) {
  return (
    <div className={className}>
      <div className="eyebrow mb-3">{label}</div>
      {accounts.length > 0 ? (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          {accounts.map((account) => (
            <AccountCard key={account.account_num} account={account} />
          ))}
        </div>
      ) : (
        <EmptyState message="표시할 항목이 없습니다." />
      )}
    </div>
  );
}

function AccountCard({ account }: { account: AiUsageAccount }) {
  return (
    <Card>
      <CardHeader className="flex-row items-start justify-between gap-3 pb-2">
        <div className="min-w-0">
          <CardTitle className="truncate">
            {account.email ?? `계정 ${account.account_num}`}
          </CardTitle>
          {account.plan && (
            <div className="mt-0.5 text-xs text-ink-muted">{account.plan}</div>
          )}
        </div>
        <FreshnessBadge account={account} />
      </CardHeader>
      <CardContent className="pt-1">
        {account.items.length > 0 ? (
          <div className="divide-y divide-hairline">
            {account.items.map((item, i) => (
              <Meter key={`${item.label}-${i}`} item={item} />
            ))}
          </div>
        ) : (
          <EmptyState message="표시할 항목이 없습니다." />
        )}
      </CardContent>
    </Card>
  );
}

function FreshnessBadge({ account }: { account: AiUsageAccount }) {
  if (!account.captured_at) {
    return (
      <span className="inline-flex shrink-0 items-center rounded-full border border-hairline bg-canvas-soft px-2 py-0.5 text-xs font-medium text-ink-faint">
        데이터 없음
      </span>
    );
  }
  return (
    <span
      className={cn(
        "inline-flex shrink-0 items-center rounded-full border px-2 py-0.5 text-xs font-medium",
        account.stale
          ? "border-amber-400/40 bg-amber-400/[0.10] text-amber-700"
          : "border-status-success/30 bg-status-success/[0.08] text-status-success",
      )}
    >
      {formatRelativeTime(account.captured_at)}
      {account.stale && " · 오래됨"}
    </span>
  );
}

function meterFillClass(pct: number): string {
  if (pct >= 90) return "bg-status-failed";
  if (pct >= 70) return "bg-amber-400";
  return "bg-ge-point";
}

function Meter({ item }: { item: AiUsageMeter }) {
  const width = Math.min(100, Math.max(0, item.pct));
  const caption = [
    item.subtitle,
    item.remaining_pct != null ? `잔여 ${item.remaining_pct.toFixed(0)}%` : null,
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <div className="py-2.5 first:pt-0 last:pb-0">
      <div className="mb-1.5 flex items-baseline justify-between gap-2">
        <span className="text-sm font-medium text-ink-secondary">
          {item.label}
        </span>
        <span className="font-mono text-xs text-ink-muted">
          {item.pct.toFixed(0)}%
        </span>
      </div>
      <div className="h-2 w-full overflow-hidden rounded-full bg-canvas-soft">
        <div
          className={cn("h-full rounded-full transition-all", meterFillClass(width))}
          style={{ width: `${width}%` }}
        />
      </div>
      {caption && <div className="mt-1 text-xs text-ink-faint">{caption}</div>}
    </div>
  );
}
