"use client";

import { useState } from "react";
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
  const [picked, setPicked] = useState<RealizedPnlItem | null>(null);

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

  const ranges = (
    <div className="flex flex-wrap items-center gap-1.5">
      {RANGES.map((r) => (
        <Chip key={r.id} active={days === r.id} onClick={() => setDays(r.id)}>
          {r.label}
        </Chip>
      ))}
    </div>
  );

  return (
    <>
      <Topbar title="실현손익" subtitle="매도 확정 기준" />
      <PageContainer fit>
        {!connected && <NotConnectedBanner what="키움 실현손익" />}

        <div className="grid shrink-0 grid-cols-2 gap-2.5 lg:grid-cols-4">
          <StatTile
            label="실현손익 (주가)"
            value={formatKrwSigned(data?.pnl_krw)}
            hint={
              data?.first_sell_date
                ? `${data.first_sell_date} ~ ${data.last_sell_date}`
                : "매도 확정분"
            }
            accent="auto"
            loading={realized.isLoading}
          />
          <StatTile
            label="환차손익"
            value={formatKrwSigned(data?.fx_pnl_krw)}
            hint={
              // 합계도 알려주되 주인공이 아님을 분명히 한다 — 둘은 다른 사건이다.
              data?.pnl_krw != null && data.fx_pnl_krw != null
                ? `주가와 합치면 ${formatKrwSigned(String(Number(data.pnl_krw) + Number(data.fx_pnl_krw)))}`
                : "환율 변동에 따른 손익 (별도)"
            }
            accent="auto"
            loading={realized.isLoading}
          />
          <StatTile
            label="승률"
            value={winRate == null ? undefined : `${winRate}%`}
            hint={
              data ? `익절 ${data.win_count} · 손절 ${data.loss_count}` : "익절 / 전체 청산"
            }
            loading={realized.isLoading}
          />
          <StatTile
            label="청산 건수"
            value={data ? `${data.total}` : undefined}
            hint="매도일 × 종목 기준"
            loading={realized.isLoading}
          />
        </div>

        <div
          className={cn(
            "grid min-h-0 flex-1 gap-3",
            "grid-cols-1 auto-rows-[minmax(0,1fr)]",
            "md:grid-cols-2 lg:auto-rows-auto",
            "lg:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)]",
          )}
        >
          <StubCard
            title="청산 내역"
            subtitle={`${items.length}건 · 최근순`}
            action={ranges}
            scrollBody
          >
            <DataTable
              columns={["매도일", "종목", "손익", "수익률"]}
              align={["left", "left", "right", "right"]}
              empty={
                realized.isLoading
                  ? "불러오는 중…"
                  : connected
                    ? "해당 기간에 청산이 없습니다"
                    : "계좌를 연동하면 실현손익이 표시됩니다"
              }
            >
              {items.map((r) => (
                <tr
                  key={r.id}
                  onClick={() => setPicked(r)}
                  className="cursor-pointer border-b border-hairline transition-colors hover:bg-canvas-soft"
                >
                  <Cell left tone="muted">
                    {r.sell_date}
                  </Cell>
                  <Cell left strong>
                    <span className="flex items-center gap-1.5">
                      <span className="max-w-[150px] truncate">
                        {r.asset_name ?? r.ticker}
                      </span>
                      <span className="shrink-0 text-[10px] font-bold text-ink-faint">
                        {r.ticker}
                      </span>
                    </span>
                  </Cell>
                  <Cell strong tone={toneOf(r.pnl_krw)}>
                    {formatKrwSigned(r.pnl_krw)}
                  </Cell>
                  <Cell tone={toneOf(r.pnl_rate)}>
                    {formatPercentString(r.pnl_rate)}
                  </Cell>
                </tr>
              ))}
            </DataTable>
          </StubCard>

          <StubCard title="종목별 손익 기여" subtitle="주가 손익 기준" scrollBody>
            <DataTable
              columns={["종목", "청산", "손익"]}
              align={["left", "right", "right"]}
              empty={realized.isLoading ? "불러오는 중…" : "데이터가 없습니다"}
            >
              {byTicker.map((t) => (
                <tr key={t.ticker} className="border-b border-hairline">
                  <Cell left strong>
                    <span className="block max-w-[150px] truncate">
                      {t.name ?? t.ticker}
                    </span>
                  </Cell>
                  <Cell tone="muted">{t.count}회</Cell>
                  <Cell strong tone={t.pnl >= 0 ? "up" : "down"}>
                    {formatKrwSigned(String(Math.round(t.pnl)))}
                  </Cell>
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
        subtitle={picked ? `${picked.sell_date} 청산` : undefined}
      >
        {picked && <RealizedDetail item={picked} />}
      </Modal>
    </>
  );
}

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
      <p className="text-[11px] leading-relaxed text-ink-muted">
        {total && (
          <>
            주가 {formatKrwSigned(r.pnl_krw)} + 환차 {formatKrwSigned(r.fx_pnl_krw)} ={" "}
            <b className="tabular-nums text-ink">{formatKrwSigned(total)}</b>.{" "}
          </>
        )}
        <strong>둘은 다른 사건입니다.</strong> 종목 선택이 좋았는지는 주가 손익만
        봅니다 — 환차는 환율이 움직인 결과이지 매매 판단의 결과가 아닙니다.
      </p>
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
      // 카드 헤더(짙은 갈색) 위에 올라가므로 흰 계열로 맞춘다.
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
