"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { PageContainer } from "@/components/layout/page-header";
import { Topbar } from "@/components/layout/topbar";
import { useAccount } from "@/components/layout/account-context";
import { Modal } from "@/components/ui/modal";
import { SignedBarChart } from "@/components/charts/signed-bar-chart";
import { StackedBarChart, type StackColumn } from "@/components/charts/stacked-bar-chart";
import {
  CardEmpty,
  Cell,
  DataTable,
  HeaderChip,
  ListButton,
  NotConnectedBanner,
  StatTile,
  StubCard,
  toneOf,
} from "@/components/stub";
import { getRealizedPnl, type RealizedPnlItem } from "@/lib/api";
import {
  formatKrwSigned,
  formatKrwString,
  formatPercentString,
  formatPriceString,
  formatQuantityString,
} from "@/lib/format";
import { cn } from "@/lib/utils";

// 실현손익 — 키움 ust21530.
//
// ⚠️이 화면의 핵심은 **주가 손익과 환 손익을 분리해서 보여주는 것**이다.
//   해외 주식은 종목이 올라도 환율이 빠지면 원화로는 손해일 수 있다. 둘을 한
//   숫자로 합치면 "무엇으로 벌었는지"가 사라져서, 다음에 무엇을 고쳐야 할지 모른다.
//   실측 예: SGOV 는 외화 기준 -$7.58 손실인데 환차손익이 +₩195,692 였다.
//
// ★2026-09-22: 1페이지 압축. 청산 내역이 8열이라 좁은 칸에서 잘렸다 — 목록에는
//   매도일·종목·손익·수익률만 두고 매입평균·매도평균·환차손익은 행을 눌러 보는
//   팝업으로 옮겼다. 주가/환차 분리라는 이 화면의 요점은 상단 4칸과 팝업 양쪽에
//   그대로 남는다.

const RANGES = [
  { id: 90, label: "3개월" },
  { id: 180, label: "6개월" },
  { id: 365, label: "1년" },
  { id: 1000, label: "전체" },
];

export default function RealizedPnlPage() {
  const { accountId, connected } = useAccount();
  const [days, setDays] = useState(365);
  const [breakdownOpen, setBreakdownOpen] = useState(false);
  const [byTickerOpen, setByTickerOpen] = useState(false);
  const [dividendOpen, setDividendOpen] = useState(false);
  const [picked, setPicked] = useState<RealizedPnlItem | null>(null);
  // 막대 → 그 달 목록. null 월 + open 이면 "전체 목록".
  const [pnlMonth, setPnlMonth] = useState<string | null>(null);
  const [pnlListOpen, setPnlListOpen] = useState(false);
  const [tradeMonth, setTradeMonth] = useState<string | null>(null);
  const [tradeListOpen, setTradeListOpen] = useState(false);

  const realized = useQuery({
    queryKey: ["realized", accountId, days],
    queryFn: () => getRealizedPnl(accountId, days),
    staleTime: 60_000,
  });

  const data = realized.data;
  const items = data?.items ?? [];
  const decided = (data?.win_count ?? 0) + (data?.loss_count ?? 0);
  const winRate = decided > 0 ? ((data!.win_count / decided) * 100).toFixed(0) : null;

  // 종목별 손익 기여 — 같은 종목을 여러 번 팔았으면 합친다.
  const byTicker = aggregateByTicker(items);
  const b = data?.breakdown ?? null;
  const trades = data?.trades ?? [];

  // ★2026-09-25 사용자 지시(전체 메뉴 공통 패턴): 본문은 **월별 막대**, 목록은
  //   막대를 눌러 여는 팝업. 청산은 매도일 기준, 체결은 원장 날짜(결제일) 기준.
  const pnlColumns = useMemo(() => {
    const acc = new Map<string, number>();
    for (const r of items) {
      const m = r.sell_date.slice(0, 7);
      acc.set(m, (acc.get(m) ?? 0) + Number(r.pnl_krw ?? 0));
    }
    return [...acc.entries()]
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([m, v]) => ({ key: m, label: m, value: v }));
  }, [items]);
  const tradeColumns: StackColumn[] = useMemo(() => {
    const acc = new Map<string, { buy: number; sell: number }>();
    for (const t of trades) {
      const m = t.trade_date.slice(0, 7);
      const e = acc.get(m) ?? { buy: 0, sell: 0 };
      if (t.side === "BUY") e.buy += 1;
      else e.sell += 1;
      acc.set(m, e);
    }
    return [...acc.entries()]
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([m, e]) => ({
        key: m,
        label: m,
        total: e.buy + e.sell,
        segments: [
          { key: "BUY", label: "매수", value: e.buy },
          { key: "SELL", label: "매도", value: e.sell },
        ].filter((x) => x.value > 0),
      }));
  }, [trades]);

  const pnlShown = items.filter((r) => (pnlMonth ? r.sell_date.startsWith(pnlMonth) : true));
  const tradeShown = trades.filter((t) =>
    tradeMonth ? t.trade_date.startsWith(tradeMonth) : true,
  );

  const ranges = (
    <div className="flex flex-wrap items-center gap-1.5">
      {RANGES.map((r) => (
        <HeaderChip key={r.id} active={days === r.id} onClick={() => setDays(r.id)}>
          {r.label}
        </HeaderChip>
      ))}
    </div>
  );

  return (
    <>
      <Topbar title="체결·실현손익" />
      <PageContainer fit>
        {!connected && <NotConnectedBanner what="키움 실현손익" />}

        <div className="grid shrink-0 grid-cols-2 gap-2.5 lg:grid-cols-4">
          {/* ★2026-09-22 사용자 지정: 실현손익에 **배당을 포함**하고, 무엇으로
              벌었는지 종목 수익 / 배당 / 수수료 / 세금으로 쪼갠다. */}
          <StatTile
            label="실현손익 (배당 포함)"
            value={formatKrwSigned(b?.net_krw)}
            hint={
              data?.first_sell_date
                ? `${data.first_sell_date} ~ ${data.last_sell_date}`
                : "종목 수익 + 배당"
            }
            accent="auto"
            actionHint="눌러서 분해 보기"
            onClick={() => setBreakdownOpen(true)}
            loading={realized.isLoading}
          />
          <StatTile
            label="종목 수익"
            value={formatKrwSigned(data?.pnl_krw)}
            hint={
              winRate != null
                ? `승률 ${winRate}% (${data!.win_count}승 ${data!.loss_count}패) · 환차 제외`
                : "비용 차감 후 · 환차 제외"
            }
            accent="auto"
            actionHint="눌러서 종목별 기여 보기"
            onClick={() => setByTickerOpen(true)}
            loading={realized.isLoading}
          />
          <StatTile
            label="배당"
            value={formatKrwSigned(b?.dividend_krw)}
            hint="같은 기간 수령분"
            accent="auto"
            actionHint="눌러서 설명 보기"
            onClick={() => setDividendOpen(true)}
            loading={realized.isLoading}
          />
          {/* ⚠️예전 힌트는 "달러 분리: 수수료 $91.26 · 세금 $0.30" 이었다.
              그 달러 값은 **이 기간 모든 체결**(49건)이고 위 원화는 **판
              종목**(10건)이라, 분해인 척하면 35% 어긋난다($91.56 vs $68.02).
              같은 범위의 달러 값을 적는다. */}
          <StatTile
            label="수수료·세금"
            value={b ? `-${formatKrwString(b.cost_krw)}` : undefined}
            hint={
              b?.cost_local != null
                ? `판 종목 기준 $${Number(b.cost_local).toFixed(2)}`
                : "판 종목에 붙은 비용"
            }
            actionHint="눌러서 분해 보기"
            onClick={() => setBreakdownOpen(true)}
            accent="down"
            loading={realized.isLoading}
          />
        </div>

        <div
          className={cn(
            "grid min-h-0 flex-1 gap-3",
            "grid-cols-1 auto-rows-[minmax(0,1fr)]",
            "md:grid-cols-2 lg:auto-rows-auto",
            "lg:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]",
          )}
        >
          <StubCard
            title="월별 실현손익"
            subtitle={`${items.length}건 청산 · 막대를 누르면 그 달 청산 내역`}
            action={
              <div className="flex items-center gap-2">
                {ranges}
                <ListButton
                  onClick={() => {
                    setPnlMonth(null);
                    setPnlListOpen(true);
                  }}
                />
              </div>
            }
            scrollBody
          >
            {realized.isLoading ? (
              <CardEmpty text="불러오는 중…" />
            ) : (
              <SignedBarChart
                columns={pnlColumns}
                height={360}
                formatValue={(v) => formatKrwSigned(String(Math.round(v)))}
                selected={pnlMonth}
                onPick={(k) => {
                  setPnlMonth(k);
                  setPnlListOpen(true);
                }}
              />
            )}
          </StubCard>

          {/* ★체결 내역을 **여기로 합쳤다.** 따로 두면 "무엇을 팔았나"와
              "그래서 얼마 벌었나"가 갈려 매번 두 화면을 오가야 했다. */}
          <StubCard
            title="월별 체결"
            subtitle={
              data?.trade_stats
                ? `${trades.length}건 · 매수 ${data.trade_stats.buy_count} · 매도 ${data.trade_stats.sell_count}`
                : `${trades.length}건`
            }
            action={
              <ListButton
                onClick={() => {
                  setTradeMonth(null);
                  setTradeListOpen(true);
                }}
              />
            }
            scrollBody
          >
            {realized.isLoading ? (
              <CardEmpty text="불러오는 중…" />
            ) : (
              <StackedBarChart
                columns={tradeColumns}
                colors={TRADE_COLORS}
                height={340}
                formatTotal={(v) => `${v}건`}
                selected={tradeMonth}
                onSelect={(key, sticky) => {
                  if (sticky && key) {
                    setTradeMonth(key);
                    setTradeListOpen(true);
                  }
                }}
              />
            )}
            <p className="mt-2 text-[11px] leading-snug text-ink-muted">
              <span className="font-bold text-bid">■</span> 매수{" "}
              <span className="ml-1 font-bold text-ask">■</span> 매도 · 결제일(T+2) 기준
            </p>
          </StubCard>
        </div>
      </PageContainer>

      <Modal
        open={pnlListOpen}
        onClose={() => setPnlListOpen(false)}
        title={pnlMonth ? `${pnlMonth} 청산 내역` : "청산 내역 전체"}
        subtitle={`${pnlShown.length}건 · 합계 ${formatKrwSigned(
          String(Math.round(pnlShown.reduce((sum, r) => sum + Number(r.pnl_krw ?? 0), 0))),
        )}`}
        width={720}
      >
        <div className="max-h-[60vh] overflow-y-auto">
          <DataTable
            columns={["매도일", "종목", "손익", "수익률"]}
            align={["left", "left", "right", "right"]}
            empty="청산이 없습니다"
          >
            {pnlShown.map((r) => (
              <tr
                key={r.id}
                onClick={() => setPicked(r)}
                className="cursor-pointer border-b border-hairline transition-colors hover:bg-canvas-soft"
              >
                <Cell left tone="muted">{r.sell_date}</Cell>
                <Cell left strong>
                  <span className="flex items-center gap-1.5">
                    <span className="max-w-[200px] truncate">{r.asset_name ?? r.ticker}</span>
                    <span className="shrink-0 text-[10px] font-bold text-ink-faint">{r.ticker}</span>
                  </span>
                </Cell>
                <Cell strong tone={toneOf(r.pnl_krw)}>{formatKrwSigned(r.pnl_krw)}</Cell>
                <Cell tone={toneOf(r.pnl_rate)}>{formatPercentString(r.pnl_rate)}</Cell>
              </tr>
            ))}
          </DataTable>
        </div>
      </Modal>

      <Modal
        open={tradeListOpen}
        onClose={() => setTradeListOpen(false)}
        title={tradeMonth ? `${tradeMonth} 체결 내역` : "체결 내역 전체"}
        subtitle={`${tradeShown.length}건 · 결제일(T+2) 기준`}
        width={720}
      >
        <div className="max-h-[60vh] overflow-y-auto">
          <DataTable
            columns={["체결일", "종목", "구분", "수량", "단가"]}
            align={["left", "left", "left", "right", "right"]}
            empty="체결이 없습니다"
          >
            {tradeShown.map((t) => (
              <tr key={t.id} className="border-b border-hairline">
                <Cell left tone="muted">{t.trade_date}</Cell>
                <Cell left strong>
                  <span className="flex items-center gap-1.5">
                    <span className="max-w-[200px] truncate">{t.asset_name ?? t.ticker}</span>
                    <span className="shrink-0 text-[10px] font-bold text-ink-faint">{t.ticker}</span>
                  </span>
                </Cell>
                <Cell left>
                  <span
                    className={cn(
                      "rounded px-1.5 py-0.5 text-[10px] font-bold",
                      t.side === "BUY" ? "bg-bid-soft text-bid" : "bg-ask-soft text-ask",
                    )}
                  >
                    {t.side === "BUY" ? "매수" : "매도"}
                  </span>
                </Cell>
                <Cell>{Number(t.quantity).toLocaleString()}</Cell>
                <Cell tone="muted">
                  {t.price == null
                    ? "—"
                    : `$${Number(t.price).toLocaleString("en-US", {
                        minimumFractionDigits: 2,
                        maximumFractionDigits: 2,
                      })}`}
                </Cell>
              </tr>
            ))}
          </DataTable>
        </div>
      </Modal>

      <Modal
        open={byTickerOpen}
        onClose={() => setByTickerOpen(false)}
        title="종목별 손익 기여"
        subtitle="주가 기준 · 비용 차감 후 · 환차 제외"
        width={620}
      >
        <DataTable
          columns={["종목", "청산", "손익"]}
          align={["left", "right", "right"]}
          empty="데이터가 없습니다"
        >
          {byTicker.map((t) => (
            <tr key={t.ticker} className="border-b border-hairline">
              <Cell left strong>
                <span className="flex items-center gap-1.5">
                  <span className="max-w-[220px] truncate">{t.name ?? t.ticker}</span>
                  <span className="shrink-0 text-[10px] font-bold text-ink-faint">{t.ticker}</span>
                </span>
              </Cell>
              <Cell tone="muted">{t.count}회</Cell>
              <Cell strong tone={t.pnl >= 0 ? "up" : "down"}>
                {formatKrwSigned(String(Math.round(t.pnl)))}
              </Cell>
            </tr>
          ))}
        </DataTable>
      </Modal>

      <Modal
        open={dividendOpen}
        onClose={() => setDividendOpen(false)}
        title="배당"
        subtitle="이 화면에서는 합계만"
        width={520}
      >
        <p className="text-[12px] leading-relaxed text-ink-secondary">
          같은 기간 수령한 배당 <b className="text-ink">{formatKrwSigned(b?.dividend_krw)}</b>
        </p>
        <Link
          href="/income/cashflow"
          className="mt-3 inline-block text-[12px] font-bold text-ge-point hover:text-ink"
        >
          현금유출입에서 월별 배당 보기 →
        </Link>
      </Modal>

      <Modal
        open={breakdownOpen}
        onClose={() => setBreakdownOpen(false)}
        title="실현손익 분해"
      >
        {b ? (
          <div className="space-y-3">
            <div>
              <BreakLine label="종목 수익 (비용 차감 전)" value={b.gross_trading_krw} signed />
              <BreakLine label="수수료·세금" value={`-${b.cost_krw}`} signed />
              <BreakLine label="배당" value={b.dividend_krw} signed />
              <div className="mt-1 border-t border-ink pt-1">
                <BreakLine label="실현손익 합계" value={b.net_krw} signed strong />
              </div>
            </div>
          </div>
        ) : (
          <p className="text-[12px] text-ink-faint">분해할 내역이 없습니다.</p>
        )}
      </Modal>

      <Modal
        open={picked != null}
        onClose={() => setPicked(null)}
        title={picked?.asset_name ?? picked?.ticker ?? ""}
        subtitle={picked ? `${picked.sell_date} 청산` : undefined}
      >
        {picked && <RealizedDetail item={picked} />}
      </Modal>
    </>
  );
}

// 매수 = 상승색(bid), 매도 = 하락색(ask). 이 레포의 매수/매도 배지와 같은 색이다.
const TRADE_COLORS: Record<string, string> = { BUY: "#A33A2A", SELL: "#3A6B96" };

/** 목록에서 뺀 열들. 주가 손익과 환차손익을 **나란히** 두어 차이가 보이게 한다. */
function RealizedDetail({ item: r }: { item: RealizedPnlItem }) {
  const rows: [string, string][] = [
    ["종목코드", r.ticker],
    ["수량", formatQuantityString(r.quantity)],
    ["매입평균", formatPriceString(r.avg_buy_price, r.currency)],
    ["매도평균", formatPriceString(r.avg_sell_price, r.currency)],
    ["매입금액", formatPriceString(r.buy_amount_local, r.currency)],
    ["매도금액", formatPriceString(r.sell_amount_local, r.currency)],
    ["수수료·세금", formatPriceString(r.commission_tax_local, r.currency)],
    ["실현손익 (외화)", formatPriceString(r.pnl_local, r.currency)],
    ["실현손익 (주가, 원화)", formatKrwSigned(r.pnl_krw)],
    ["수익률", formatPercentString(r.pnl_rate)],
    // 환차가 어디서 나왔는지 보이게 매수/매도 시점 환율을 같이 둔다.
    ["매수 환율", formatPriceString(r.buy_exchange_rate, "KRW")],
    ["매도 환율", formatPriceString(r.sell_exchange_rate, "KRW")],
    ["환차손익", formatKrwSigned(r.fx_pnl_krw)],
  ];
  const total =
    r.pnl_krw != null && r.fx_pnl_krw != null
      ? String(Number(r.pnl_krw) + Number(r.fx_pnl_krw))
      : null;
  return (
    <div className="space-y-3">
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
      {total && (
        <p className="text-[11px] leading-relaxed text-ink-muted">
          주가 {formatKrwSigned(r.pnl_krw)} + 환차 {formatKrwSigned(r.fx_pnl_krw)} ={" "}
          <b className="tabular-nums text-ink">{formatKrwSigned(total)}</b>
        </p>
      )}
    </div>
  );
}

function BreakLine({
  label,
  value,
  signed,
  strong,
}: {
  label: string;
  value: string;
  signed?: boolean;
  strong?: boolean;
}) {
  return (
    <div className="flex items-baseline justify-between gap-2">
      <span
        className={cn(
          "text-[12px]",
          strong ? "font-bold text-ink" : "text-ink-secondary",
        )}
      >
        {label}
      </span>
      <span
        className={cn(
          "tabular-nums",
          strong
            ? "text-[14px] font-extrabold text-ink"
            : "text-[12px] font-semibold text-ink-secondary",
        )}
      >
        {signed ? formatKrwSigned(value) : formatKrwString(value)}
      </span>
    </div>
  );
}

function aggregateByTicker(items: RealizedPnlItem[]) {
  const acc = new Map<string, { ticker: string; name: string | null; pnl: number; count: number }>();
  for (const r of items) {
    const entry = acc.get(r.ticker) ?? {
      ticker: r.ticker,
      name: r.asset_name,
      pnl: 0,
      count: 0,
    };
    entry.pnl += Number(r.pnl_krw ?? 0);
    entry.count += 1;
    acc.set(r.ticker, entry);
  }
  return [...acc.values()].sort((a, b) => b.pnl - a.pnl);
}

