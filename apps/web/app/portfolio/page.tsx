"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { useAccount } from "@/components/layout/account-context";
import { useLiveQueryOptions } from "@/components/layout/auto-refresh-context";
import { PageContainer } from "@/components/layout/page-header";
import { Topbar } from "@/components/layout/topbar";
import { DonutChart, type DonutSlice } from "@/components/charts/donut-chart";
import { SeriesChart } from "@/components/charts/series-chart";
import { Modal } from "@/components/ui/modal";
import {
  Cell,
  DataTable,
  NotConnectedBanner,
  StatTile,
  StubCard,
  StubChart,
  toneOf,
} from "@/components/stub";
import {
  getLiveQuotes,
  getPerformance,
  getPortfolioAllocation,
  getPortfolioHoldings,
  getPortfolioSummary,
  type AllocationDimension,
  type LiveQuote,
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

// 자산 현황 — **한 화면에 압축**한다(2026-09-21 사용자 지시).
//
// 원칙:
//   · 페이지는 스크롤하지 않는다. 남는 높이를 카드가 나눠 갖고, 넘치는 표는
//     카드 안에서만 스크롤한다.
//   · 한 화면에 들어갈 만큼만 보여주고, **세부는 hover/click 으로 팝업**에서 본다.
//     (평가손익 → 자산 추이 / 도넛 조각·표 행 → 종목 상세)
//   · 숫자는 5초 갱신에 맞춰 자릿수가 굴러 올라간다(StatTile → AnimatedNumber).

// 배분 축. AI/Tech 밸류체인과 전통 섹터는 서로 다른 관점이라 섞지 않고 전환한다.
// ★기본 축은 `exposure` 다(2026-09-21). tech_l1 로 두면 ETF 7종목이 전부 "ETF"
//   한 조각(평가금액의 61.3%)이 되어 섹터 비중을 볼 수 없다. exposure 는 ETF 를
//   **대표 노출 하나**로 바꿔 개별주와 같은 축에 올린다 — 한 ETF 를 구성종목
//   비중으로 쪼개는 투과 배분이 아니다.
//   "ETF" 축을 남겨 둔 이유: 상품 유형별로 보고 싶을 때가 따로 있다.
const AXES: { id: AllocationDimension; label: string; hint: string }[] = [
  { id: "exposure", label: "섹터", hint: "ETF는 대표 노출로 치환" },
  { id: "tech_l1", label: "ETF구분", hint: "ETF를 상품 유형 그대로" },
  { id: "tech_l2", label: "중분류", hint: "AI/Tech 중분류" },
  { id: "country", label: "국가", hint: "상장 국가" },
];

export default function PortfolioPage() {
  const { accountId, connected, isError: accountsError } = useAccount();
  const live = useLiveQueryOptions();
  const [trendOpen, setTrendOpen] = useState(false);
  const [picked, setPicked] = useState<PortfolioHolding | null>(null);
  const [axis, setAxis] = useState<AllocationDimension>("exposure");

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
  // 하루 단위 값이라 5초 폴링에 얹지 않는다.
  const performance = useQuery({
    queryKey: ["performance", accountId, 365],
    queryFn: () => getPerformance(accountId, 365),
    staleTime: 60_000,
  });
  // ★실시간 시세(2026-09-22). 잔고 동기화는 키움 TR 이 무거워 30초 주기인데,
  //   시세만 따로 받으면 5초 주기여도 가볍다(실측 17종목 0.60초 + 서버 4초 캐시).
  //   가격이 30초 동안 멈춰 보이던 문제를 이게 메운다.
  const quotes = useQuery({
    queryKey: ["liveQuotes", accountId],
    queryFn: () => getLiveQuotes(accountId),
    staleTime: 3_000,
    ...live,
  });

  const s = summary.data;
  const rows = holdings.data?.items ?? [];

  // 티커 → 실시간 시세. 못 받은 종목은 여기 없고, 화면은 증권사 값을 그대로 쓴다.
  const liveByTicker = useMemo(() => {
    const map = new Map<string, LiveQuote>();
    for (const q of quotes.data?.items ?? []) map.set(q.ticker, q);
    return map;
  }, [quotes.data]);

  // ⚠️합계는 **실시간으로 전 종목을 다 받았을 때만** 갈아끼운다. 일부만 실시간이면
  //   실시간 값과 증권사 값이 섞여 합계가 어느 시점 것인지 알 수 없어진다.
  const allLive =
    (quotes.data?.missing.length ?? 1) === 0 && liveByTicker.size === rows.length;
  const liveTotalKrw = allLive ? (quotes.data?.total_market_value_krw ?? null) : null;
  const totalKrw = liveTotalKrw ?? holdings.data?.total_market_value_krw ?? null;

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

  const axisSlices: DonutSlice[] = useMemo(
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
      <PageContainer fit>
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

        {/* 1행: 요약 4칸 — 높이 고정 */}
        <div className="grid shrink-0 grid-cols-2 gap-2.5 lg:grid-cols-4">
          <StatTile
            label="총 평가금액"
            value={formatKrwString(s?.total_assets_krw)}
            hint="보유종목 평가액 + 예수금"
            loading={summary.isLoading}
          />
          <StatTile
            label="평가손익"
            value={formatKrwSigned(
              (allLive ? quotes.data?.total_unrealized_pnl_krw : null) ??
                s?.unrealized_pnl_krw,
            )}
            hint={
              s?.unrealized_return != null
                ? `매입원가 대비 ${formatPercentString(s.unrealized_return)}`
                : "매입원가 대비"
            }
            accent="auto"
            loading={summary.isLoading}
            onClick={() => setTrendOpen(true)}
            actionHint="눌러서 자산 추이 보기"
          />
          <StatTile
            label="보유종목 평가액"
            value={formatKrwString(liveTotalKrw ?? s?.securities_value_krw)}
            hint={
              allLive
                ? `${rows.length}종목 · 실시간`
                : s?.position_count
                  ? `${s.position_count}종목`
                  : "보유 종목 평가액"
            }
            loading={summary.isLoading}
          />
          <StatTile
            label="예수금"
            value={formatKrwString(s?.cash_krw)}
            hint={foreignCashHint(s) ?? "주문 가능 금액"}
            loading={summary.isLoading}
          />
        </div>

        {/* 2행: 남는 높이를 셋이 나눠 갖는다 */}
        <div
          className={cn(
            "grid min-h-0 flex-1 gap-3",
            // ⚠️`auto-rows-[minmax(0,1fr)]` 가 핵심이다. 없으면 행이 내용 높이로
            //   자라서 1열일 때 페이지가 넘친다(좁은 창에서 실제로 스크롤이 생겼다).
            //   이걸 주면 남는 높이를 행들이 나눠 갖고, 넘치는 건 카드 안에서 스크롤한다.
            "grid-cols-1 auto-rows-[minmax(0,1fr)]",
            "md:grid-cols-2 lg:auto-rows-auto",
            // 상세 표가 6열이라 좁으면 손익·비중이 잘린다. 도넛 둘을 줄이고 표에 더 준다.
            "lg:grid-cols-[minmax(0,0.78fr)_minmax(0,0.78fr)_minmax(0,1.6fr)]",
          )}
        >
          <StubCard
            title="보유 종목"
            subtitle={totalKrw ? formatKrwString(totalKrw) : "평가금액 비중"}
            scrollBody
          >
            <DonutChart
              slices={holdingSlices}
              size={132}
              maxLegend={5}
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
                ? `미분류 ${formatKrwString(allocation.data.unclassified_market_value_krw)}`
                : undefined
            }
            scrollBody
            action={
              <div className="flex gap-1">
                {AXES.map((a) => (
                  <button
                    key={a.id}
                    type="button"
                    onClick={() => setAxis(a.id)}
                    aria-pressed={axis === a.id}
                    title={a.hint}
                    className={cn(
                      "rounded px-1.5 py-0.5 text-[10px] font-bold transition-colors",
                      axis === a.id
                        ? "bg-white/90 text-ge-header"
                        : "text-white/60 hover:bg-white/15 hover:text-white",
                    )}
                  >
                    {a.label}
                  </button>
                ))}
              </div>
            }
          >
            <DonutChart
              slices={axisSlices}
              size={132}
              maxLegend={5}
              centerLabel={AXES.find((a) => a.id === axis)?.label}
              centerValue={axisSlices.length ? `${axisSlices.length}개` : undefined}
            />
          </StubCard>

          <StubCard title="보유 종목 상세" subtitle="평가금액 순" scrollBody>
            <DataTable
              columns={["종목", "현재가", "당일", "평가금액", "손익", "비중"]}
              align={["left", "right", "right", "right", "right", "right"]}
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
                  live={liveByTicker.get(h.ticker)}
                  totalKrw={totalKrw}
                  onClick={() => setPicked(h)}
                />
              ))}
            </DataTable>
          </StubCard>
        </div>
      </PageContainer>

      <Modal
        open={trendOpen}
        onClose={() => setTrendOpen(false)}
        title="자산 추이"
        subtitle={
          performance.data?.first_date
            ? `${performance.data.first_date} ~ ${performance.data.last_date}`
            : "예탁자산 시계열"
        }
        width={880}
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
            <p className="mt-2 text-[11px] font-medium leading-snug text-ink-muted">
              기간 손익은 (현재 − 시작)이 아니라 <b>순입금을 뺀 값</b>입니다. 그렇게
              하지 않으면 그 사이 입금한 돈이 수익처럼 보입니다.
            </p>
            <Link
              href="/performance/returns"
              className="mt-2 inline-block text-[11px] font-bold text-ge-point hover:text-ink"
            >
              수익률 추이 자세히 →
            </Link>
          </>
        ) : (
          <StubChart
            height={300}
            note={performance.isLoading ? "불러오는 중…" : "계좌 성과 데이터 없음"}
          />
        )}
      </Modal>

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
        <Figure label="평단" value={formatPriceString(h.average_purchase_price, h.currency)} />
        <Figure label="현재가" value={formatPriceString(h.current_price, h.currency)} />
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
      <p className="text-[11px] font-medium leading-snug text-ink-muted">
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
      <dd className="mt-0.5 font-bold text-ink-secondary">{value}</dd>
    </div>
  );
}

function HoldingRow({
  holding: h,
  live,
  totalKrw,
  onClick,
}: {
  holding: PortfolioHolding;
  /** 실시간 시세. 없으면(못 받은 종목) 증권사 값을 그대로 쓴다. */
  live?: LiveQuote;
  totalKrw: string | null;
  onClick: () => void;
}) {
  // 실시간 값이 있으면 그걸, 없으면 증권사 값을 쓴다. 둘 다 없으면 "—".
  const valueKrw = live?.market_value_krw ?? h.market_value_krw;
  const pnlKrw = live?.unrealized_pnl_krw ?? h.unrealized_pnl_krw;
  const weight =
    totalKrw && valueKrw && Number(totalKrw) !== 0
      ? `${((Number(valueKrw) / Number(totalKrw)) * 100).toFixed(1)}%`
      : "—";
  const dayRate = live?.change_rate == null ? null : Number(live.change_rate) * 100;

  return (
    <tr
      onClick={onClick}
      className="cursor-pointer border-b border-hairline transition-colors hover:bg-canvas-soft"
    >
      <Cell left strong>
        <span className="flex items-center gap-1.5">
          <span className="max-w-[150px] truncate">{h.name ?? h.ticker}</span>
          <span className="shrink-0 text-[10px] font-semibold text-ink-muted">
            {h.ticker}
          </span>
        </span>
      </Cell>
      <Cell>
        {live ? (
          <span className="inline-flex items-center gap-1">
            {`$${Number(live.price).toLocaleString("en-US", {
              minimumFractionDigits: 2,
              maximumFractionDigits: 2,
            })}`}
            {/* ⚠️데이마켓 체결가를 정규장 종가인 척 두지 않는다. 값은 버리지
                않는다 — 한국 투자자가 실제로 체결할 수 있는 가격이고, 실측상
                미국 개장 전 방향을 먼저 반영한다(2026-09-22 09:32: 8종목 전부
                같은 방향, 같은 시각 나스닥100 선물 +0.32%). '틀린 값'이 아니라
                '다른 세션의 값'이라 그렇게 적는다. */}
            {live.thin_session && (
              <span
                title={
                  `한국 데이마켓 가격입니다 — 미국 정규장은 마감 중이라 이 값은 개장 전 방향을 먼저 반영합니다.` +
                  (live.volume
                    ? ` 이 봉의 거래량 ${Number(live.volume).toLocaleString("en-US")}주로 정규장보다 훨씬 적으니 정규장 종가와는 다를 수 있습니다.`
                    : "")
                }
                className="shrink-0 cursor-help rounded bg-ge-point/12 px-1 py-0.5 text-[9px] font-extrabold text-ge-point"
              >
                데이
              </span>
            )}
          </span>
        ) : (
          formatPriceString(h.current_price, h.currency)
        )}
      </Cell>
      <Cell tone={dayRate == null ? undefined : dayRate > 0 ? "up" : dayRate < 0 ? "down" : "muted"}>
        {dayRate == null ? "—" : `${dayRate > 0 ? "+" : ""}${dayRate.toFixed(2)}%`}
      </Cell>
      <Cell strong>{formatKrwString(valueKrw)}</Cell>
      <Cell tone={toneOf(pnlKrw)}>{formatKrwSigned(pnlKrw)}</Cell>
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
  return `+ ${parts.join(" · ")} (환율 없음)`;
}
