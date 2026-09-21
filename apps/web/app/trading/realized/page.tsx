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

const RANGES = [
  { id: 90, label: "3개월" },
  { id: 180, label: "6개월" },
  { id: 365, label: "1년" },
  { id: 1000, label: "전체" },
];

export default function RealizedPnlPage() {
  const { accountId, connected } = useAccount();
  const [days, setDays] = useState(365);

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

  return (
    <>
      <Topbar title="실현손익" subtitle="매도 확정 기준" />
      <PageContainer wide>
        {!connected && <NotConnectedBanner what="키움 실현손익" />}

        <StatRow>
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
            hint="환율 변동에 따른 손익 (별도)"
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
        </StatRow>

        {/* 둘을 더한 값도 알려주되, 합계가 주인공이 아님을 분명히 한다. */}
        {data?.pnl_krw != null && data.fx_pnl_krw != null && (
          <div className="mb-4 rounded-xl border border-hairline bg-canvas px-4 py-3 shadow-card">
            <p className="text-[12px] font-semibold text-ink-secondary">
              주가 {formatKrwSigned(data.pnl_krw)} + 환차{" "}
              {formatKrwSigned(data.fx_pnl_krw)} ={" "}
              <b
                className={cn(
                  "tabular-nums",
                  Number(data.pnl_krw) + Number(data.fx_pnl_krw) >= 0
                    ? "text-bid"
                    : "text-ask",
                )}
              >
                {formatKrwSigned(
                  String(Number(data.pnl_krw) + Number(data.fx_pnl_krw)),
                )}
              </b>
              <span className="ml-2 font-medium text-ink-faint">
                — 둘은 다른 사건입니다. 종목 선택이 좋았는지는 왼쪽(주가)만 봅니다.
              </span>
            </p>
          </div>
        )}

        <div className="mb-4 flex flex-wrap items-center gap-2">
          {RANGES.map((r) => (
            <Chip key={r.id} active={days === r.id} onClick={() => setDays(r.id)}>
              {r.label}
            </Chip>
          ))}
          <span className="ml-auto text-[11px] font-semibold text-ink-faint">
            {items.length}건
          </span>
        </div>

        <div className="grid gap-4 xl:grid-cols-[1.6fr_1fr]">
          <StubCard title="청산 내역" subtitle="최근순">
            <DataTable
              columns={[
                "매도일",
                "종목",
                "수량",
                "매입평균",
                "매도평균",
                "손익",
                "수익률",
                "환차손익",
              ]}
              align={[
                "left", "left", "right", "right",
                "right", "right", "right", "right",
              ]}
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
                  className="border-t border-hairline transition-colors hover:bg-canvas-soft/60"
                >
                  <Cell left tone="muted">
                    {r.sell_date}
                  </Cell>
                  <Cell left strong>
                    <span className="flex items-center gap-2">
                      {r.asset_name ?? r.ticker}
                      <span className="text-[10px] font-semibold text-ink-faint">
                        {r.ticker}
                      </span>
                    </span>
                  </Cell>
                  <Cell>{formatQuantityString(r.quantity)}</Cell>
                  <Cell>{formatPriceString(r.avg_buy_price, r.currency)}</Cell>
                  <Cell>{formatPriceString(r.avg_sell_price, r.currency)}</Cell>
                  <Cell strong tone={toneOf(r.pnl_krw)}>
                    {formatKrwSigned(r.pnl_krw)}
                  </Cell>
                  <Cell tone={toneOf(r.pnl_rate)}>
                    {formatPercentString(r.pnl_rate)}
                  </Cell>
                  {/* 환차는 회색 계열로 — 주가 손익과 시각적으로 섞이지 않게. */}
                  <Cell
                    className={cn(
                      Number(r.fx_pnl_krw ?? 0) >= 0 ? "text-ink-secondary" : "text-ink-muted",
                    )}
                  >
                    {formatKrwSigned(r.fx_pnl_krw)}
                  </Cell>
                </tr>
              ))}
            </DataTable>
          </StubCard>

          <StubCard title="종목별 손익 기여" subtitle="주가 손익 기준">
            <DataTable
              columns={["종목", "청산", "손익"]}
              align={["left", "right", "right"]}
              empty={realized.isLoading ? "불러오는 중…" : "데이터가 없습니다"}
            >
              {byTicker.map((t) => (
                <tr
                  key={t.ticker}
                  className="border-t border-hairline transition-colors hover:bg-canvas-soft/60"
                >
                  <Cell left strong>
                    {t.name ?? t.ticker}
                  </Cell>
                  <Cell tone="muted">{t.count}회</Cell>
                  <Cell tone={t.pnl >= 0 ? "up" : "down"}>
                    {formatKrwSigned(String(Math.round(t.pnl)))}
                  </Cell>
                </tr>
              ))}
            </DataTable>
          </StubCard>
        </div>
      </PageContainer>
    </>
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
