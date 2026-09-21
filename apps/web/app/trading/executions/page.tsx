"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { PageContainer } from "@/components/layout/page-header";
import { Topbar } from "@/components/layout/topbar";
import { useAccount } from "@/components/layout/account-context";
import { Modal } from "@/components/ui/modal";
import {
  Cell,
  DataTable,
  NotConnectedBanner,
  StatTile,
  StubCard,
} from "@/components/stub";
import { getTrades, type Trade, type TradeStats } from "@/lib/api";
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
//
// ★2026-09-22: 1페이지 압축. 체결 목록이 9열이라 좁은 칸에서 잘렸다 —
//   목록에는 핵심 5열만 두고 단가·수수료·세금·정산금액은 행을 눌러 보는
//   팝업으로 옮겼다. 왼쪽에는 종목별 집계를 세워 "무엇을 얼마나 사고팔았나"가
//   스크롤 없이 한눈에 들어오게 했다.

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
  const [picked, setPicked] = useState<Trade | null>(null);

  const trades = useQuery({
    queryKey: ["trades", accountId, days, side],
    queryFn: () => getTrades({ accountId, days, side }),
    staleTime: 30_000,
  });

  const data = trades.data;
  const items = data?.items ?? [];
  // 통화가 하나면 상단 4칸에 그 통화 합계를 띄운다. 섞이면 "통화별" 로 표시한다.
  const single: TradeStats | null =
    data?.stats.length === 1 ? data.stats[0] : null;

  // 종목별 집계 — 서버에 없는 축이라 여기서 만든다(목록과 같은 데이터라 어긋나지 않는다).
  const byTicker = useMemo(() => {
    const map = new Map<
      string,
      {
        ticker: string;
        name: string | null;
        currency: string;
        buy: number;
        sell: number;
        buyCount: number;
        sellCount: number;
      }
    >();
    for (const t of items) {
      const row = map.get(t.ticker) ?? {
        ticker: t.ticker,
        name: t.asset_name,
        currency: t.currency,
        buy: 0,
        sell: 0,
        buyCount: 0,
        sellCount: 0,
      };
      const amount = Number(t.amount_local ?? 0);
      if (t.side === "BUY") {
        row.buy += amount;
        row.buyCount += 1;
      } else {
        row.sell += amount;
        row.sellCount += 1;
      }
      row.name = row.name ?? t.asset_name;
      map.set(t.ticker, row);
    }
    // 순매수(매수-매도)가 큰 순. 많이 담은 종목이 위로 온다.
    return [...map.values()].sort((a, b) => b.buy - b.sell - (a.buy - a.sell));
  }, [items]);

  const filters = (
    <div className="flex flex-wrap items-center gap-1.5">
      {RANGES.map((r) => (
        <Chip key={r.id} active={days === r.id} onClick={() => setDays(r.id)}>
          {r.label}
        </Chip>
      ))}
      <span className="mx-0.5 h-3.5 w-px bg-white/25" />
      <Chip active={side === null} onClick={() => setSide(null)}>
        전체
      </Chip>
      <Chip active={side === "BUY"} onClick={() => setSide("BUY")}>
        매수
      </Chip>
      <Chip active={side === "SELL"} onClick={() => setSide("SELL")}>
        매도
      </Chip>
    </div>
  );

  return (
    <>
      <Topbar title="체결 내역" subtitle="일자별 매수 · 매도 체결" />
      <PageContainer fit>
        {!connected && <NotConnectedBanner what="키움 거래내역" />}

        <div className="grid shrink-0 grid-cols-2 gap-2.5 lg:grid-cols-4">
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
            hint={single ? `${single.buy_count}건` : "통화가 섞여 합치지 않음"}
            loading={trades.isLoading}
          />
          <StatTile
            label="매도 합계"
            value={single ? money(single.sell_amount, single.currency) : undefined}
            hint={single ? `${single.sell_count}건` : "통화가 섞여 합치지 않음"}
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
        </div>

        <div
          className={cn(
            "grid min-h-0 flex-1 gap-3",
            "grid-cols-1 auto-rows-[minmax(0,1fr)]",
            "md:grid-cols-2 lg:auto-rows-auto",
            "lg:grid-cols-[minmax(0,1fr)_minmax(0,1.5fr)]",
          )}
        >
          <StubCard
            title="종목별 매매"
            subtitle={`${byTicker.length}종목 · 순매수 순`}
            scrollBody
          >
            {trades.isLoading ? (
              <Empty text="불러오는 중…" />
            ) : (
              <DataTable
                columns={["종목", "매수", "매도", "순매수"]}
                empty="해당 기간에 체결이 없습니다"
              >
                {byTicker.map((r) => {
                  const net = r.buy - r.sell;
                  return (
                    <tr key={r.ticker} className="border-b border-hairline">
                      <Cell left strong>
                        <span className="flex items-center gap-1.5">
                          <span className="max-w-[130px] truncate">
                            {r.name ?? r.ticker}
                          </span>
                          <span className="shrink-0 text-[10px] font-bold text-ink-faint">
                            {r.ticker}
                          </span>
                        </span>
                      </Cell>
                      <Cell tone={r.buyCount ? "up" : "muted"}>
                        {r.buyCount ? money(String(r.buy), r.currency) : "—"}
                      </Cell>
                      <Cell tone={r.sellCount ? "down" : "muted"}>
                        {r.sellCount ? money(String(r.sell), r.currency) : "—"}
                      </Cell>
                      <Cell strong tone={net >= 0 ? "up" : "down"}>
                        {money(String(net), r.currency)}
                      </Cell>
                    </tr>
                  );
                })}
              </DataTable>
            )}
          </StubCard>

          <StubCard
            title="체결 목록"
            subtitle={
              data
                ? `${items.length}건 표시${data.total > items.length ? ` / 전체 ${data.total}건` : ""}`
                : "최근순"
            }
            action={filters}
            scrollBody
          >
            <DataTable
              columns={["체결일", "구분", "종목", "수량", "거래금액"]}
              align={["left", "left", "left", "right", "right"]}
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
                  onClick={() => setPicked(t)}
                  className="cursor-pointer border-b border-hairline transition-colors hover:bg-canvas-soft"
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
                    <span className="flex items-center gap-1.5">
                      <span className="max-w-[140px] truncate">
                        {t.asset_name ?? t.ticker}
                      </span>
                      <span className="shrink-0 text-[10px] font-bold text-ink-faint">
                        {t.ticker}
                      </span>
                    </span>
                  </Cell>
                  <Cell>{formatQuantityString(t.quantity)}</Cell>
                  <Cell strong>{money(t.amount_local, t.currency)}</Cell>
                </tr>
              ))}
            </DataTable>
          </StubCard>
        </div>
      </PageContainer>

      <Modal
        open={picked != null}
        onClose={() => setPicked(null)}
        title={picked?.asset_name ?? picked?.ticker ?? ""}
        subtitle={
          picked ? `${picked.trade_date} · ${picked.side === "BUY" ? "매수" : "매도"}` : undefined
        }
      >
        {picked && <TradeDetail trade={picked} />}
      </Modal>
    </>
  );
}

/** 목록에서 뺀 열들을 여기서 보여준다 — 자주 보는 값이 아니라 팝업이 맞다. */
function TradeDetail({ trade: t }: { trade: Trade }) {
  const rows: [string, string][] = [
    ["종목코드", t.ticker],
    ["체결일", t.trade_date],
    ["구분", t.side === "BUY" ? "매수" : "매도"],
    ["수량", formatQuantityString(t.quantity)],
    ["단가", formatPriceString(t.price, t.currency)],
    ["거래금액", money(t.amount_local, t.currency)],
    ["수수료", money(t.commission_local, t.currency)],
    ["세금", money(t.tax_local, t.currency)],
    ["정산금액", money(t.settlement_amount_local, t.currency)],
  ];
  return (
    <dl className="grid grid-cols-2 gap-x-5 gap-y-0">
      {rows.map(([label, value]) => (
        <div
          key={label}
          className="flex items-baseline justify-between border-b border-hairline py-2"
        >
          <dt className="text-[12px] text-ink-secondary">{label}</dt>
          <dd className="text-[13px] font-bold tabular-nums text-ink">{value}</dd>
        </div>
      ))}
    </dl>
  );
}

function Empty({ text }: { text: string }) {
  return (
    <div className="flex h-full items-center justify-center">
      <span className="text-[12px] font-semibold text-ink-faint">{text}</span>
    </div>
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
      // 카드 헤더(ge-header, 짙은 갈색) 위에 올라가므로 흰 계열로 맞춘다.
      className={cn(
        "rounded px-1.5 py-0.5 text-[10px] font-bold transition-colors",
        active
          ? "bg-white/90 text-ge-header"
          : "text-white/60 hover:bg-white/15 hover:text-white",
      )}
    >
      {children}
    </button>
  );
}
