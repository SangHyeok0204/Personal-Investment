"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { PageContainer } from "@/components/layout/page-header";
import { Topbar } from "@/components/layout/topbar";
import { useAccount } from "@/components/layout/account-context";
import { Modal } from "@/components/ui/modal";
import { colorForKeys } from "@/components/charts/donut-chart";
import { StackedBarChart, type StackColumn } from "@/components/charts/stacked-bar-chart";
import {
  CardEmpty,
  Cell,
  DataTable,
  ListButton,
  NotConnectedBanner,
  StatTile,
  StubCard,
} from "@/components/stub";
import { getDividends } from "@/lib/api";
import { formatKrwCompactString, formatKrwString } from "@/lib/format";
import { cn } from "@/lib/utils";

// 배당 — 내 자산 › 배당.
//
// ★2026-10-01 "매매/현금흐름" 메뉴(체결·실현손익 · 현금유출입)를 걷으면서 두 화면이
//   배당에 대해 보여 주던 것(지급 건별 · 종목별 합계 · 월별 막대)만 여기로 옮겼다.
//
// ⚠️금액은 **세후(원천징수 후)** 다 — 키움 usa21730 이 원천징수 뒤 원화 입금액을 준다
//   (감사로 확인). 세금을 또 빼지 않는다.
// ⚠️배당수익률은 두지 않았다. 주당 배당금도, 지급일 주가도 원장에 없다 — 현재 평가액으로
//   나누면 기간·보유 수량이 다른 두 숫자를 섞은 값이 된다.
// ⚠️조회 하한은 서버가 투자 시작일(INVESTMENT_START)로 막는다 — 3650일을 달라고 해도
//   시작일 앞은 오지 않는다.

const ALL_DAYS = 3650;

export default function DividendsPage() {
  const { accountId, connected } = useAccount();
  const [month, setMonth] = useState<string | null>(null);
  const [listOpen, setListOpen] = useState(false);

  const dividends = useQuery({
    queryKey: ["dividends", accountId, ALL_DAYS],
    queryFn: () => getDividends(accountId, ALL_DAYS),
    staleTime: 60_000,
  });

  const div = dividends.data;
  const items = useMemo(() => div?.items ?? [], [div]);
  const byTicker = useMemo(() => div?.by_ticker ?? [], [div]);
  const total = div?.total_amount_krw != null ? Number(div.total_amount_krw) : null;
  const colors = useMemo(() => colorForKeys(byTicker.map((t) => t.ticker)), [byTicker]);

  // 월 × 종목 누적막대 — 옛 현금유출입 화면과 같은 방식.
  const columns: StackColumn[] = useMemo(() => {
    const names: Record<string, string> = {};
    for (const t of byTicker) names[t.ticker] = t.asset_name ?? t.ticker;
    const buckets = new Map<string, Map<string, number>>();
    for (const d of items) {
      const m = d.pay_date.slice(0, 7);
      const inner = buckets.get(m) ?? new Map<string, number>();
      inner.set(d.ticker, (inner.get(d.ticker) ?? 0) + Number(d.amount_krw));
      buckets.set(m, inner);
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
  }, [div, items, byTicker]);

  const listed = useMemo(
    () => items.filter((d) => (month ? d.pay_date.startsWith(month) : true)),
    [items, month],
  );
  const listedTotal = listed.reduce((sum, d) => sum + Number(d.amount_krw), 0);
  const monthCount = div?.monthly.length ?? 0;
  const top = byTicker[0] ?? null;

  return (
    <>
      <Topbar title="배당" subtitle="세후(원천징수 후) · 투자 시작일부터" />
      <PageContainer fit>
        {!connected && <NotConnectedBanner what="키움 배당 내역" />}

        <div className="grid shrink-0 grid-cols-2 gap-2.5 lg:grid-cols-4">
          <StatTile
            label="배당 합계 (세후)"
            value={formatKrwString(div?.total_amount_krw)}
            hint={
              div?.first_pay_date
                ? `${div.first_pay_date} ~ ${div.last_pay_date} · 원천징수 후`
                : "원천징수 후 수령액"
            }
            accent="up"
            actionHint="눌러서 지급 내역 전체"
            onClick={() => {
              setMonth(null);
              setListOpen(true);
            }}
            loading={dividends.isLoading}
          />
          <StatTile
            label="지급 건수"
            value={div ? `${div.total}건` : undefined}
            hint={div ? `${byTicker.length}종목 · ${monthCount}개월` : "종목 · 개월"}
            loading={dividends.isLoading}
          />
          <StatTile
            label="월 평균 (세후)"
            // 지급이 있었던 달로 나눈다 — 없는 달을 0 으로 세지 않는다.
            value={
              total != null && monthCount > 0
                ? formatKrwString(String(Math.round(total / monthCount)))
                : undefined
            }
            hint="배당이 들어온 달 기준"
            loading={dividends.isLoading}
          />
          <StatTile
            label="가장 많이 준 종목"
            value={top ? top.ticker : undefined}
            hint={
              top && total
                ? `${formatKrwString(top.amount_krw)} · ${((Number(top.amount_krw) / total) * 100).toFixed(0)}%`
                : "종목별 합계 1위"
            }
            loading={dividends.isLoading}
          />
        </div>

        <div
          className={cn(
            "grid min-h-0 flex-1 gap-3",
            // ⚠️1열일 때 행이 내용 높이로 자라 페이지가 넘치지 않게(자산 현황과 같은 규칙).
            "grid-cols-1 auto-rows-[minmax(0,1fr)]",
            "lg:auto-rows-auto lg:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]",
          )}
        >
          <StubCard
            title="월별 배당"
            subtitle="세후 · 막대를 누르면 그 달의 지급 내역"
            action={
              <ListButton
                onClick={() => {
                  setMonth(null);
                  setListOpen(true);
                }}
              />
            }
            scrollBody
          >
            {dividends.isLoading ? (
              <CardEmpty text="불러오는 중…" />
            ) : (
              <StackedBarChart
                columns={columns}
                colors={colors}
                height={300}
                formatTotal={(v) => formatKrwCompactString(String(v))}
                selected={month}
                onSelect={(key, sticky) => {
                  if (sticky && key) {
                    setMonth(key);
                    setListOpen(true);
                  }
                }}
              />
            )}
          </StubCard>

          <div className="grid min-h-0 auto-rows-[minmax(0,1fr)] gap-3">
            <StubCard title="종목별 합계" subtitle="세후 · 금액 순" scrollBody>
              <DataTable
                columns={["종목", "횟수", "합계", "비중"]}
                align={["left", "right", "right", "right"]}
                empty={dividends.isLoading ? "불러오는 중…" : "수령한 배당이 없습니다"}
              >
                {byTicker.map((t) => (
                  <tr key={t.ticker} className="border-b border-hairline">
                    <Cell left strong>
                      <span className="flex items-center gap-1.5">
                        <span
                          className="h-2 w-2 shrink-0 rounded-[2px]"
                          style={{ backgroundColor: colors[t.ticker] }}
                        />
                        {t.ticker}
                        <span className="max-w-[140px] truncate text-[10px] font-semibold text-ink-faint">
                          {t.asset_name}
                        </span>
                      </span>
                    </Cell>
                    <Cell tone="muted">{t.count}회</Cell>
                    <Cell strong tone="up">{formatKrwString(t.amount_krw)}</Cell>
                    <Cell tone="muted">
                      {total ? `${((Number(t.amount_krw) / total) * 100).toFixed(1)}%` : "—"}
                    </Cell>
                  </tr>
                ))}
              </DataTable>
            </StubCard>

            <StubCard title="지급 내역" subtitle="최근순 · 세후" scrollBody>
              <DividendTable rows={items} colors={colors} loading={dividends.isLoading} />
            </StubCard>
          </div>
        </div>
      </PageContainer>

      <Modal
        open={listOpen}
        onClose={() => {
          setListOpen(false);
          setMonth(null);
        }}
        title={month ? `${month} 배당` : "배당 지급 내역 전체"}
        subtitle={`${listed.length}건 · 합계 ${formatKrwString(String(listedTotal))} · 세후(원천징수 후)`}
        width={640}
      >
        <div className="max-h-[60vh] overflow-y-auto">
          <DividendTable rows={listed} colors={colors} loading={false} />
        </div>
      </Modal>
    </>
  );
}

function DividendTable({
  rows,
  colors,
  loading,
}: {
  rows: { id: string; pay_date: string; ticker: string; asset_name: string | null; amount_krw: string }[];
  colors: Record<string, string>;
  loading: boolean;
}) {
  return (
    <DataTable
      columns={["지급일", "종목", "금액(세후)"]}
      align={["left", "left", "right"]}
      empty={loading ? "불러오는 중…" : "수령한 배당이 없습니다"}
    >
      {rows.map((d) => (
        <tr key={d.id} className="border-b border-hairline">
          <Cell left tone="muted">{d.pay_date}</Cell>
          <Cell left strong>
            <span className="flex items-center gap-1.5">
              <span
                className="h-2 w-2 shrink-0 rounded-[2px]"
                style={{ backgroundColor: colors[d.ticker] }}
              />
              {d.ticker}
              <span className="max-w-[140px] truncate text-[10px] font-semibold text-ink-faint">
                {d.asset_name}
              </span>
            </span>
          </Cell>
          <Cell strong tone="up">{formatKrwString(d.amount_krw)}</Cell>
        </tr>
      ))}
    </DataTable>
  );
}
