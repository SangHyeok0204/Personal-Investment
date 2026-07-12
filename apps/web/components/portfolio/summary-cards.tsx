import type { PortfolioSummary } from "@/lib/api";
import { formatKrw, formatPercent } from "@/lib/format";
import { MetricCard } from "./metric-card";

export function SummaryCards({
  summary,
  loading,
}: {
  summary: PortfolioSummary | undefined;
  loading: boolean;
}) {
  const pnl = summary?.total_unrealized_pnl_krw ?? null;
  const tone =
    pnl == null || pnl === 0 ? "muted" : pnl > 0 ? "positive" : "negative";
  const returnPct = summary?.unrealized_return_pct ?? null;

  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
      <MetricCard
        label="총자산"
        value={formatKrw(summary?.total_assets_krw)}
        loading={loading}
      />
      <MetricCard
        label="주식 평가금액"
        value={formatKrw(summary?.securities_value_krw)}
        loading={loading}
      />
      <MetricCard
        label="현금·예수금"
        value={formatKrw(summary?.cash_value_krw)}
        loading={loading}
      />
      <MetricCard
        label="총매입금액"
        value={formatKrw(summary?.total_purchase_amount_krw)}
        loading={loading}
      />
      <MetricCard
        label="평가손익"
        value={formatKrw(pnl)}
        sub={returnPct != null ? formatPercent(returnPct) : undefined}
        tone={tone}
        loading={loading}
      />
      <MetricCard
        label="보유종목 수"
        value={
          summary != null
            ? `${summary.position_count.toLocaleString("ko-KR")}개`
            : "—"
        }
        loading={loading}
      />
    </div>
  );
}
