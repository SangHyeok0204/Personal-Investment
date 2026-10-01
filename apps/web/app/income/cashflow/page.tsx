"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { PageContainer } from "@/components/layout/page-header";
import { Topbar } from "@/components/layout/topbar";
import { useAccount } from "@/components/layout/account-context";
import { Modal } from "@/components/ui/modal";
import { DonutChart, colorForKeys, type DonutSlice } from "@/components/charts/donut-chart";
import { StackedBarChart, type StackColumn } from "@/components/charts/stacked-bar-chart";
import { SignedBarChart } from "@/components/charts/signed-bar-chart";
import {
  CardEmpty,
  Cell,
  DataTable,
  Figure,
  NotConnectedBanner,
  PlannedList,
  StatTile,
  StubCard,
  toneOf,
} from "@/components/stub";
import {
  getCashflow,
  getDividends,
  getMonthlyCashflow,
  getTax,
  getTradingCosts,
  type MonthlyCashflowRow,
} from "@/lib/api";
import {
  formatKrwCompactString,
  formatKrwSigned,
  formatKrwString,
  formatPercentString,
} from "@/lib/format";
import { cn } from "@/lib/utils";

// 현금유출입 — 배당 이력 · 입출금 · 월별 현금흐름 · 수수료 · 세금을 한 화면으로
// (2026-09-25 사용자 지시). 다섯 화면이 따로 있던 것을 합쳤다.
//
// ★구성 원칙: **화면에는 숫자 하나, 누르면 상세.** 위 칸 다섯 개가 각 주제의
//   대표값이고, 칸을 누르면 원래 화면이 보여 주던 표가 팝업으로 뜬다. 본문의 월별
//   막대는 막대를 누르면 그 달의 세부 내역이 뜬다.
//
// ⚠️통화가 섞여 있다. 거래비용만 **USD**(trades 원천 — 거래일 환율이 없어 원화로
//   바꾸면 거짓이 된다), 나머지는 원화다. 그래서 비용을 다른 칸과 더하지 않는다.
//   월별 현금흐름의 '비용'은 원화(일별성과 원천)라 출처가 다르다 — 이어 붙이지 않는다.
//
// ⚠️기준 기간도 다르다. 세금만 **역년**이고 나머지는 조회 기간이다. 그래서 같은
//   2026년 배당이 배당 칸과 세금 팝업에서 다르게 나온다 — 각 칸 아래에 기준을 적는다.

const RANGES = [
  { id: 180, label: "6개월" },
  { id: 365, label: "1년" },
  { id: 1095, label: "전체" },
];

function usd(value: string | null | undefined, digits = 2): string {
  if (value == null || value === "") return "—";
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  return `$${n.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits })}`;
}

type Panel = "transfers" | "dividends" | "generated" | "costs" | "tax" | null;

export default function CashflowPage() {
  const { accountId, connected } = useAccount();
  const [days, setDays] = useState(365);
  const [panel, setPanel] = useState<Panel>(null);
  // 막대를 눌러 여는 달 상세 — 배당(월×종목)과 현금흐름(월 한 줄)이 따로다.
  const [divMonth, setDivMonth] = useState<string | null>(null);
  const [flowMonth, setFlowMonth] = useState<string | null>(null);
  const [transferMonth, setTransferMonth] = useState<string | null>(null);
  const [taxYear, setTaxYear] = useState<number | null>(null);

  const cashflow = useQuery({
    queryKey: ["cashflow", accountId],
    queryFn: () => getCashflow(accountId),
    staleTime: 60_000,
  });
  const dividends = useQuery({
    queryKey: ["dividends", accountId, days],
    queryFn: () => getDividends(accountId, days),
    staleTime: 60_000,
  });
  const monthly = useQuery({
    queryKey: ["monthlyCashflow", accountId],
    queryFn: () => getMonthlyCashflow(accountId),
    staleTime: 60_000,
  });
  const costs = useQuery({
    queryKey: ["tradingCosts", accountId],
    queryFn: () => getTradingCosts(accountId),
    staleTime: 60_000,
  });
  const tax = useQuery({
    queryKey: ["tax", accountId, taxYear],
    queryFn: () => getTax(accountId, taxYear),
    staleTime: 60_000,
  });

  // ── 배당: 월 × 종목 누적막대 (옛 배당 이력 화면과 같은 방식) ──────────────
  const div = dividends.data;
  const byTicker = div?.by_ticker ?? [];
  const colors = useMemo(() => colorForKeys(byTicker.map((t) => t.ticker)), [byTicker]);
  const divColumns: StackColumn[] = useMemo(() => {
    const names: Record<string, string> = {};
    for (const t of byTicker) names[t.ticker] = t.asset_name ?? t.ticker;
    const buckets = new Map<string, Map<string, number>>();
    for (const d of div?.items ?? []) {
      const month = d.pay_date.slice(0, 7);
      const inner = buckets.get(month) ?? new Map<string, number>();
      inner.set(d.ticker, (inner.get(d.ticker) ?? 0) + Number(d.amount_krw));
      buckets.set(month, inner);
    }
    return (div?.monthly ?? []).map((m) => {
      const inner = buckets.get(m.month) ?? new Map<string, number>();
      return {
        key: m.month,
        label: m.month,
        total: Number(m.amount_krw),
        // 큰 종목이 아래로 깔리게 금액 순서(서버 by_ticker 순서)로 쌓는다.
        segments: byTicker
          .filter((t) => (inner.get(t.ticker) ?? 0) > 0)
          .map((t) => ({ key: t.ticker, label: names[t.ticker], value: inner.get(t.ticker) ?? 0 })),
      };
    });
  }, [div, byTicker]);
  const divPicked = divColumns.find((c) => c.key === divMonth) ?? null;
  // 그 달의 지급 건별 목록 — 누적막대가 월로 묶어 잃은 '지급일'을 여기서 돌려준다.
  const divPickedItems = useMemo(
    () => (div?.items ?? []).filter((d) => d.pay_date.startsWith(divMonth ?? "—")),
    [div, divMonth],
  );

  // ── 월별 현금흐름: 계좌가 만든 현금(배당 − 비용) ───────────────────────────
  const rows = useMemo(
    () => [...(monthly.data?.rows ?? [])].sort((a, b) => a.month.localeCompare(b.month)),
    [monthly.data],
  );
  const flowPicked = rows.find((r) => r.month === flowMonth) ?? null;

  // ── 입출금: 월별 순입출금 ───────────────────────────────────────────────
  const cf = cashflow.data;
  // ⚠️기간 **첫날**의 입출금은 서버가 시작 잔고에 넣고 순입출금에서 뺀다
  //   (first_day_flow_krw). 월별 막대에 그대로 두면 칸의 순입출금(+187만)과
  //   첫 달 막대(+784만)가 서로 다른 말을 한다 — 막대에서도 뺀다(시작일이 06-04 이던
  //   때의 실측. 06-01 시작인 지금은 첫날 입출금이 0 이다).
  const firstMonth = cf?.first_date?.slice(0, 7) ?? null;
  const firstDayFlow = Number(cf?.first_day_flow_krw ?? 0);
  const transferColumns = useMemo(
    () =>
      [...(cf?.monthly ?? [])]
        .sort((a, b) => a.month.localeCompare(b.month))
        .map((m) => ({
          key: m.month,
          label: m.month,
          value: Number(m.net_krw) - (m.month === firstMonth ? firstDayFlow : 0),
        })),
    [cf, firstMonth, firstDayFlow],
  );
  const transferEvents = useMemo(
    () =>
      (cf?.events ?? []).filter((e) =>
        transferMonth ? e.base_date.startsWith(transferMonth) : true,
      ),
    [cf, transferMonth],
  );

  const t = tax.data?.current ?? null;
  const c = costs.data;
  const m = monthly.data;

  const ranges = (
    <div className="flex gap-1">
      {RANGES.map((r) => (
        <button
          key={r.id}
          type="button"
          onClick={() => setDays(r.id)}
          aria-pressed={days === r.id}
          className={cn(
            "rounded px-1.5 py-0.5 text-[10px] font-bold transition-colors",
            days === r.id
              ? "bg-white/90 text-ge-header"
              : "text-white/60 hover:bg-white/15 hover:text-white",
          )}
        >
          {r.label}
        </button>
      ))}
    </div>
  );

  return (
    <>
      <Topbar title="현금유출입" subtitle="입출금 · 배당 · 계좌 현금 · 거래비용 · 세금" />
      <PageContainer fit>
        {!connected && <NotConnectedBanner what="키움 계좌 API" />}

        {/* 1행: 주제별 대표값 하나씩. 누르면 상세. */}
        <div className="grid shrink-0 grid-cols-2 gap-2.5 md:grid-cols-3 xl:grid-cols-5">
          <StatTile
            label="순입출금"
            value={formatKrwSigned(cf?.net_deposit_krw)}
            hint={
              cf
                ? `입금 ${formatKrwCompactString(cf.total_deposit_krw)} · 출금 ${formatKrwCompactString(cf.total_withdrawal_krw)}`
                : "입금 − 출금"
            }
            onClick={() => setPanel("transfers")}
            actionHint="눌러서 월별 입출금 보기"
            loading={cashflow.isLoading}
          />
          <StatTile
            label="배당 수령"
            value={formatKrwString(div?.total_amount_krw)}
            hint={
              div
                ? `${div.total}회 · ${byTicker.length}종목 · ${RANGES.find((r) => r.id === days)?.label}`
                : "조회 기간"
            }
            accent="up"
            onClick={() => setPanel("dividends")}
            actionHint="눌러서 종목별 보기"
            loading={dividends.isLoading}
          />
          <StatTile
            label="계좌가 만든 현금"
            value={formatKrwSigned(m?.net_cash_generated_krw)}
            hint={
              m
                ? `배당 − 비용 · 배당이 비용을 넘은 달 ${m.months_dividend_covered_cost}/${m.months_total}`
                : "배당 − 비용"
            }
            accent="auto"
            onClick={() => setPanel("generated")}
            actionHint="눌러서 월별 표 보기"
            loading={monthly.isLoading}
          />
          <StatTile
            label="거래비용 (USD)"
            value={usd(c?.total_cost)}
            hint={
              c
                ? `비용률 ${c.cost_ratio ? formatPercentString(c.cost_ratio).replace("+", "") : "—"} · ${c.trade_count}건`
                : "수수료 + 세금"
            }
            onClick={() => setPanel("costs")}
            actionHint="눌러서 매수·매도·종목별 보기"
            loading={costs.isLoading}
          />
          <StatTile
            label={t ? `${t.year} 양도세 (추정)` : "양도세 (추정)"}
            value={formatKrwString(t?.tax_krw)}
            hint={
              t
                ? `양도차익 ${formatKrwCompactString(t.gain_krw)} · 공제 여유 ${formatKrwCompactString(t.headroom_krw)}`
                : "역년 기준 · 신고 자료 아님"
            }
            onClick={() => setPanel("tax")}
            actionHint="눌러서 매도 건별 보기"
            loading={tax.isLoading}
          />
        </div>

        {/* 2행: 월별 막대 두 개. 막대를 누르면 그 달 상세. */}
        <div
          className={cn(
            "grid min-h-0 flex-1 gap-3",
            "grid-cols-1 auto-rows-[minmax(0,1fr)]",
            "lg:auto-rows-auto lg:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]",
          )}
        >
          <StubCard
            title="월별 배당"
            subtitle="막대를 누르면 그 달의 지급 내역"
            action={ranges}
            scrollBody
          >
            {dividends.isLoading ? (
              <CardEmpty text="불러오는 중…" />
            ) : (
              <StackedBarChart
                columns={divColumns}
                colors={colors}
                height={380}
                formatTotal={(v) => formatKrwCompactString(String(v))}
                selected={divMonth}
                onSelect={(key, sticky) => {
                  if (sticky && key) setDivMonth(key);
                }}
              />
            )}
          </StubCard>

          <StubCard
            title="월별 계좌 현금"
            subtitle="배당 − 비용 · 막대를 누르면 그 달의 흐름 전체"
            scrollBody
          >
            {monthly.isLoading ? (
              <CardEmpty text="불러오는 중…" />
            ) : (
              <SignedBarChart
                columns={rows.map((r) => ({
                  key: r.month,
                  label: r.month,
                  value: Number(r.net_cash_generated_krw),
                }))}
                height={380}
                formatValue={(v) => formatKrwSigned(String(Math.round(v)))}
                selected={flowMonth}
                onPick={setFlowMonth}
              />
            )}
          </StubCard>
        </div>
      </PageContainer>

      {/* ── 막대 → 달 상세 ─────────────────────────────────────────────── */}
      <Modal
        open={divPicked != null}
        onClose={() => setDivMonth(null)}
        title={divPicked ? `${divPicked.label} 배당` : ""}
        subtitle={
          divPicked
            ? `${formatKrwString(String(divPicked.total))} · ${divPickedItems.length}건 · 원화 수령액`
            : undefined
        }
        width={620}
      >
        <DataTable
          columns={["지급일", "종목", "금액", "그 달 비중"]}
          align={["left", "left", "right", "right"]}
          empty="이 달에는 수령한 배당이 없습니다"
        >
          {divPickedItems.map((d) => (
            <tr key={d.id} className="border-b border-hairline">
              <Cell left tone="muted">{d.pay_date}</Cell>
              <Cell left strong>
                <span className="flex items-center gap-1.5">
                  <span
                    className="h-2 w-2 shrink-0 rounded-[2px]"
                    style={{ backgroundColor: colors[d.ticker] }}
                  />
                  {d.ticker}
                  <span className="max-w-[180px] truncate text-[10px] font-semibold text-ink-faint">
                    {d.asset_name}
                  </span>
                </span>
              </Cell>
              <Cell strong tone="up">{formatKrwString(d.amount_krw)}</Cell>
              <Cell tone="muted">
                {divPicked && divPicked.total > 0
                  ? `${((Number(d.amount_krw) / divPicked.total) * 100).toFixed(0)}%`
                  : "—"}
              </Cell>
            </tr>
          ))}
        </DataTable>
      </Modal>

      <Modal
        open={flowPicked != null}
        onClose={() => setFlowMonth(null)}
        title={flowPicked ? `${flowPicked.month} 현금흐름` : ""}
        subtitle="세 층을 한 숫자로 합치지 않습니다 — 합치면 뜻이 사라집니다"
        width={620}
      >
        {flowPicked && <MonthBreakdown row={flowPicked} />}
      </Modal>

      {/* ── 요약 칸 → 주제 상세 ─────────────────────────────────────────── */}
      <Modal
        open={panel === "transfers"}
        onClose={() => {
          setPanel(null);
          setTransferMonth(null);
        }}
        title="입출금"
        subtitle={
          cf?.first_date
            ? `${cf.first_date} ~ ${cf.last_date} · 증권사 장부 날짜 그대로`
            : undefined
        }
        width={860}
      >
        <div className="space-y-3">
          <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Figure label="총 입금" value={formatKrwString(cf?.total_deposit_krw)} />
            <Figure label="총 출금" value={formatKrwString(cf?.total_withdrawal_krw)} />
            <Figure label="기간 시작 자산" value={formatKrwString(cf?.opening_balance_krw)} />
            <Figure
              label="금액 증감 (수익률 아님)"
              value={formatKrwSigned(cf?.gain_krw)}
              tone={toneOf(cf?.gain_krw)}
            />
          </dl>
          <SignedBarChart
            columns={transferColumns}
            height={150}
            formatValue={(v) => formatKrwSigned(String(Math.round(v)))}
            selected={transferMonth}
            onPick={(k) => setTransferMonth((prev) => (prev === k ? null : k))}
          />
          <div className="flex items-baseline justify-between">
            <span className="text-[11px] font-bold text-ge-navy">
              {transferMonth ? `${transferMonth} 내역` : "전체 내역"}
            </span>
            {transferMonth && (
              <button
                type="button"
                onClick={() => setTransferMonth(null)}
                className="text-[11px] font-bold text-ge-point hover:text-ink"
              >
                전체 보기
              </button>
            )}
          </div>
          <div className="max-h-[36vh] overflow-y-auto">
            <DataTable
              columns={["날짜", "입금", "출금", "순입출금", "직후 자산"]}
              empty="입출금 내역이 없습니다"
            >
              {transferEvents.map((e) => (
                <tr key={e.base_date} className="border-b border-hairline">
                  <Cell left>
                    {e.base_date}
                    {e.base_date === cf?.first_date && (
                      <span
                        title="기간 첫날의 흐름은 시작 잔고에 들어가 순입출금에서 빠집니다"
                        className="ml-1.5 rounded bg-canvas-soft px-1 py-0.5 text-[9px] font-bold text-ink-muted"
                      >
                        시작 잔고에 포함
                      </span>
                    )}
                  </Cell>
                  <Cell tone={e.deposit_krw ? "up" : "muted"}>{formatKrwString(e.deposit_krw)}</Cell>
                  <Cell tone={e.withdrawal_krw ? "down" : "muted"}>
                    {formatKrwString(e.withdrawal_krw)}
                  </Cell>
                  <Cell strong tone={toneOf(e.net_krw)}>{formatKrwSigned(e.net_krw)}</Cell>
                  <Cell tone="muted">{formatKrwString(e.assets_after_krw)}</Cell>
                </tr>
              ))}
            </DataTable>
          </div>
        </div>
      </Modal>

      <Modal
        open={panel === "dividends"}
        onClose={() => setPanel(null)}
        title="종목별 배당"
        subtitle={
          div?.first_pay_date
            ? `${div.first_pay_date} ~ ${div.last_pay_date} · 수령한 배당(원화)`
            : undefined
        }
        width={760}
      >
        <div className="space-y-3">
          <DonutChart
            slices={byTicker.map<DonutSlice>((x) => ({
              key: x.ticker,
              label: x.ticker,
              value: Number(x.amount_krw),
              caption: `${formatKrwString(x.amount_krw)} · ${x.count}회`,
            }))}
            size={150}
            centerLabel="총 배당"
            centerValue={formatKrwCompactString(div?.total_amount_krw)}
            maxLegend={8}
          />
        </div>
      </Modal>

      <Modal
        open={panel === "generated"}
        onClose={() => setPanel(null)}
        title="월별 현금흐름"
        subtitle={
          m?.first_month ? `${m.first_month} ~ ${m.last_month} · 전부 원화(일별성과 원천)` : undefined
        }
        width={980}
      >
        <div className="max-h-[60vh] overflow-y-auto">
          <DataTable
            columns={["월", "입금", "출금", "배당", "비용", "배당 − 비용", "매수", "매도"]}
            empty="데이터가 없습니다"
          >
            {[...rows].reverse().map((r) => (
              <tr
                key={r.month}
                onClick={() => {
                  setPanel(null);
                  setFlowMonth(r.month);
                }}
                className="cursor-pointer border-b border-hairline transition-colors hover:bg-canvas-soft"
              >
                <Cell left strong>{r.month}</Cell>
                <Cell tone="muted">{formatKrwString(r.deposit_krw)}</Cell>
                <Cell tone="muted">{formatKrwString(r.withdrawal_krw)}</Cell>
                <Cell tone="up">{formatKrwString(r.dividend_krw)}</Cell>
                <Cell tone="down">{formatKrwString(r.cost_krw)}</Cell>
                <Cell strong tone={toneOf(r.net_cash_generated_krw)}>
                  {formatKrwSigned(r.net_cash_generated_krw)}
                </Cell>
                <Cell tone="muted">{formatKrwCompactString(r.buy_krw)}</Cell>
                <Cell tone="muted">{formatKrwCompactString(r.sell_krw)}</Cell>
              </tr>
            ))}
          </DataTable>
        </div>
      </Modal>

      <Modal
        open={panel === "costs"}
        onClose={() => setPanel(null)}
        title="거래비용"
        subtitle={
          c?.first_trade_date
            ? `${c.first_trade_date} ~ ${c.last_trade_date} · USD 그대로 · 비용률 분모는 거래대금`
            : "USD 그대로"
        }
        width={820}
      >
        <div className="space-y-3">
          <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Figure label="거래대금" value={usd(c?.turnover, 0)} />
            <Figure label="수수료" value={usd(c?.commission)} />
            <Figure label="세금" value={usd(c?.tax)} />
            <Figure
              label="비용률"
              value={c?.cost_ratio ? formatPercentString(c.cost_ratio).replace("+", "") : "—"}
            />
          </dl>
          <DataTable columns={["구분", "건수", "거래대금", "수수료", "세금", "비용률"]}>
            {(c?.by_side ?? []).map((s) => (
              <tr key={s.side} className="border-b border-hairline">
                <Cell left strong>{s.side === "BUY" ? "매수" : s.side === "SELL" ? "매도" : s.side}</Cell>
                <Cell tone="muted">{s.trade_count}</Cell>
                <Cell>{usd(s.turnover, 0)}</Cell>
                <Cell>{usd(s.commission)}</Cell>
                <Cell>{usd(s.tax)}</Cell>
                <Cell tone="muted">
                  {s.cost_ratio ? formatPercentString(s.cost_ratio).replace("+", "") : "—"}
                </Cell>
              </tr>
            ))}
          </DataTable>
          <div className="max-h-[32vh] overflow-y-auto">
            <DataTable columns={["종목", "건수", "거래대금", "비용", "비용률"]} empty="체결이 없습니다">
              {(c?.by_ticker ?? []).map((x) => (
                <tr key={x.ticker} className="border-b border-hairline">
                  <Cell left strong>
                    <span className="flex items-center gap-1.5">
                      {x.ticker}
                      <span className="max-w-[180px] truncate text-[10px] font-semibold text-ink-faint">
                        {x.name}
                      </span>
                    </span>
                  </Cell>
                  <Cell tone="muted">{x.trade_count}</Cell>
                  <Cell>{usd(x.turnover, 0)}</Cell>
                  <Cell>{usd(x.cost)}</Cell>
                  <Cell tone="muted">
                    {x.cost_ratio ? formatPercentString(x.cost_ratio).replace("+", "") : "—"}
                  </Cell>
                </tr>
              ))}
            </DataTable>
          </div>
        </div>
      </Modal>

      <Modal
        open={panel === "tax"}
        onClose={() => setPanel(null)}
        title="해외주식 양도소득세 (추정)"
        subtitle="역년 기준 · 신고 자료가 아닙니다"
        width={900}
      >
        <div className="space-y-3">
          <div className="flex gap-1.5">
            {(tax.data?.years ?? []).map((y) => (
              <button
                key={y}
                type="button"
                onClick={() => setTaxYear(y)}
                aria-pressed={t?.year === y}
                className={cn(
                  "rounded-lg border px-2.5 py-1 text-[11px] font-bold transition-colors",
                  t?.year === y
                    ? "border-ge-point bg-ge-blue-bg text-ge-point"
                    : "border-hairline bg-white text-ink-muted hover:bg-canvas-soft",
                )}
              >
                {y}
              </button>
            ))}
          </div>
          <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Figure label="양도차익 (체결일 환율)" value={formatKrwSigned(t?.gain_krw)} tone={toneOf(t?.gain_krw)} />
            <Figure label="기본공제" value={formatKrwString(t?.deduction_krw)} />
            <Figure label="과세표준" value={formatKrwString(t?.taxable_base_krw)} />
            <Figure label="추정 세액" value={formatKrwString(t?.tax_krw)} />
            <Figure label="증권사 기준 차익" value={formatKrwSigned(t?.gain_krw_broker)} />
            <Figure label="두 방식 차이" value={formatKrwSigned(t?.method_diff_krw)} />
            <Figure label="공제까지 여유" value={formatKrwSigned(t?.headroom_krw)} />
            <Figure
              label={`배당소득 (${t?.dividend_count ?? 0}건)`}
              value={formatKrwString(t?.dividend_krw)}
            />
          </dl>
          <div className="max-h-[32vh] overflow-y-auto">
            <DataTable
              columns={["매도일", "종목", "양도가액", "취득가액", "필요경비", "양도차익"]}
              align={["left", "left", "right", "right", "right", "right"]}
              empty="이 해에 매도가 없습니다"
            >
              {(t?.sales ?? []).map((s, i) => (
                <tr key={`${s.sell_date}-${s.ticker}-${i}`} className="border-b border-hairline">
                  <Cell left tone="muted">{s.sell_date}</Cell>
                  <Cell left strong>{s.ticker}</Cell>
                  <Cell>{formatKrwString(s.proceeds_krw)}</Cell>
                  <Cell>{formatKrwString(s.cost_basis_krw)}</Cell>
                  <Cell tone="muted">{formatKrwString(s.expense_krw)}</Cell>
                  <Cell strong tone={toneOf(s.gain_krw)}>{formatKrwSigned(s.gain_krw)}</Cell>
                </tr>
              ))}
            </DataTable>
          </div>
          {(tax.data?.notes ?? []).length > 0 && <PlannedList items={tax.data!.notes} />}
        </div>
      </Modal>
    </>
  );
}

/** 한 달의 흐름을 세 층으로. 옛 월별 현금흐름 화면의 구분을 그대로 쓴다. */
function MonthBreakdown({ row: r }: { row: MonthlyCashflowRow }) {
  const layers: { title: string; note: string; items: [string, string, "up" | "down" | undefined][] }[] = [
    {
      title: "외부 흐름",
      note: "내 지갑 ↔ 계좌",
      items: [
        ["입금", formatKrwString(r.deposit_krw), undefined],
        ["출금", formatKrwString(r.withdrawal_krw), undefined],
        ["순입출금", formatKrwSigned(r.net_flow_krw), toneOf(r.net_flow_krw)],
      ],
    },
    {
      title: "계좌가 만든 현금",
      note: "시장과 무관하게 실제로 생기거나 사라진 돈.",
      items: [
        ["배당", formatKrwString(r.dividend_krw), "up"],
        ["비용", formatKrwString(r.cost_krw), "down"],
        ["배당 − 비용", formatKrwSigned(r.net_cash_generated_krw), toneOf(r.net_cash_generated_krw)],
      ],
    },
    {
      title: "매매 회전",
      note: "계좌 안 현금 ↔ 주식",
      items: [
        ["매수", formatKrwString(r.buy_krw), undefined],
        ["매도", formatKrwString(r.sell_krw), undefined],
        ["손익", formatKrwSigned(r.pnl_krw), toneOf(r.pnl_krw)],
      ],
    },
  ];
  return (
    <div className="space-y-3">
      {layers.map((l) => (
        <section key={l.title} className="rounded-xl bg-canvas-soft/70 p-3">
          <p className="text-[12px] font-extrabold text-ge-navy">
            {l.title}
            <span className="ml-2 text-[11px] font-medium text-ink-muted">{l.note}</span>
          </p>
          <dl className="mt-2 grid grid-cols-3 gap-3">
            {l.items.map(([label, value, tone]) => (
              <Figure key={label} label={label} value={value} tone={tone} />
            ))}
          </dl>
        </section>
      ))}
      <p className="text-[11px] font-medium leading-snug text-ink-muted">
        월초 {formatKrwString(r.opening_assets_krw)} → 월말 {formatKrwString(r.closing_assets_krw)} ·
        설명되지 않는 나머지 <b>{formatKrwSigned(r.unexplained_krw)}</b>
      </p>
    </div>
  );
}

