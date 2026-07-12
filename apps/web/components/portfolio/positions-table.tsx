"use client";

import type { ReactNode } from "react";
import { useState } from "react";
import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { ArrowDown, ArrowUp, ArrowUpDown } from "lucide-react";
import type {
  AssetType,
  PortfolioAccount,
  Position,
  SyncStatus,
} from "@/lib/api";
import { ApiError, getPositions, updateAssetType } from "@/lib/api";
import { cn } from "@/lib/utils";
import {
  formatKrw,
  formatMoney,
  formatPercent,
  formatQuantity,
  formatRate,
  shortId,
} from "@/lib/format";
import { Card } from "@/components/ui/card";
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

const ASSET_TYPE_OPTIONS: { value: AssetType; label: string }[] = [
  { value: "STOCK", label: "주식" },
  { value: "BOND", label: "채권" },
  { value: "DERIVATIVE", label: "파생" },
  { value: "OTHER", label: "기타" },
];

// New assets default to STOCK in the DB (spec §4), so an unset value reads as 주식.
function normalizeAssetType(value: string | null): AssetType {
  return ASSET_TYPE_OPTIONS.some((option) => option.value === value)
    ? (value as AssetType)
    : "STOCK";
}

// 수익률 from local pnl / local purchase — independent of currency and FX.
function positionReturnPct(p: Position): number | null {
  if (p.purchase_amount_local == null || p.purchase_amount_local === 0) {
    return null;
  }
  if (p.unrealized_pnl_local == null) return null;
  return (p.unrealized_pnl_local / p.purchase_amount_local) * 100;
}

// Sorting a mixed KRW/USD column by its local value would put $7,028 below
// ₩84,900, so the money sorts always compare KRW-normalised amounts.
function purchaseKrw(p: Position): number | null {
  if (p.purchase_amount_local == null || p.exchange_rate == null) return null;
  return p.purchase_amount_local * p.exchange_rate;
}

type SortKey = "purchase" | "value" | "pnl" | "return";
type SortDir = "desc" | "asc";
type Sort = { key: SortKey; dir: SortDir };

const SORT_VALUE: Record<SortKey, (p: Position) => number | null> = {
  purchase: purchaseKrw,
  value: (p) => p.market_value_krw,
  pnl: (p) => p.unrealized_pnl_krw,
  return: positionReturnPct,
};

function pnlToneClass(value: number | null): string {
  if (value == null || value === 0) return "text-slate-600";
  return value > 0 ? "text-emerald-600" : "text-rose-500";
}

// Nulls sort last in both directions.
function compareNullable(
  a: number | null,
  b: number | null,
  dir: SortDir,
): number {
  if (a == null && b == null) return 0;
  if (a == null) return 1;
  if (b == null) return -1;
  return dir === "desc" ? b - a : a - b;
}

export function PositionsTable({
  accounts,
  syncStatus,
  totalAssetsKrw,
}: {
  accounts: PortfolioAccount[];
  syncStatus: SyncStatus;
  totalAssetsKrw: number | undefined;
}) {
  const queryClient = useQueryClient();
  const [country, setCountry] = useState<string | undefined>(undefined);
  const [accountId, setAccountId] = useState<string | undefined>(undefined);
  const [currency, setCurrency] = useState<string | undefined>(undefined);
  // Sort and filters are component state, so the 5s refetch never resets them.
  const [sort, setSort] = useState<Sort | null>(null);
  const [assetError, setAssetError] = useState<string | null>(null);
  const [pendingAssetId, setPendingAssetId] = useState<string | null>(null);

  const filters = { account_id: accountId, country, currency };
  const positions = useQuery({
    queryKey: ["portfolio", "positions", filters],
    queryFn: () => getPositions(filters),
    placeholderData: keepPreviousData,
  });

  const assetType = useMutation({
    mutationFn: (vars: { assetId: string; assetType: AssetType }) =>
      updateAssetType(vars.assetId, vars.assetType),
    onMutate: (vars) => {
      setPendingAssetId(vars.assetId);
      setAssetError(null);
    },
    onSuccess: () => {
      // Refreshes the donut and the table together.
      queryClient.invalidateQueries({ queryKey: ["portfolio"] });
    },
    onError: (err) => {
      setAssetError(
        err instanceof ApiError ? err.message : "자산군 변경에 실패했습니다.",
      );
    },
    onSettled: () => setPendingAssetId(null),
  });

  const items = positions.data?.items ?? [];
  const rows = [...items].sort((a, b) => {
    if (sort) {
      const compared = compareNullable(
        SORT_VALUE[sort.key](a),
        SORT_VALUE[sort.key](b),
        sort.dir,
      );
      if (compared !== 0) return compared;
    }
    // Default order, and the tiebreak: 원화환산 평가금액 DESC, nulls last.
    return compareNullable(a.market_value_krw, b.market_value_krw, "desc");
  });

  // 비중 is measured against TOTAL assets (cash included), matching the donut.
  // Holdings therefore sum to (100 − 현금비중)%, and a row keeps its weight when
  // a filter narrows the table.
  const weightBase = totalAssetsKrw ?? 0;

  function toggleSort(key: SortKey) {
    setSort((prev) => {
      if (prev?.key !== key) return { key, dir: "desc" };
      if (prev.dir === "desc") return { key, dir: "asc" };
      return null;
    });
  }

  return (
    <Card className="overflow-hidden">
      <div className="flex flex-wrap items-center justify-between gap-3 px-5 pb-3 pt-4">
        <div>
          <h2 className="text-[15px] font-semibold tracking-tight text-slate-900">
            보유 종목
          </h2>
          <p className="mt-0.5 text-[11px] text-slate-400">
            총 {positions.data?.total ?? 0}개 종목 · 자산군을 바꾸면 도넛이 즉시
            갱신됩니다
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {assetError && (
            <span
              className="max-w-[220px] truncate text-[11px] text-rose-600"
              title={assetError}
            >
              {assetError}
            </span>
          )}
          <div className="inline-flex rounded-md border border-slate-200 p-0.5">
            {COUNTRY_SEGMENTS.map((segment) => (
              <button
                key={segment.label}
                type="button"
                onClick={() => setCountry(segment.value)}
                className={cn(
                  "rounded px-3 py-1 text-xs font-medium transition-colors",
                  country === segment.value
                    ? "bg-slate-100 text-slate-900"
                    : "text-slate-500 hover:text-slate-800",
                )}
              >
                {segment.label}
              </button>
            ))}
          </div>
          <FilterSelect
            value={accountId ?? ""}
            onChange={(value) => setAccountId(value || undefined)}
          >
            <option value="">전체 계좌</option>
            {accounts.map((account) => (
              <option key={account.id} value={account.id}>
                {account.account_name ??
                  account.account_number_masked ??
                  shortId(account.id)}
              </option>
            ))}
          </FilterSelect>
          <FilterSelect
            value={currency ?? ""}
            onChange={(value) => setCurrency(value || undefined)}
          >
            {CURRENCY_OPTIONS.map((option) => (
              <option key={option.label} value={option.value ?? ""}>
                {option.label}
              </option>
            ))}
          </FilterSelect>
        </div>
      </div>

      <div className="px-5 pb-5">
        {positions.isLoading ? (
          <div className="space-y-2">
            {[0, 1, 2, 3].map((i) => (
              <Skeleton key={i} className="h-9 w-full" />
            ))}
          </div>
        ) : positions.isError ? (
          <p className="text-sm text-slate-500">
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
          <Table className="text-xs">
            <TableHead>
              <TableRow>
                <TableHeaderCell className="px-2 py-2">시장</TableHeaderCell>
                <TableHeaderCell className="px-2 py-2">종목명</TableHeaderCell>
                <TableHeaderCell className="px-2 py-2">티커</TableHeaderCell>
                <TableHeaderCell className="px-2 py-2">자산군</TableHeaderCell>
                <TableHeaderCell className="px-2 py-2">통화</TableHeaderCell>
                <TableHeaderCell className="px-2 py-2 text-right">
                  보유수량
                </TableHeaderCell>
                <TableHeaderCell className="px-2 py-2 text-right">
                  평단가
                </TableHeaderCell>
                <TableHeaderCell className="px-2 py-2 text-right">
                  현재가
                </TableHeaderCell>
                <SortableHeader
                  label="매입금액"
                  sortKey="purchase"
                  sort={sort}
                  onToggle={toggleSort}
                />
                <SortableHeader
                  label="평가금액"
                  sortKey="value"
                  sort={sort}
                  onToggle={toggleSort}
                />
                <TableHeaderCell className="px-2 py-2 text-right">
                  원화환산 평가금액
                </TableHeaderCell>
                <SortableHeader
                  label="평가손익"
                  sortKey="pnl"
                  sort={sort}
                  onToggle={toggleSort}
                />
                <SortableHeader
                  label="수익률"
                  sortKey="return"
                  sort={sort}
                  onToggle={toggleSort}
                />
                <TableHeaderCell className="px-2 py-2 text-right">
                  비중
                </TableHeaderCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {rows.map((p) => {
                const returnPct = positionReturnPct(p);
                const weight =
                  weightBase > 0 && p.market_value_krw != null
                    ? (p.market_value_krw / weightBase) * 100
                    : null;
                return (
                  <TableRow key={`${p.account_id}-${p.asset_id}`}>
                    <TableCell className="whitespace-nowrap px-2 py-2.5">
                      {p.market ?? "—"}
                    </TableCell>
                    <TableCell className="px-2 py-2.5">
                      <div
                        className="max-w-[150px] truncate font-medium text-slate-800"
                        title={p.asset_name ?? undefined}
                      >
                        {p.asset_name ?? "—"}
                      </div>
                    </TableCell>
                    <TableCell className="whitespace-nowrap px-2 py-2.5 tabular-nums">
                      {p.ticker ?? "—"}
                    </TableCell>
                    <TableCell className="px-2 py-2.5">
                      <select
                        value={normalizeAssetType(p.asset_type)}
                        onChange={(event) =>
                          assetType.mutate({
                            assetId: p.asset_id,
                            assetType: event.target.value as AssetType,
                          })
                        }
                        disabled={pendingAssetId === p.asset_id}
                        className="h-7 rounded border border-slate-200 bg-white px-1.5 text-xs text-slate-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/30 disabled:opacity-50"
                      >
                        {ASSET_TYPE_OPTIONS.map((option) => (
                          <option key={option.value} value={option.value}>
                            {option.label}
                          </option>
                        ))}
                      </select>
                    </TableCell>
                    <TableCell className="whitespace-nowrap px-2 py-2.5">
                      {p.currency ?? "—"}
                    </TableCell>
                    <TableCell className="whitespace-nowrap px-2 py-2.5 text-right tabular-nums">
                      {formatQuantity(p.quantity)}
                    </TableCell>
                    <TableCell className="whitespace-nowrap px-2 py-2.5 text-right tabular-nums">
                      {formatMoney(p.average_purchase_price, p.currency)}
                    </TableCell>
                    <TableCell className="whitespace-nowrap px-2 py-2.5 text-right tabular-nums">
                      {formatMoney(p.current_price, p.currency)}
                    </TableCell>
                    <TableCell className="whitespace-nowrap px-2 py-2.5 text-right tabular-nums">
                      {formatMoney(p.purchase_amount_local, p.currency)}
                    </TableCell>
                    <TableCell className="whitespace-nowrap px-2 py-2.5 text-right tabular-nums">
                      {formatMoney(p.market_value_local, p.currency)}
                    </TableCell>
                    <TableCell
                      className="whitespace-nowrap px-2 py-2.5 text-right tabular-nums text-slate-800"
                      title={
                        p.exchange_rate != null
                          ? `적용 환율 ${formatRate(p.exchange_rate)}`
                          : undefined
                      }
                    >
                      {formatKrw(p.market_value_krw)}
                    </TableCell>
                    <TableCell
                      className={cn(
                        "whitespace-nowrap px-2 py-2.5 text-right tabular-nums",
                        pnlToneClass(p.unrealized_pnl_krw),
                      )}
                    >
                      {formatKrw(p.unrealized_pnl_krw)}
                    </TableCell>
                    <TableCell
                      className={cn(
                        "whitespace-nowrap px-2 py-2.5 text-right tabular-nums",
                        pnlToneClass(returnPct),
                      )}
                    >
                      {formatPercent(returnPct)}
                    </TableCell>
                    <TableCell className="whitespace-nowrap px-2 py-2.5 text-right tabular-nums">
                      {weight == null ? "—" : `${weight.toFixed(1)}%`}
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        )}
      </div>
    </Card>
  );
}

function SortableHeader({
  label,
  sortKey,
  sort,
  onToggle,
}: {
  label: string;
  sortKey: SortKey;
  sort: Sort | null;
  onToggle: (key: SortKey) => void;
}) {
  const active = sort?.key === sortKey;
  return (
    <TableHeaderCell className="px-2 py-2 text-right">
      <button
        type="button"
        onClick={() => onToggle(sortKey)}
        className={cn(
          "inline-flex items-center gap-1 transition-colors hover:text-slate-800",
          active && "text-slate-800",
        )}
      >
        {label}
        {active ? (
          sort.dir === "desc" ? (
            <ArrowDown className="h-3 w-3" />
          ) : (
            <ArrowUp className="h-3 w-3" />
          )
        ) : (
          <ArrowUpDown className="h-3 w-3 opacity-30" />
        )}
      </button>
    </TableHeaderCell>
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
      onChange={(event) => onChange(event.target.value)}
      className="h-8 rounded-md border border-slate-200 bg-white px-2 text-xs text-slate-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/30"
    >
      {children}
    </select>
  );
}
