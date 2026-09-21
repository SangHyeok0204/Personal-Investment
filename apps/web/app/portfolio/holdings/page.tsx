"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { PageContainer } from "@/components/layout/page-header";
import { Topbar } from "@/components/layout/topbar";
import { useAccount } from "@/components/layout/account-context";
import {
  Cell,
  DataTable,
  NotConnectedBanner,
  StatRow,
  StatTile,
  StubCard,
  toneOf,
} from "@/components/stub";
import { getPortfolioHoldings, getPortfolioSummary } from "@/lib/api";
import {
  formatKrwSigned,
  formatKrwString,
  formatPercentString,
  formatPriceString,
  formatQuantityString,
} from "@/lib/format";
import { cn } from "@/lib/utils";

// 보유 종목 전체 — /portfolio 의 요약 표보다 컬럼이 많다(시장·통화·환율·매입금액).
// 정렬은 클라이언트에서 한다: 행이 수십~수백 개 수준이라 서버 왕복을 늘릴 이유가 없다.

type SortKey =
  | "market_value_krw"
  | "unrealized_pnl_krw"
  | "unrealized_return"
  | "ticker";

const MARKET_FILTERS = [
  { id: "all", label: "전체" },
  { id: "KR", label: "국내" },
  { id: "US", label: "해외" },
] as const;

export default function HoldingsPage() {
  const { accountId, connected, isError } = useAccount();
  const [sortKey, setSortKey] = useState<SortKey>("market_value_krw");
  const [country, setCountry] = useState<string>("all");

  const summary = useQuery({
    queryKey: ["portfolioSummary", accountId],
    queryFn: () => getPortfolioSummary(accountId),
    staleTime: 30_000,
  });
  const holdings = useQuery({
    queryKey: ["portfolioHoldings", accountId],
    queryFn: () => getPortfolioHoldings(accountId),
    staleTime: 30_000,
  });

  const rows = useMemo(() => {
    const items = (holdings.data?.items ?? []).filter((h) =>
      country === "all"
        ? true
        : country === "KR"
          ? h.country === "KR"
          : h.country !== "KR",
    );
    const num = (v: string | null) => (v == null ? Number.NEGATIVE_INFINITY : Number(v));
    return [...items].sort((a, b) => {
      if (sortKey === "ticker") return a.ticker.localeCompare(b.ticker);
      return num(b[sortKey]) - num(a[sortKey]);
    });
  }, [holdings.data, sortKey, country]);

  const s = summary.data;

  return (
    <>
      <Topbar title="보유 종목" subtitle="종목별 수량 · 평단 · 손익" />
      <PageContainer wide>
        {!connected && (
          <NotConnectedBanner
            what="키움 잔고 조회"
            message={
              isError
                ? "API 서버에 연결하지 못했습니다 — 백엔드(uvicorn)가 떠 있는지 확인하세요."
                : undefined
            }
          />
        )}

        <StatRow>
          <StatTile
            label="보유 종목 수"
            value={s?.position_count ? `${s.position_count}` : undefined}
            loading={summary.isLoading}
          />
          <StatTile
            label="총 매입금액"
            value={formatKrwString(s?.purchase_amount_krw)}
            loading={summary.isLoading}
          />
          <StatTile
            label="총 평가금액"
            value={formatKrwString(s?.securities_value_krw)}
            loading={summary.isLoading}
          />
          <StatTile
            label="평가손익"
            value={formatKrwSigned(s?.unrealized_pnl_krw)}
            hint={
              s?.unrealized_return != null
                ? formatPercentString(s.unrealized_return)
                : undefined
            }
            accent="auto"
            loading={summary.isLoading}
          />
        </StatRow>

        <StubCard
          title="보유 종목 전체"
          subtitle="국내 · 해외 통합 (평가금액은 KRW 환산 기준)"
        >
          <div className="mb-3 flex flex-wrap items-center gap-2">
            {MARKET_FILTERS.map((f) => (
              <Chip
                key={f.id}
                active={country === f.id}
                onClick={() => setCountry(f.id)}
              >
                {f.label}
              </Chip>
            ))}
            <span className="mx-1 h-4 w-px bg-hairline" />
            <Chip
              active={sortKey === "market_value_krw"}
              onClick={() => setSortKey("market_value_krw")}
            >
              평가금액순
            </Chip>
            <Chip
              active={sortKey === "unrealized_pnl_krw"}
              onClick={() => setSortKey("unrealized_pnl_krw")}
            >
              손익순
            </Chip>
            <Chip
              active={sortKey === "unrealized_return"}
              onClick={() => setSortKey("unrealized_return")}
            >
              수익률순
            </Chip>
            <Chip active={sortKey === "ticker"} onClick={() => setSortKey("ticker")}>
              종목코드순
            </Chip>
            <span className="ml-auto text-[11px] font-semibold text-ink-faint">
              {rows.length}종목
            </span>
          </div>

          <DataTable
            columns={[
              "종목",
              "시장",
              "수량",
              "평단",
              "현재가",
              "매입금액",
              "평가금액",
              "평가손익",
              "수익률",
              "환율",
            ]}
            align={[
              "left", "left", "right", "right", "right",
              "right", "right", "right", "right", "right",
            ]}
            empty={
              holdings.isLoading
                ? "불러오는 중…"
                : connected
                  ? "보유 종목이 없습니다"
                  : "계좌를 연동하면 보유 종목이 표시됩니다"
            }
          >
            {rows.map((h) => (
              <tr
                key={`${h.account_id}-${h.asset_id}`}
                className="border-t border-hairline transition-colors hover:bg-canvas-soft/60"
              >
                <Cell left strong>
                  <span className="flex items-center gap-2">
                    {h.name ?? h.ticker}
                    <span className="text-[10px] font-semibold text-ink-faint">
                      {h.ticker}
                    </span>
                  </span>
                </Cell>
                <Cell left tone="muted">
                  {h.market}
                </Cell>
                <Cell>{formatQuantityString(h.quantity)}</Cell>
                <Cell>{formatPriceString(h.average_purchase_price, h.currency)}</Cell>
                <Cell>{formatPriceString(h.current_price, h.currency)}</Cell>
                <Cell tone="muted">
                  {formatPriceString(h.purchase_amount_local, h.currency)}
                </Cell>
                <Cell strong>{formatKrwString(h.market_value_krw)}</Cell>
                <Cell tone={toneOf(h.unrealized_pnl_krw)}>
                  {formatKrwSigned(h.unrealized_pnl_krw)}
                </Cell>
                <Cell tone={toneOf(h.unrealized_return)}>
                  {formatPercentString(h.unrealized_return)}
                </Cell>
                {/* 환율은 수집 시점 값 — 화면이 다시 계산하지 않는다. */}
                <Cell tone="muted">
                  {h.currency === "KRW"
                    ? "—"
                    : formatPriceString(h.exchange_rate, "USD")}
                </Cell>
              </tr>
            ))}
          </DataTable>
        </StubCard>
      </PageContainer>
    </>
  );
}

function Chip({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={cn(
        "rounded-lg border px-2.5 py-1 text-[11px] font-bold transition-colors",
        active
          ? "border-ge-point bg-ge-blue-bg text-ge-point"
          : "border-hairline bg-white text-ink-muted hover:bg-canvas-soft",
      )}
    >
      {children}
    </button>
  );
}
