"use client";

import { useState } from "react";
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
} from "@/components/stub";
import { getTrades, type TradeStats } from "@/lib/api";
import { formatPriceString, formatQuantityString } from "@/lib/format";
import { cn } from "@/lib/utils";

// 체결 내역.
//
// ★2026-09-21: 키움 ust21100(거래내역)을 붙였다. 이 화면이 마지막까지 골격만
//   남아 있던 자리다 — 0002 스키마에 거래 이력 테이블이 아예 없었다(alembic 0007).
//
// ⚠️합계를 **통화별로** 나눠 보여준다. USD 거래와 KRW 거래를 한 숫자로 더하면
//   의미 없는 값이 된다. 증권사가 해외 거래의 원화 금액을 0 으로 주기 때문에
//   환산에 쓸 거래 시점 환율이 없다 — 억지로 합치지 않는다.

const RANGES = [
  { id: 90, label: "3개월" },
  { id: 180, label: "6개월" },
  { id: 365, label: "1년" },
  { id: 730, label: "2년" },
];

/** 통화 기호. 모르는 통화는 코드를 그대로 쓴다. */
function money(value: string | null | undefined, currency: string): string {
  if (value == null || value === "") return "—";
  const digits = currency === "KRW" ? 0 : 2;
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  const body = n.toLocaleString("ko-KR", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
  return currency === "KRW" ? `₩${body}` : `$${body}`;
}

export default function ExecutionsPage() {
  const { accountId, connected } = useAccount();
  const [days, setDays] = useState(365);
  const [side, setSide] = useState<"BUY" | "SELL" | null>(null);

  const trades = useQuery({
    queryKey: ["trades", accountId, days, side],
    queryFn: () => getTrades({ accountId, days, side }),
    staleTime: 30_000,
  });

  const data = trades.data;
  const items = data?.items ?? [];
  // 통화가 하나면 상단 4칸에 그 통화 합계를 띄운다. 섞이면 아래 카드로 나눠 보여준다.
  const single: TradeStats | null =
    data?.stats.length === 1 ? data.stats[0] : null;

  return (
    <>
      <Topbar title="체결 내역" subtitle="일자별 매수 · 매도 체결" />
      <PageContainer wide>
        {!connected && <NotConnectedBanner what="키움 거래내역" />}

        <StatRow>
          <StatTile
            label="체결 건수"
            value={data ? `${data.total}` : undefined}
            hint={
              data?.first_trade_date
                ? `${data.first_trade_date} ~ ${data.last_trade_date}`
                : undefined
            }
            loading={trades.isLoading}
          />
          <StatTile
            label="매수 합계"
            value={single ? money(single.buy_amount, single.currency) : undefined}
            hint={single ? `${single.buy_count}건` : "통화별로 아래 참조"}
            loading={trades.isLoading}
          />
          <StatTile
            label="매도 합계"
            value={single ? money(single.sell_amount, single.currency) : undefined}
            hint={single ? `${single.sell_count}건` : "통화별로 아래 참조"}
            loading={trades.isLoading}
          />
          <StatTile
            label="거래비용"
            value={
              single
                ? money(
                    String(Number(single.commission) + Number(single.tax)),
                    single.currency,
                  )
                : undefined
            }
            hint={
              single
                ? `수수료 ${money(single.commission, single.currency)} · 세금 ${money(single.tax, single.currency)}`
                : "수수료 + 세금"
            }
            loading={trades.isLoading}
          />
        </StatRow>

        {/* 통화가 둘 이상이면 합치지 않고 나란히 보여준다. */}
        {data && data.stats.length > 1 && (
          <div className="mb-4 grid gap-3 sm:grid-cols-2">
            {data.stats.map((s) => (
              <div
                key={s.currency}
                className="rounded-2xl border border-hairline bg-canvas p-4 shadow-card"
              >
                <div className="mb-2 text-[12px] font-extrabold text-ge-navy">
                  {s.currency}
                </div>
                <dl className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-[12px]">
                  <dt className="text-ink-muted">매수 {s.buy_count}건</dt>
                  <dd className="text-right font-bold tabular-nums text-bid">
                    {money(s.buy_amount, s.currency)}
                  </dd>
                  <dt className="text-ink-muted">매도 {s.sell_count}건</dt>
                  <dd className="text-right font-bold tabular-nums text-ask">
                    {money(s.sell_amount, s.currency)}
                  </dd>
                  <dt className="text-ink-muted">거래비용</dt>
                  <dd className="text-right font-semibold tabular-nums text-ink-secondary">
                    {money(
                      String(Number(s.commission) + Number(s.tax)),
                      s.currency,
                    )}
                  </dd>
                </dl>
              </div>
            ))}
          </div>
        )}

        <StubCard title="체결 목록" subtitle="최근순">
          <div className="mb-3 flex flex-wrap items-center gap-2">
            {RANGES.map((r) => (
              <Chip key={r.id} active={days === r.id} onClick={() => setDays(r.id)}>
                {r.label}
              </Chip>
            ))}
            <span className="mx-1 h-4 w-px bg-hairline" />
            <Chip active={side === null} onClick={() => setSide(null)}>
              전체
            </Chip>
            <Chip active={side === "BUY"} onClick={() => setSide("BUY")}>
              매수
            </Chip>
            <Chip active={side === "SELL"} onClick={() => setSide("SELL")}>
              매도
            </Chip>
            <span className="ml-auto text-[11px] font-semibold text-ink-faint">
              {items.length}건 표시
              {data && data.total > items.length && ` / 전체 ${data.total}건`}
            </span>
          </div>

          <DataTable
            columns={[
              "체결일",
              "구분",
              "종목",
              "수량",
              "단가",
              "거래금액",
              "수수료",
              "세금",
              "정산금액",
            ]}
            align={[
              "left", "left", "left", "right", "right",
              "right", "right", "right", "right",
            ]}
            empty={
              trades.isLoading
                ? "불러오는 중…"
                : connected
                  ? "해당 기간에 체결이 없습니다"
                  : "계좌를 연동하면 체결 내역이 표시됩니다"
            }
          >
            {items.map((t) => (
              <tr
                key={t.id}
                className="border-t border-hairline transition-colors hover:bg-canvas-soft/60"
              >
                <Cell left tone="muted">
                  {t.trade_date}
                </Cell>
                <Cell left>
                  <span
                    className={cn(
                      "rounded px-1.5 py-0.5 text-[10px] font-extrabold",
                      t.side === "BUY"
                        ? "bg-bid-soft text-bid"
                        : "bg-ask-soft text-ask",
                    )}
                  >
                    {t.side === "BUY" ? "매수" : "매도"}
                  </span>
                </Cell>
                <Cell left strong>
                  <span className="flex items-center gap-2">
                    {t.asset_name ?? t.ticker}
                    <span className="text-[10px] font-semibold text-ink-faint">
                      {t.ticker}
                    </span>
                  </span>
                </Cell>
                <Cell>{formatQuantityString(t.quantity)}</Cell>
                <Cell>{formatPriceString(t.price, t.currency)}</Cell>
                <Cell strong>{money(t.amount_local, t.currency)}</Cell>
                <Cell tone="muted">{money(t.commission_local, t.currency)}</Cell>
                <Cell tone="muted">{money(t.tax_local, t.currency)}</Cell>
                <Cell>{money(t.settlement_amount_local, t.currency)}</Cell>
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
