"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { PageContainer } from "@/components/layout/page-header";
import { Topbar } from "@/components/layout/topbar";
import { useAccount } from "@/components/layout/account-context";
import { SeriesChart } from "@/components/charts/series-chart";
import {
  Cell,
  DataTable,
  NotConnectedBanner,
  PlannedList,
  StatRow,
  StatTile,
  StubCard,
  toneOf,
} from "@/components/stub";
import { getPerformance } from "@/lib/api";
import { formatKrwSigned, formatKrwString } from "@/lib/format";
import { cn } from "@/lib/utils";

// 수익률 추이.
//
// ★2026-09-21: 키움 usa21670(일별계좌수익률현황)에 배선했다. 스냅샷을 쌓는 배치를
//   만들지 않은 이유 — 증권사가 이미 과거 일별 시계열을 들고 있다(실측 531일).
//   우리가 오늘부터 새로 쌓으면 과거가 영영 비어 있게 된다.
//
// ⚠️여기서 TWR/MWR 을 계산해 내보이지 않는다. 제대로 하려면 일별 현금흐름이
//   정확해야 하는데, 지금 있는 것은 입출금 일계(ina_amt/pymn_amt)뿐이라 같은 날
//   입금과 매매가 겹치면 시점 가정이 필요하다. 근거 없는 숫자를 "TWR" 이라고
//   써 붙이면 그 숫자로 판단하게 된다 — 대신 **입출금을 뺀 순수 증감**을 보여준다.

const RANGES = [
  { id: 90, label: "3개월" },
  { id: 180, label: "6개월" },
  { id: 365, label: "1년" },
  { id: 1000, label: "전체" },
];

export default function ReturnsPage() {
  const { accountId, connected } = useAccount();
  const [days, setDays] = useState(365);
  const [metric, setMetric] = useState<"assets" | "cumulative">("assets");

  const perf = useQuery({
    queryKey: ["performance", accountId, days],
    queryFn: () => getPerformance(accountId, days),
    staleTime: 60_000,
  });

  const data = perf.data;
  const items = data?.items ?? [];

  // 원금(순입금) 대비 증감률. 분모가 0이면 계산하지 않는다.
  const netDeposit = Number(data?.net_deposit_krw ?? 0);
  const start = Number(data?.start_assets_krw ?? 0);
  const base = start + netDeposit;
  const gain = data?.gain_krw == null ? null : Number(data.gain_krw);
  const gainRate = gain != null && base > 0 ? (gain / base) * 100 : null;

  // 월별 집계 — 월말 예탁자산과 그 달의 손익 합.
  const monthly = aggregateMonthly(items);

  return (
    <>
      <Topbar title="수익률 추이" subtitle="예탁자산 · 누적손익" />
      <PageContainer wide>
        {!connected && <NotConnectedBanner what="계좌 성과" />}

        <StatRow>
          <StatTile
            label="현재 예탁자산"
            value={formatKrwString(data?.end_assets_krw)}
            hint={data?.last_date ?? undefined}
            loading={perf.isLoading}
          />
          <StatTile
            label="기간 순입금"
            value={formatKrwString(data?.net_deposit_krw)}
            hint="입금 − 출금"
            loading={perf.isLoading}
          />
          <StatTile
            label="입출금 제외 증감"
            value={formatKrwSigned(data?.gain_krw)}
            hint="(끝자산 − 시작자산 − 순입금)"
            accent="auto"
            loading={perf.isLoading}
          />
          <StatTile
            label="원금 대비"
            value={gainRate == null ? undefined : `${gainRate > 0 ? "+" : ""}${gainRate.toFixed(2)}%`}
            hint="증감 ÷ (시작자산 + 순입금)"
            accent="auto"
            loading={perf.isLoading}
          />
        </StatRow>

        <div className="mb-4 flex flex-wrap items-center gap-2">
          {RANGES.map((r) => (
            <Chip key={r.id} active={days === r.id} onClick={() => setDays(r.id)}>
              {r.label}
            </Chip>
          ))}
          <span className="mx-1 h-4 w-px bg-hairline" />
          <Chip active={metric === "assets"} onClick={() => setMetric("assets")}>
            예탁자산
          </Chip>
          <Chip active={metric === "cumulative"} onClick={() => setMetric("cumulative")}>
            누적손익
          </Chip>
          {data?.first_date && (
            <span className="ml-auto text-[11px] font-semibold text-ink-faint">
              {data.first_date} ~ {data.last_date} ({items.length}일)
            </span>
          )}
        </div>

        <div className="grid gap-4 xl:grid-cols-[1.6fr_1fr]">
          <StubCard
            title={metric === "assets" ? "예탁자산 추이" : "누적손익 추이"}
            subtitle={metric === "assets" ? "현금 + 주식 평가" : "증권사 산출 누적손익"}
          >
            {items.length > 0 ? (
              <SeriesChart
                height={280}
                includeZero={metric === "cumulative"}
                points={items.map((p) => {
                  const raw =
                    metric === "assets" ? p.deposit_assets_krw : p.cumulative_pnl_krw;
                  return { date: p.base_date, value: raw == null ? null : Number(raw) };
                })}
                tooltipFormat={(p) =>
                  formatKrwString(p.value == null ? null : String(Math.round(p.value)))
                }
              />
            ) : (
              <div className="flex h-[280px] items-center justify-center text-[12px] font-semibold text-ink-faint">
                {perf.isLoading ? "불러오는 중…" : "데이터가 없습니다"}
              </div>
            )}
          </StubCard>

          <StubCard title="월별" subtitle="월말 자산 · 월 손익 합">
            <DataTable
              columns={["월", "월말 예탁자산", "월 손익"]}
              align={["left", "right", "right"]}
              empty={perf.isLoading ? "불러오는 중…" : "데이터가 없습니다"}
            >
              {monthly.map((m) => (
                <tr
                  key={m.month}
                  className="border-t border-hairline transition-colors hover:bg-canvas-soft/60"
                >
                  <Cell left strong>
                    {m.month}
                  </Cell>
                  <Cell>{formatKrwString(String(Math.round(m.assets)))}</Cell>
                  <Cell tone={toneOf(String(m.pnl))}>
                    {formatKrwSigned(String(Math.round(m.pnl)))}
                  </Cell>
                </tr>
              ))}
            </DataTable>
          </StubCard>

          <StubCard title="여기서 하지 않는 것" className="xl:col-span-2">
            <PlannedList
              items={[
                "TWR/MWR 을 계산해 붙이지 않았다 — 일별 현금흐름의 시점 가정이 필요한데, 지금 있는 건 입출금 일계뿐이다. 근거 없는 숫자에 'TWR' 이름을 붙이면 그걸로 판단하게 된다",
                "벤치마크(KOSPI·S&P500) 비교는 지수 시계열을 붙인 뒤에",
                "리스크 지표(변동성·MDD·샤프)는 일별 수익률이 정확해진 뒤에",
              ]}
            />
          </StubCard>
        </div>
      </PageContainer>
    </>
  );
}

/** 월말 예탁자산과 그 달 손익 합. 최근 달이 위로. */
function aggregateMonthly(items: { base_date: string; deposit_assets_krw: string | null; pnl_krw: string | null }[]) {
  const acc = new Map<string, { month: string; assets: number; pnl: number }>();
  for (const p of items) {
    const month = p.base_date.slice(0, 7);
    const entry = acc.get(month) ?? { month, assets: 0, pnl: 0 };
    // 마지막으로 본 값이 월말 값이다(items 는 날짜 오름차순).
    if (p.deposit_assets_krw != null) entry.assets = Number(p.deposit_assets_krw);
    entry.pnl += Number(p.pnl_krw ?? 0);
    acc.set(month, entry);
  }
  return [...acc.values()].reverse();
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
