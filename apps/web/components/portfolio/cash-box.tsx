import type { CashBalance } from "@/lib/api";
import { formatKrw, formatMoney, formatRate } from "@/lib/format";
import { cn } from "@/lib/utils";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

type CashRow = {
  currency: string;
  cash: number;
  krw: number | null;
  rate: number | null;
};

function groupByCurrency(balances: CashBalance[]): CashRow[] {
  const rows = new Map<string, CashRow>();
  for (const balance of balances) {
    const row = rows.get(balance.currency) ?? {
      currency: balance.currency,
      cash: 0,
      krw: null,
      rate: null,
    };
    row.cash += balance.cash_balance ?? 0;
    // cash_krw is Kiwoom's own conversion. We never multiply an FX rate ourselves.
    if (balance.cash_krw != null) row.krw = (row.krw ?? 0) + balance.cash_krw;
    if (balance.exchange_rate != null) row.rate = balance.exchange_rate;
    rows.set(balance.currency, row);
  }
  return [...rows.values()].sort((a, b) => {
    if (a.currency === "KRW") return -1;
    if (b.currency === "KRW") return 1;
    return a.currency.localeCompare(b.currency);
  });
}

export function CashBox({
  cashBalances,
  cashValueKrw,
  loading,
}: {
  cashBalances: CashBalance[] | undefined;
  cashValueKrw: number | undefined;
  loading: boolean;
}) {
  const rows = groupByCurrency(cashBalances ?? []);

  return (
    <Card className="overflow-hidden">
      <div className="flex items-center justify-between gap-4 px-5 pb-3 pt-4">
        <h2 className="text-[15px] font-semibold tracking-tight text-slate-900">
          예수금
        </h2>
        <span className="text-xs tabular-nums text-slate-400">
          합계 {loading ? "—" : formatKrw(cashValueKrw)}
        </span>
      </div>

      <div className="grid gap-3 px-5 pb-5 sm:grid-cols-2">
        {loading ? (
          <>
            <Skeleton className="h-[86px] w-full rounded-lg" />
            <Skeleton className="h-[86px] w-full rounded-lg" />
          </>
        ) : rows.length === 0 ? (
          <div className="rounded-lg border border-dashed border-slate-200 px-4 py-6 text-center text-xs text-slate-400 sm:col-span-2">
            예수금 정보가 없습니다.
          </div>
        ) : (
          rows.map((row) => (
            <div
              key={row.currency}
              className="rounded-lg border border-slate-200 bg-slate-50/50 px-4 py-3"
            >
              <div className="flex items-center justify-between gap-2">
                <span className="text-[11px] font-semibold text-slate-500">
                  {row.currency}
                </span>
                {row.currency !== "KRW" && row.rate != null && (
                  <span className="text-[10px] tabular-nums text-slate-400">
                    환율 {formatRate(row.rate)}
                  </span>
                )}
              </div>
              <div
                className={cn(
                  "mt-1.5 text-lg font-semibold tabular-nums",
                  row.cash < 0 ? "text-rose-500" : "text-slate-900",
                )}
              >
                {formatMoney(row.cash, row.currency)}
              </div>
              {row.currency !== "KRW" && (
                <div className="mt-0.5 text-[11px] tabular-nums text-slate-400">
                  {formatKrw(row.krw)}
                </div>
              )}
            </div>
          ))
        )}
      </div>
    </Card>
  );
}
