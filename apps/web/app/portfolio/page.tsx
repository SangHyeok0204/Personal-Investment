"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { ArrowRight } from "lucide-react";
import { PageContainer } from "@/components/layout/page-header";
import { Topbar } from "@/components/layout/topbar";
import { useAccount } from "@/components/layout/account-context";
import { useLiveQueryOptions } from "@/components/layout/auto-refresh-context";
import { SeriesChart } from "@/components/charts/series-chart";
import { DonutChart, type DonutSlice } from "@/components/charts/donut-chart";
import { Modal } from "@/components/ui/modal";
import {
  Cell,
  DataTable,
  NotConnectedBanner,
  StatRow,
  StatTile,
  StubCard,
  StubChart,
  toneOf,
} from "@/components/stub";
import {
  getPerformance,
  getPortfolioAllocation,
  getPortfolioHoldings,
  getPortfolioSummary,
  type AllocationDimension,
  type PortfolioHolding,
  type PortfolioSummary,
} from "@/lib/api";
import {
  formatKrwSigned,
  formatKrwString,
  formatPercentString,
  formatPriceString,
  formatQuantityString,
} from "@/lib/format";
import { cn } from "@/lib/utils";

// 개인 대시보드의 1면 — 자산 현황.
//
// ★2026-09-21 사용자 요청 반영:
//   · 평가손익 카드를 누르면 **자산 추이를 가운데 팝업**으로 크게 본다.
//     (상단 카드 옆의 작은 차트는 "지금 얼마"를 방해하지 않게 유지하고,
//      자세히 볼 때만 팝업을 연다.)
//   · 보유 종목을 **도넛 + 범례**로 보여주고, 조각을 누르면 그 종목 상세가 팝업으로.
//   · 5초마다 화면을 갱신한다(useLiveQueryOptions).

// 배분 축. AI/Tech 밸류체인(L1~L3)과 전통 섹터는 서로 다른 관점이다 —
// 한 도넛에 섞으면 어느 축인지 알 수 없게 된다.
const AXES: { id: AllocationDimension; label: string }[] = [
  { id: "tech_l1", label: "AI/Tech 대분류" },
  { id: "tech_l2", label: "중분류" },
  { id: "sector", label: "전통 섹터" },
  { id: "country", label: "국가" },
];

export default function PortfolioPage() {
  const { accountId, connected, isError: accountsError } = useAccount();
  const live = useLiveQueryOptions();
  const [trendOpen, setTrendOpen] = useState(false);
  const [picked, setPicked] = useState<PortfolioHolding | null>(null);
  // 배분 축 — 전통 섹터와 AI/Tech 밸류체인은 **다른 축**이라 전환해서 본다.
  const [axis, setAxis] = useState<AllocationDimension>("tech_l1");

  const summary = useQuery({
    queryKey: ["portfolioSummary", accountId],
    queryFn: () => getPortfolioSummary(accountId),
    staleTime: 3_000,
    ...live,
  });

  const holdings = useQuery({
    queryKey: ["portfolioHoldings", accountId],
    queryFn: () => getPortfolioHoldings(accountId),
    staleTime: 3_000,
    ...live,
  });

  const allocation = useQuery({
    queryKey: ["portfolioAllocation", axis, accountId],
    queryFn: () => getPortfolioAllocation(axis, accountId),
    staleTime: 3_000,
    ...live,
  });

  // 자산 추이 — 증권사가 들고 있던 과거를 읽는다(우리가 스냅샷을 쌓지 않는다).
  // 이 값은 하루 단위라 5초 폴링에 얹지 않는다.
  const performance = useQuery({
    queryKey: ["performance", accountId, 365],
    queryFn: () => getPerformance(accountId, 365),
    staleTime: 60_000,
  });

  const s = summary.data;
  const rows = holdings.data?.items ?? [];
  const totalKrw = holdings.data?.total_market_value_krw ?? null;
  const loading = summary.isLoading;

  const holdingSlices: DonutSlice[] = useMemo(
    () =>
      rows.map((h) => ({
        key: h.asset_id,
        label: h.name ?? h.ticker,
        value: Number(h.market_value_krw ?? 0),
        caption: formatKrwString(h.market_value_krw),
      })),
    [rows],
  );

  const sectorSlices: DonutSlice[] = useMemo(
    () =>
      (allocation.data?.items ?? []).map((a) => ({
        key: a.key ?? "__none__",
        label: a.label,
        value: Number(a.market_value_krw),
        caption: formatKrwString(a.market_value_krw),
        muted: a.key == null,
      })),
    [allocation.data],
  );

  return (
    <>
      <Topbar title="자산 현황" subtitle="전체 계좌 합산 · 실시간 평가" />
      <PageContainer wide>
        {!connected && (
          <NotConnectedBanner
            what="키움 계좌 API"
            message={
              accountsError
                ? "API 서버에 연결하지 못했습니다 — 백엔드(uvicorn)가 떠 있는지 확인하세요."
                : undefined
            }
          />
        )}

        <StatRow>
          <StatTile
            label="총 평가금액"
            value={formatKrwString(s?.total_assets_krw)}
            hint="보유종목 평가액 + 예수금"
            loading={loading}
          />
          <StatTile
            label="평가손익"
            value={formatKrwSigned(s?.unrealized_pnl_krw)}
            hint={
              s?.unrealized_return != null
                ? `매입원가 대비 ${formatPercentString(s.unrealized_return)}`
                : "매입원가 대비"
            }
            accent="auto"
            loading={loading}
            onClick={() => setTrendOpen(true)}
            actionHint="눌러서 자산 추이 보기"
          />
          <StatTile
            label="보유종목 평가액"
            value={formatKrwString(s?.securities_value_krw)}
            hint={
              s?.position_count ? `${s.position_count}종목` : "보유 종목 평가액"
            }
            loading={loading}
          />
          <StatTile
            label="예수금"
            value={formatKrwString(s?.cash_krw)}
            hint={foreignCashHint(s) ?? "주문 가능 금액"}
            loading={loading}
          />
        </StatRow>

        <div className="grid gap-4 xl:grid-cols-2">
          <StubCard
            title="보유 종목"
            subtitle={
              totalKrw ? `합계 ${formatKrwString(totalKrw)}` : "평가금액 비중"
            }
          >
            <DonutChart
              slices={holdingSlices}
              size={190}
              centerLabel="보유"
              centerValue={rows.length ? `${rows.length}종목` : undefined}
              onSliceClick={(slice) => {
                const found = rows.find((h) => h.asset_id === slice.key);
                if (found) setPicked(found);
              }}
            />
          </StubCard>

          <StubCard
            title="배분"
            subtitle={
              allocation.data?.unclassified_market_value_krw &&
              Number(allocation.data.unclassified_market_value_krw) > 0
                ? `미분류 ${formatKrwString(allocation.data.unclassified_market_value_krw)} 포함`
                : "평가금액(KRW) 기준"
            }
          >
            <div className="mb-2 flex flex-wrap gap-1.5">
              {AXES.map((a) => (
                <button
                  key={a.id}
                  type="button"
                  onClick={() => setAxis(a.id)}
                  aria-pressed={axis === a.id}
                  className={cn(
                    "rounded border px-2 py-0.5 text-[11px] font-bold transition-colors",
                    axis === a.id
                      ? "border-ge-point bg-ge-blue-bg text-ge-point"
                      : "border-hairline bg-white text-ink-muted hover:bg-canvas-soft",
                  )}
                >
                  {a.label}
                </button>
              ))}
            </div>
            <DonutChart
              slices={sectorSlices}
              size={175}
              centerLabel={AXES.find((a) => a.id === axis)?.label}
              centerValue={
                sectorSlices.length ? `${sectorSlices.length}개` : undefined
              }
            />
            <Link
              href="/portfolio/allocation"
              className="mt-2 inline-block text-[11px] font-bold text-ge-point hover:text-ink"
            >
              전체 배분 보기 →
            </Link>
          </StubCard>

          <StubCard
            title="보유 종목 상세"
            subtitle="평가금액 순"
            className="xl:col-span-2"
          >
            <DataTable
              columns={[
                "종목",
                "수량",
                "평단",
                "현재가",
                "평가금액",
                "평가손익",
                "수익률",
                "비중",
              ]}
              align={["left", "right", "right", "right", "right", "right", "right", "right"]}
              empty={
                holdings.isLoading
                  ? "불러오는 중…"
                  : connected
                    ? "보유 종목이 없습니다"
                    : "계좌를 연동하면 보유 종목이 표시됩니다"
              }
            >
              {rows.map((h) => (
                <HoldingRow
                  key={`${h.account_id}-${h.asset_id}`}
                  holding={h}
                  totalKrw={totalKrw}
                  onClick={() => setPicked(h)}
                />
              ))}
            </DataTable>
          </StubCard>
        </div>

        <div className="mt-4">
          <Link
            href="/portfolio/holdings"
            className="group inline-flex items-center gap-2 text-[13px] font-bold text-ge-point transition-colors hover:text-ge-navy"
          >
            보유 종목 전체 보기
            <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" />
          </Link>
        </div>
      </PageContainer>

      {/* 평가손익 카드를 눌러서 여는 자산 추이 */}
      <Modal
        open={trendOpen}
        onClose={() => setTrendOpen(false)}
        title="자산 추이"
        subtitle={
          performance.data?.first_date
            ? `${performance.data.first_date} ~ ${performance.data.last_date}`
            : "예탁자산 시계열"
        }
        width={860}
      >
        {performance.data && performance.data.items.length > 0 ? (
          <>
            <SeriesChart
              height={320}
              points={performance.data.items.map((p) => ({
                date: p.base_date,
                value:
                  p.deposit_assets_krw == null ? null : Number(p.deposit_assets_krw),
              }))}
              tooltipFormat={(p) =>
                formatKrwString(p.value == null ? null : String(Math.round(p.value)))
              }
            />
            {/* ⚠️(끝-시작)을 수익이라 부르지 않는다 — 그 사이 입금이 수익으로 보인다. */}
            <dl className="mt-3 grid grid-cols-2 gap-3 border-t border-hairline pt-3 sm:grid-cols-4">
              <Figure label="시작 자산" value={formatKrwString(performance.data.start_assets_krw)} />
              <Figure label="현재 자산" value={formatKrwString(performance.data.end_assets_krw)} />
              <Figure label="순입금" value={formatKrwString(performance.data.net_deposit_krw)} />
              <Figure
                label="입출금 제외 증감"
                value={formatKrwSigned(performance.data.gain_krw)}
                tone={Number(performance.data.gain_krw ?? 0) >= 0 ? "up" : "down"}
              />
            </dl>
            <p className="mt-2 text-[11px] font-medium leading-snug text-ink-faint">
              기간 손익은 (현재 − 시작)이 아니라 <b>순입금을 뺀 값</b>입니다. 그렇게
              하지 않으면 그 사이 입금한 돈이 수익처럼 보입니다.
            </p>
          </>
        ) : (
          <StubChart
            height={300}
            note={performance.isLoading ? "불러오는 중…" : "계좌 성과 데이터 없음"}
          />
        )}
      </Modal>

      {/* 도넛 조각·표 행을 눌러서 여는 종목 상세 */}
      <Modal
        open={picked != null}
        onClose={() => setPicked(null)}
        title={picked ? (picked.name ?? picked.ticker) : ""}
        subtitle={picked ? `${picked.ticker} · ${picked.market}` : undefined}
        width={560}
      >
        {picked && <HoldingDetail holding={picked} totalKrw={totalKrw} />}
      </Modal>
    </>
  );
}

function Figure({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: "up" | "down";
}) {
  return (
    <div>
      <dt className="text-[11px] font-bold text-ink-muted">{label}</dt>
      <dd
        className={cn(
          "mt-0.5 text-[15px] font-extrabold tabular-nums",
          tone === "up" && "text-bid",
          tone === "down" && "text-ask",
          !tone && "text-ge-navy",
        )}
      >
        {value}
      </dd>
    </div>
  );
}

function HoldingDetail({
  holding: h,
  totalKrw,
}: {
  holding: PortfolioHolding;
  totalKrw: string | null;
}) {
  const weight =
    totalKrw && h.market_value_krw && Number(totalKrw) !== 0
      ? `${((Number(h.market_value_krw) / Number(totalKrw)) * 100).toFixed(1)}%`
      : "—";
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        <Figure label="평가금액" value={formatKrwString(h.market_value_krw)} />
        <Figure
          label="평가손익"
          value={formatKrwSigned(h.unrealized_pnl_krw)}
          tone={toneOf(h.unrealized_pnl_krw)}
        />
        <Figure
          label="수익률"
          value={formatPercentString(h.unrealized_return)}
          tone={toneOf(h.unrealized_return)}
        />
        <Figure label="수량" value={formatQuantityString(h.quantity)} />
        <Figure
          label="평단"
          value={formatPriceString(h.average_purchase_price, h.currency)}
        />
        <Figure
          label="현재가"
          value={formatPriceString(h.current_price, h.currency)}
        />
      </div>
      <dl className="grid grid-cols-2 gap-x-4 gap-y-2 rounded-xl bg-canvas-soft/70 p-3.5 text-[12px] sm:grid-cols-3">
        <Small label="AI/Tech" value={h.tech_l1 ?? "미분류"} />
        <Small label="중분류" value={h.tech_l2 ?? "—"} />
        <Small label="소분류" value={h.tech_l3 ?? "—"} />
        <Small label="전통 섹터" value={h.sector ?? "미분류"} />
        <Small label="비중" value={weight} />
        <Small label="통화" value={h.currency} />
        <Small
          label="적용 환율"
          value={h.currency === "KRW" ? "—" : formatPriceString(h.exchange_rate, "USD")}
        />
        <Small label="계좌" value={h.account_name ?? h.broker_code} />
      </dl>
      <p className="text-[11px] font-medium leading-snug text-ink-faint">
        평가금액의 원화 환산과 적용 환율은 <b>증권사가 준 값</b>입니다 — 화면이 다시
        계산하지 않습니다(그러면 합계와 종목별 수치가 어긋납니다).
      </p>
    </div>
  );
}

function Small({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-[10px] font-bold text-ink-muted">{label}</dt>
      <dd className="mt-0.5 font-bold text-ink">{value}</dd>
    </div>
  );
}

function HoldingRow({
  holding: h,
  totalKrw,
  onClick,
}: {
  holding: PortfolioHolding;
  totalKrw: string | null;
  onClick: () => void;
}) {
  // 비중은 KRW 평가액 기준. 합계를 모르면 계산하지 않는다(빈칸이 거짓말보다 낫다).
  const weight =
    totalKrw && h.market_value_krw && Number(totalKrw) !== 0
      ? `${((Number(h.market_value_krw) / Number(totalKrw)) * 100).toFixed(1)}%`
      : "—";

  return (
    <tr
      onClick={onClick}
      className="cursor-pointer border-t border-hairline transition-colors hover:bg-canvas-soft/60"
    >
      <Cell left strong>
        <span className="flex items-center gap-2">
          {h.name ?? h.ticker}
          <span className="text-[10px] font-semibold text-ink-faint">
            {h.ticker}
          </span>
          {h.currency !== "KRW" && (
            <span className="rounded bg-ge-blue-bg px-1.5 py-0.5 text-[10px] font-bold text-ge-point">
              {h.currency}
            </span>
          )}
        </span>
      </Cell>
      <Cell>{formatQuantityString(h.quantity)}</Cell>
      <Cell>{formatPriceString(h.average_purchase_price, h.currency)}</Cell>
      <Cell>{formatPriceString(h.current_price, h.currency)}</Cell>
      <Cell strong>{formatKrwString(h.market_value_krw)}</Cell>
      <Cell tone={toneOf(h.unrealized_pnl_krw)}>
        {formatKrwSigned(h.unrealized_pnl_krw)}
      </Cell>
      <Cell tone={toneOf(h.unrealized_return)}>
        {formatPercentString(h.unrealized_return)}
      </Cell>
      <Cell tone="muted">{weight}</Cell>
    </tr>
  );
}

/** KRW 합계에 못 들어간 외화 예수금을 한 줄로. 없으면 null. */
function foreignCashHint(s: PortfolioSummary | undefined): string | null {
  if (!s) return null;
  const unconverted = (s.cash_by_currency ?? []).filter(
    (c) => c.currency !== "KRW" && c.krw_value == null,
  );
  if (unconverted.length === 0) {
    return s.available_cash_krw != null
      ? `주문가능 ${formatKrwString(s.available_cash_krw)}`
      : null;
  }
  const parts = unconverted.map(
    (c) => `${c.currency} ${formatQuantityString(c.cash_balance)}`,
  );
  return `+ ${parts.join(" · ")} (환율 없음, 합계 제외)`;
}
