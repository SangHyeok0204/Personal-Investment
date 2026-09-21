"use client";

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { PageContainer } from "@/components/layout/page-header";
import { Topbar } from "@/components/layout/topbar";
import { useAccount } from "@/components/layout/account-context";
import {
  Cell,
  DataTable,
  NotConnectedBanner,
  PlannedList,
  StubCard,
  StubChart,
} from "@/components/stub";
import { getPortfolioHoldings } from "@/lib/api";
import { formatKrwString } from "@/lib/format";
import { cn } from "@/lib/utils";

// 섹터/자산 배분.
//
// ★2026-09-21 사용자가 "섹터별 투자 비중"을 모니터링 1순위로 꼽아 제목을 바꾸고
//   섹터를 맨 위로 올렸다. 다만 **섹터는 아직 계산할 수 없다** — 종목→섹터 매핑
//   테이블(alembic 0003 asset_classification)이 비어 있기 때문이다. 그래서 섹터
//   카드는 비워 두고, 지금 데이터로 정직하게 계산되는 **국가·통화 비중은 실제로**
//   그린다. 못 하는 것과 하는 것을 한 화면에서 구분한다.

type Slice = { key: string; label: string; krw: number };

function toSlices(
  items: { market_value_krw: string | null }[],
  keyOf: (h: never) => { key: string; label: string },
): Slice[] {
  const acc = new Map<string, Slice>();
  for (const h of items) {
    const v = h.market_value_krw == null ? 0 : Number(h.market_value_krw);
    if (!Number.isFinite(v) || v === 0) continue;
    const { key, label } = keyOf(h as never);
    const cur = acc.get(key);
    if (cur) cur.krw += v;
    else acc.set(key, { key, label, krw: v });
  }
  return [...acc.values()].sort((a, b) => b.krw - a.krw);
}

/** 가로 막대 비중 표 — 원형 차트보다 값을 읽기 쉽고, 항목이 적을 때 낭비가 없다. */
function WeightBars({ slices }: { slices: Slice[] }) {
  const total = slices.reduce((s, x) => s + x.krw, 0);
  if (total === 0) {
    return (
      <div className="flex h-40 items-center justify-center text-[12px] font-semibold text-ink-faint">
        계좌를 연동하면 비중이 계산됩니다
      </div>
    );
  }
  return (
    <div className="space-y-3">
      {slices.map((s) => {
        const pct = (s.krw / total) * 100;
        return (
          <div key={s.key}>
            <div className="mb-1 flex items-baseline justify-between gap-3">
              <span className="text-[13px] font-extrabold text-ge-navy">
                {s.label}
              </span>
              <span className="text-[12px] font-bold tabular-nums text-ink-secondary">
                {pct.toFixed(1)}%
                <span className="ml-2 font-semibold text-ink-faint">
                  {formatKrwString(String(Math.round(s.krw)))}
                </span>
              </span>
            </div>
            <div className="h-2 w-full overflow-hidden rounded-full bg-canvas-soft">
              <div
                className="h-full rounded-full bg-ge-point"
                style={{ width: `${pct}%` }}
              />
            </div>
          </div>
        );
      })}
    </div>
  );
}

export default function AllocationPage() {
  const { accountId, connected } = useAccount();
  const holdings = useQuery({
    queryKey: ["portfolioHoldings", accountId],
    queryFn: () => getPortfolioHoldings(accountId),
    staleTime: 30_000,
  });

  const items = useMemo(() => holdings.data?.items ?? [], [holdings.data]);

  const byCountry = useMemo(
    () =>
      toSlices(items, (h: { country: string }) => ({
        key: h.country,
        label: h.country === "KR" ? "한국" : h.country === "US" ? "미국" : h.country,
      })),
    [items],
  );
  const byCurrency = useMemo(
    () =>
      toSlices(items, (h: { currency: string }) => ({
        key: h.currency,
        label: h.currency,
      })),
    [items],
  );
  const byTicker = useMemo(
    () =>
      toSlices(items, (h: { ticker: string; name: string | null }) => ({
        key: h.ticker,
        label: h.name ?? h.ticker,
      })),
    [items],
  );

  const total = byTicker.reduce((s, x) => s + x.krw, 0);

  return (
    <>
      <Topbar title="섹터/자산 배분" subtitle="섹터 · 국가 · 통화 · 종목 비중" />
      <PageContainer wide>
        {!connected && <NotConnectedBanner what="보유 종목" />}

        <div className="grid gap-4 xl:grid-cols-2">
          {/* 섹터가 1순위지만 매핑이 없어 아직 계산할 수 없다 — 비워 두고 이유를 적는다. */}
          <StubCard title="섹터 비중" subtitle="종목 → 섹터 매핑 필요">
            <StubChart height={220} note="종목 분류(0003) 미적재 — 섹터를 붙일 수 없습니다" />
            <p className="mt-3 text-[11px] font-medium leading-snug text-ink-faint">
              보유 종목은 읽고 있지만 각 종목이 어느 섹터인지는 아직 모릅니다. 분류
              테이블이 채워지면 아래 국가·통화 비중과 같은 방식으로 바로 그려집니다.
            </p>
          </StubCard>

          <StubCard title="종목 비중" subtitle="평가금액 기준">
            <WeightBars slices={byTicker.slice(0, 8)} />
          </StubCard>

          <StubCard title="국가 비중" subtitle="지금 데이터로 계산됨">
            <WeightBars slices={byCountry} />
          </StubCard>

          <StubCard title="통화 비중" subtitle="환노출 파악용">
            <WeightBars slices={byCurrency} />
          </StubCard>

          <StubCard title="종목 비중 전체" className="xl:col-span-2">
            <DataTable
              columns={["종목", "국가", "통화", "평가금액", "비중"]}
              align={["left", "left", "left", "right", "right"]}
              empty={
                holdings.isLoading ? "불러오는 중…" : "보유 종목이 없습니다"
              }
            >
              {items.map((h) => {
                const v = h.market_value_krw ? Number(h.market_value_krw) : 0;
                return (
                  <tr
                    key={`${h.account_id}-${h.asset_id}`}
                    className="border-t border-hairline transition-colors hover:bg-canvas-soft/60"
                  >
                    <Cell left strong>
                      {h.name ?? h.ticker}
                    </Cell>
                    <Cell left tone="muted">
                      {h.country}
                    </Cell>
                    <Cell left tone="muted">
                      {h.currency}
                    </Cell>
                    <Cell>{formatKrwString(h.market_value_krw)}</Cell>
                    <Cell
                      className={cn(total === 0 && "text-ink-faint")}
                      tone="muted"
                    >
                      {total > 0 ? `${((v / total) * 100).toFixed(1)}%` : "—"}
                    </Cell>
                  </tr>
                );
              })}
            </DataTable>
          </StubCard>

          <StubCard title="다음 단계" className="xl:col-span-2">
            <PlannedList
              items={[
                "종목 분류 적재(alembic 0003) → 섹터 비중이 바로 열린다",
                "목표 비중을 설정하고 이격을 띄워 리밸런싱 판단에 쓰기",
                "섹터 비중과 산업 리서치 학습 진행도를 나란히 보기 — 돈을 넣은 곳부터 공부",
              ]}
            />
          </StubCard>
        </div>
      </PageContainer>
    </>
  );
}
