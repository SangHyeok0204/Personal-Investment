"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { PageContainer } from "@/components/layout/page-header";
import { Topbar } from "@/components/layout/topbar";
import { useAccount } from "@/components/layout/account-context";
import { Modal } from "@/components/ui/modal";
import { Cell, DataTable, NotConnectedBanner, StatTile, StubCard } from "@/components/stub";
import { getTradingCosts, type TradingCost } from "@/lib/api";
import { formatKrwSigned } from "@/lib/format";
import { cn } from "@/lib/utils";

// 수수료/세금 — 매매가 실제로 얼마를 먹었나.
//
// ★금액은 **USD 그대로** 둔다. 편입비와 같은 이유다 — trades.amount_krw 는
//   82건 전부 비어 있고 거래일 환율도 없다. 오늘 환율을 과거 거래에 곱하면
//   그 숫자는 거짓이 된다.
//
// ⚠️비용률의 분모는 **거래대금**이다. 평가액이 아니다 — 비용은 얼마를 들고
//   있느냐가 아니라 **얼마를 굴렸느냐**에 붙는다.
//
// ⚠️실현손익과 비용을 더하거나 빼지 않는다. 증권사 실현손익이 비용을 이미
//   반영했는지 확실하지 않다. 나란히 두고 판단은 사용자에게 맡긴다 —
//   확실하지 않은 계산으로 한 숫자를 만들면 그게 더 나쁘다.

function usd(value: string | null | undefined): string {
  if (value == null) return "—";
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  return `$${n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function pct(value: string | null | undefined, digits = 3): string {
  if (value == null) return "—";
  const n = Number(value);
  return Number.isFinite(n) ? `${(n * 100).toFixed(digits)}%` : "—";
}

const SIDE_LABEL: Record<string, string> = { BUY: "매수", SELL: "매도" };

export default function TradingCostsPage() {
  const { accountId, connected } = useAccount();
  const [noteOpen, setNoteOpen] = useState(false);

  const costs = useQuery({
    queryKey: ["tradingCosts", accountId],
    queryFn: () => getTradingCosts(accountId),
    staleTime: 60_000,
  });

  const data = costs.data;
  const byTicker = data?.by_ticker ?? [];

  return (
    <>
      <Topbar title="수수료/세금" subtitle="매매가 실제로 얼마를 먹었나" />
      <PageContainer fit>
        {!connected && !costs.isLoading && <NotConnectedBanner what="체결 내역" />}

        <div className="grid shrink-0 grid-cols-2 gap-2.5 lg:grid-cols-4">
          <StatTile
            label="총 거래비용"
            value={data?.total_cost ? usd(data.total_cost) : null}
            hint={
              data
                ? `수수료 ${usd(data.commission)} · 세금 ${usd(data.tax)}`
                : "수수료 + 세금"
            }
            accent="down"
            loading={costs.isLoading}
          />
          <StatTile
            label="비용률"
            value={data?.cost_ratio ? pct(data.cost_ratio) : null}
            hint="거래대금 대비 · 눌러서 설명"
            actionHint="눌러서 읽는 법 보기"
            onClick={() => setNoteOpen(true)}
            loading={costs.isLoading}
          />
          <StatTile
            label="거래대금"
            value={data?.turnover ? usd(data.turnover) : null}
            hint={
              data
                ? `${data.trade_count}건 · ${data.first_trade_date} ~ ${data.last_trade_date}`
                : "매수 + 매도"
            }
            loading={costs.isLoading}
          />
          <StatTile
            label="(참고) 실현손익"
            value={formatKrwSigned(data?.realized_pnl_krw)}
            hint="비용과 더하지 않음 — 통화도 다름"
            accent="auto"
            loading={costs.isLoading}
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
            title="종목별 비용"
            subtitle={`${byTicker.length}종목 · 비용 순`}
            scrollBody
          >
            <DataTable
              columns={["종목", "건수", "거래대금", "비용", "비용률"]}
              align={["left", "right", "right", "right", "right"]}
              empty={
                costs.isLoading
                  ? "불러오는 중…"
                  : connected
                    ? "체결 내역이 없습니다"
                    : "계좌를 연동하면 거래비용이 표시됩니다"
              }
            >
              {byTicker.map((t) => (
                <tr key={t.ticker} className="border-b border-hairline">
                  <Cell left strong>
                    <span className="flex items-center gap-1.5">
                      <span className="max-w-[130px] truncate">
                        {t.name ?? t.ticker}
                      </span>
                      <span className="shrink-0 text-[10px] font-bold text-ink-faint">
                        {t.ticker}
                      </span>
                    </span>
                  </Cell>
                  <Cell tone="muted">{t.trade_count}</Cell>
                  <Cell>{usd(t.turnover)}</Cell>
                  <Cell strong tone="down">
                    {usd(t.cost)}
                  </Cell>
                  <Cell tone="muted">{pct(t.cost_ratio)}</Cell>
                </tr>
              ))}
            </DataTable>
          </StubCard>

          <StubCard title="매수 · 매도" subtitle="어느 쪽이 더 무거운가" scrollBody>
            {costs.isLoading ? (
              <Empty text="불러오는 중…" />
            ) : (data?.by_side.length ?? 0) === 0 ? (
              <Empty text="표시할 내역이 없습니다" />
            ) : (
              <>
                <DataTable
                  columns={["구분", "건수", "비용", "비용률"]}
                  align={["left", "right", "right", "right"]}
                >
                  {(data?.by_side ?? []).map((s) => (
                    <tr key={s.side} className="border-b border-hairline">
                      <Cell left strong>
                        <span
                          className={cn(
                            "rounded px-1.5 py-0.5 text-[10px] font-bold",
                            s.side === "BUY"
                              ? "bg-bid-soft text-bid"
                              : "bg-ask-soft text-ask",
                          )}
                        >
                          {SIDE_LABEL[s.side] ?? s.side}
                        </span>
                      </Cell>
                      <Cell tone="muted">{s.trade_count}</Cell>
                      <Cell strong>
                        {usd(String(Number(s.commission) + Number(s.tax)))}
                      </Cell>
                      <Cell tone="muted">{pct(s.cost_ratio)}</Cell>
                    </tr>
                  ))}
                </DataTable>

                <p className="mt-3 mb-1.5 text-[11px] font-bold text-ink-muted">
                  월별 비용
                </p>
                <MonthlyCosts months={data!.by_month} />
              </>
            )}
          </StubCard>
        </div>
      </PageContainer>

      <Modal
        open={noteOpen}
        onClose={() => setNoteOpen(false)}
        title="이 화면 읽는 법"
        subtitle="비용률의 분모가 무엇인가"
      >
        <ul className="space-y-2.5 text-[12px] leading-relaxed text-ink-secondary">
          <li>
            <strong>비용률의 분모는 거래대금입니다.</strong> 평가액이 아닙니다 —
            비용은 얼마를 들고 있느냐가 아니라 <strong>얼마를 굴렸느냐</strong>에
            붙습니다. 같은 돈이라도 자주 사고팔면 비용은 그만큼 늘어납니다.
          </li>
          <li>
            <strong>실현손익과 비용을 더하거나 빼지 않았습니다.</strong> 증권사가
            주는 실현손익이 비용을 이미 반영했는지 확실하지 않습니다. 확실하지 않은
            계산으로 한 숫자를 만들면 그게 더 나쁘므로, 나란히 두고 판단은 남겨
            둡니다. 통화도 다릅니다(비용 USD / 실현손익 KRW).
          </li>
          <li>
            <strong>금액은 달러 그대로입니다.</strong> 체결의 원화 금액이 비어 있고
            거래일 환율도 없어서, 오늘 환율을 과거 거래에 곱하지 않았습니다.
          </li>
          <li>
            <strong>체결되지 않은 주문은 비용이 없습니다.</strong> 주문/미체결
            화면을 보면 주문 3건 중 1건 넘게 체결되지 않았는데, 그 주문들은 여기
            집계에 들어오지 않습니다.
          </li>
        </ul>
      </Modal>
    </>
  );
}

function MonthlyCosts({ months }: { months: TradingCost["by_month"] }) {
  const max = Math.max(...months.map((m) => Number(m.cost)), 0.01);
  return (
    <div className="space-y-1.5">
      {[...months].reverse().map((m) => (
        <div key={m.month}>
          <div className="mb-0.5 flex items-baseline justify-between">
            <span className="text-[11px] font-bold text-ge-navy">{m.month}</span>
            <span className="text-[11px] font-bold tabular-nums text-ink-secondary">
              {usd(m.cost)}
              <span className="ml-1.5 font-semibold text-ink-faint">
                {m.trade_count}건
              </span>
            </span>
          </div>
          <div className="h-1.5 w-full overflow-hidden rounded-full bg-canvas-soft">
            <div
              className="h-full rounded-full bg-ask"
              style={{ width: `${(Number(m.cost) / max) * 100}%` }}
            />
          </div>
        </div>
      ))}
    </div>
  );
}

function Empty({ text }: { text: string }) {
  return (
    <div className="flex h-full items-center justify-center px-4 text-center">
      <span className="text-[12px] font-semibold text-ink-faint">{text}</span>
    </div>
  );
}
