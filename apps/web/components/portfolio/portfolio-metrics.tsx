import type { PortfolioSummary } from "@/lib/api";
import { formatKrw, formatKrwCompact, formatPercent } from "@/lib/format";
import { cn } from "@/lib/utils";
import { Skeleton } from "@/components/ui/skeleton";

// 총매입금액 is not part of the donut: it is not a slice of total assets
// (portfolio-detail-spec §0). It sits here next to 평가손익 instead.
export function PortfolioMetrics({
  summary,
  loading,
}: {
  summary: PortfolioSummary | undefined;
  loading: boolean;
}) {
  const pnl = summary?.total_unrealized_pnl_krw ?? null;
  const returnPct = summary?.unrealized_return_pct ?? null;

  return (
    <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
      <Metric
        label="총자산"
        value={formatKrwCompact(summary?.total_assets_krw)}
        detail={formatKrw(summary?.total_assets_krw)}
        loading={loading}
      />
      <Metric
        label="보유 종목 수"
        value={summary != null ? `${summary.position_count}개` : "—"}
        detail={summary != null ? `${summary.account_count}개 계좌` : "—"}
        loading={loading}
      />
      <Metric
        label="평가손익"
        value={formatKrw(pnl)}
        detail={returnPct != null ? `수익률 ${formatPercent(returnPct)}` : "—"}
        tone={pnl == null || pnl === 0 ? "neutral" : pnl > 0 ? "up" : "down"}
        loading={loading}
      />
      <Metric
        label="총매입금액"
        value={formatKrwCompact(summary?.total_purchase_amount_krw)}
        detail={formatKrw(summary?.total_purchase_amount_krw)}
        loading={loading}
      />
    </div>
  );
}

function Metric({
  label,
  value,
  detail,
  tone = "neutral",
  loading,
}: {
  label: string;
  value: string;
  detail: string;
  tone?: "neutral" | "up" | "down";
  loading: boolean;
}) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white px-3.5 py-3.5 shadow-sm">
      <div className="text-[11px] font-medium text-slate-500">{label}</div>
      {loading ? (
        <Skeleton className="mt-2 h-6 w-24" />
      ) : (
        <div
          className={cn(
            "mt-2 text-lg font-semibold tracking-tight tabular-nums",
            tone === "up"
              ? "text-emerald-600"
              : tone === "down"
                ? "text-rose-500"
                : "text-slate-900",
          )}
        >
          {value}
        </div>
      )}
      <div
        className={cn(
          "mt-2 truncate text-[10px] tabular-nums",
          tone === "up"
            ? "text-emerald-600"
            : tone === "down"
              ? "text-rose-500"
              : "text-slate-400",
        )}
      >
        {loading ? "—" : detail}
      </div>
    </div>
  );
}
