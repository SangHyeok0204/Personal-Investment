import type { CashBalance, MarketBreakdown } from "@/lib/api";
import { formatKrw, formatUsd } from "@/lib/format";
import { MetricCard } from "./metric-card";

function sumCash(
  balances: CashBalance[] | undefined,
  currency: string,
): number | null {
  if (!balances) return null;
  const matches = balances.filter((b) => b.currency === currency);
  if (matches.length === 0) return null;
  return matches.reduce((total, b) => total + (b.cash_balance ?? 0), 0);
}

// KRW value of a foreign cash row, converted by Kiwoom's own rate (cash_krw).
// Null when the API has no KRW figure — we show nothing rather than converting
// with a guessed FX rate. Never estimated_total_assets_krw: that is the
// account's 추정예탁자산 (cash + securities), not this row's cash.
function sumCashKrw(
  balances: CashBalance[] | undefined,
  currency: string,
): number | null {
  if (!balances) return null;
  const converted = balances.filter(
    (b) => b.currency === currency && b.cash_krw != null,
  );
  if (converted.length === 0) return null;
  return converted.reduce((total, b) => total + (b.cash_krw ?? 0), 0);
}

export function MarketCards({
  marketBreakdown,
  cashBalances,
  loading,
}: {
  marketBreakdown: MarketBreakdown[] | undefined;
  cashBalances: CashBalance[] | undefined;
  loading: boolean;
}) {
  const domestic = marketBreakdown?.find((m) => m.country === "KR");
  const us = marketBreakdown?.find((m) => m.country === "US");
  const krwCash = sumCash(cashBalances, "KRW");
  const usdCash = sumCash(cashBalances, "USD");
  const usdCashKrw = sumCashKrw(cashBalances, "USD");

  return (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
      <MetricCard
        label="국내주식 평가금액"
        value={formatKrw(domestic?.securities_value_krw ?? null)}
        loading={loading}
      />
      <MetricCard
        label="미국주식 평가금액"
        value={formatKrw(us?.securities_value_krw ?? null)}
        loading={loading}
      />
      <MetricCard label="KRW 예수금" value={formatKrw(krwCash)} loading={loading} />
      <MetricCard
        label="USD 예수금"
        value={formatUsd(usdCash)}
        sub={usdCashKrw != null ? formatKrw(usdCashKrw) : undefined}
        loading={loading}
      />
    </div>
  );
}
