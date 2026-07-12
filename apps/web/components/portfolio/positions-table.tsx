"use client";

import type { ReactNode } from "react";
import { useState } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import type { PortfolioAccount, Position, SyncStatus } from "@/lib/api";
import { getPositions } from "@/lib/api";
import { cn } from "@/lib/utils";
import {
  formatKrw,
  formatMoney,
  formatPercent,
  formatQuantity,
  shortId,
} from "@/lib/format";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeaderCell,
  TableRow,
} from "@/components/ui/table";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/states";

const COUNTRY_SEGMENTS: { label: string; value: string | undefined }[] = [
  { label: "전체", value: undefined },
  { label: "국내", value: "KR" },
  { label: "미국", value: "US" },
];

const CURRENCY_OPTIONS: { label: string; value: string | undefined }[] = [
  { label: "전체 통화", value: undefined },
  { label: "KRW", value: "KRW" },
  { label: "USD", value: "USD" },
];

function countryLabel(country: string | null): string {
  if (country === "KR") return "국내";
  if (country === "US") return "미국";
  return country ?? "—";
}

// 수익률은 통화·환율에 의존하지 않도록 현지 통화 손익/매입금액으로 도출한다.
function positionReturnPct(p: Position): number | null {
  if (p.purchase_amount_local == null || p.purchase_amount_local === 0) {
    return null;
  }
  if (p.unrealized_pnl_local == null) return null;
  return (p.unrealized_pnl_local / p.purchase_amount_local) * 100;
}

function pnlToneClass(value: number | null): string {
  if (value == null || value === 0) return "text-ink-secondary";
  return value > 0 ? "text-status-success" : "text-status-failed";
}

export function PositionsTable({
  accounts,
  syncStatus,
}: {
  accounts: PortfolioAccount[];
  syncStatus: SyncStatus;
}) {
  const [country, setCountry] = useState<string | undefined>(undefined);
  const [accountId, setAccountId] = useState<string | undefined>(undefined);
  const [currency, setCurrency] = useState<string | undefined>(undefined);

  const filters = { account_id: accountId, country, currency };
  const positions = useQuery({
    queryKey: ["portfolio", "positions", filters],
    queryFn: () => getPositions(filters),
    placeholderData: keepPreviousData,
  });

  const items = positions.data?.items ?? [];
  // Server sorts market_value_krw DESC NULLS LAST; re-sort client-side as a guard.
  const rows = [...items].sort((a, b) => {
    const av = a.market_value_krw;
    const bv = b.market_value_krw;
    if (av == null && bv == null) return 0;
    if (av == null) return 1;
    if (bv == null) return -1;
    return bv - av;
  });
  const totalKrw = rows.reduce((sum, p) => sum + (p.market_value_krw ?? 0), 0);

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-col gap-1">
            <span className="eyebrow">보유 종목</span>
            <CardTitle>총 {positions.data?.total ?? 0}개 종목</CardTitle>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <div className="inline-flex rounded-md border border-hairline p-0.5">
              {COUNTRY_SEGMENTS.map((s) => (
                <button
                  key={s.label}
                  type="button"
                  onClick={() => setCountry(s.value)}
                  className={cn(
                    "rounded px-3 py-1 text-xs font-medium transition-colors",
                    country === s.value
                      ? "bg-canvas-soft text-ink"
                      : "text-ink-muted hover:text-ink",
                  )}
                >
                  {s.label}
                </button>
              ))}
            </div>
            <FilterSelect
              value={accountId ?? ""}
              onChange={(v) => setAccountId(v || undefined)}
            >
              <option value="">전체 계좌</option>
              {accounts.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.account_name ?? a.account_number_masked ?? shortId(a.id)}
                </option>
              ))}
            </FilterSelect>
            <FilterSelect
              value={currency ?? ""}
              onChange={(v) => setCurrency(v || undefined)}
            >
              {CURRENCY_OPTIONS.map((o) => (
                <option key={o.label} value={o.value ?? ""}>
                  {o.label}
                </option>
              ))}
            </FilterSelect>
          </div>
        </div>
      </CardHeader>
      <CardContent>
        {positions.isLoading ? (
          <div className="space-y-2">
            {[0, 1, 2, 3].map((i) => (
              <Skeleton key={i} className="h-9 w-full" />
            ))}
          </div>
        ) : positions.isError ? (
          <p className="text-sm text-ink-muted">
            보유 종목을 불러오지 못했습니다. API 연결을 확인하세요.
          </p>
        ) : rows.length === 0 ? (
          <EmptyState
            message={
              syncStatus === "NEVER_SYNCED"
                ? "아직 동기화된 보유 종목이 없습니다. 상단에서 계좌를 동기화하세요."
                : "표시할 보유 종목이 없습니다."
            }
          />
        ) : (
          <Table>
            <TableHead>
              <TableRow>
                <TableHeaderCell>국가</TableHeaderCell>
                <TableHeaderCell>시장</TableHeaderCell>
                <TableHeaderCell>종목명</TableHeaderCell>
                <TableHeaderCell>티커</TableHeaderCell>
                <TableHeaderCell>통화</TableHeaderCell>
                <TableHeaderCell className="text-right">보유수량</TableHeaderCell>
                <TableHeaderCell className="text-right">평균매입가</TableHeaderCell>
                <TableHeaderCell className="text-right">현재가</TableHeaderCell>
                <TableHeaderCell className="text-right">매입금액</TableHeaderCell>
                <TableHeaderCell className="text-right">평가금액</TableHeaderCell>
                <TableHeaderCell className="text-right">
                  원화환산 평가금액
                </TableHeaderCell>
                <TableHeaderCell className="text-right">평가손익</TableHeaderCell>
                <TableHeaderCell className="text-right">수익률</TableHeaderCell>
                <TableHeaderCell className="text-right">비중</TableHeaderCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {rows.map((p) => {
                const ret = positionReturnPct(p);
                const weight =
                  totalKrw > 0 && p.market_value_krw != null
                    ? (p.market_value_krw / totalKrw) * 100
                    : null;
                return (
                  <TableRow key={`${p.account_id}-${p.asset_id}`}>
                    <TableCell className="whitespace-nowrap">
                      {countryLabel(p.country)}
                    </TableCell>
                    <TableCell className="whitespace-nowrap">
                      {p.market ?? "—"}
                    </TableCell>
                    <TableCell className="whitespace-nowrap font-medium text-ink">
                      {p.asset_name ?? "—"}
                    </TableCell>
                    <TableCell className="whitespace-nowrap tabular-nums">
                      {p.ticker ?? "—"}
                    </TableCell>
                    <TableCell className="whitespace-nowrap">
                      {p.currency ?? "—"}
                    </TableCell>
                    <TableCell className="whitespace-nowrap text-right tabular-nums">
                      {formatQuantity(p.quantity)}
                    </TableCell>
                    <TableCell className="whitespace-nowrap text-right tabular-nums">
                      {formatMoney(p.average_purchase_price, p.currency)}
                    </TableCell>
                    <TableCell className="whitespace-nowrap text-right tabular-nums">
                      {formatMoney(p.current_price, p.currency)}
                    </TableCell>
                    <TableCell className="whitespace-nowrap text-right tabular-nums">
                      {formatMoney(p.purchase_amount_local, p.currency)}
                    </TableCell>
                    <TableCell className="whitespace-nowrap text-right tabular-nums">
                      {formatMoney(p.market_value_local, p.currency)}
                    </TableCell>
                    <TableCell className="whitespace-nowrap text-right tabular-nums text-ink">
                      {formatKrw(p.market_value_krw)}
                    </TableCell>
                    <TableCell
                      className={cn(
                        "whitespace-nowrap text-right tabular-nums",
                        pnlToneClass(p.unrealized_pnl_krw),
                      )}
                    >
                      {formatKrw(p.unrealized_pnl_krw)}
                    </TableCell>
                    <TableCell
                      className={cn(
                        "whitespace-nowrap text-right tabular-nums",
                        pnlToneClass(ret),
                      )}
                    >
                      {formatPercent(ret)}
                    </TableCell>
                    <TableCell className="whitespace-nowrap text-right tabular-nums">
                      {weight == null ? "—" : `${weight.toFixed(1)}%`}
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}

function FilterSelect({
  value,
  onChange,
  children,
}: {
  value: string;
  onChange: (value: string) => void;
  children: ReactNode;
}) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="h-8 rounded-sm border border-hairline bg-canvas px-2 text-xs text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/30"
    >
      {children}
    </select>
  );
}
