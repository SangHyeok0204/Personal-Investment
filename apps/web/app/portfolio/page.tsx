"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { useAccount } from "@/components/layout/account-context";
import { useLiveQueryOptions } from "@/components/layout/auto-refresh-context";
import { PageContainer } from "@/components/layout/page-header";
import { Topbar } from "@/components/layout/topbar";
import { DonutChart, type DonutSlice } from "@/components/charts/donut-chart";
import { CompareChart } from "@/components/charts/compare-chart";
import { SeriesChart, type SecondarySeries } from "@/components/charts/series-chart";
import { Modal } from "@/components/ui/modal";
import {
  Cell,
  DataTable,
  Figure,
  NotConnectedBanner,
  StatTile,
  StubCard,
  StubChart,
  toneOf,
} from "@/components/stub";
import {
  getLiveQuotes,
  getPerformance,
  getPnlBreakdown,
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

/** 그 축에서 이 종목이 들어가는 조각 키. 서버 /allocation 의 group by 와 같은 값이다
 *  (null = 미분류 조각 "__none__"). */
function axisKeyOf(h: PortfolioHolding, axis: AllocationDimension): string | null {
  switch (axis) {
    case "exposure":
      return h.exposure;
    case "tech_l1":
      return h.tech_l1;
    case "tech_l2":
      return h.tech_l2;
    case "country":
      return h.country;
    default:
      return null;
  }
}

export default function PortfolioPage() {
  const { accountId, connected, isError: accountsError } = useAccount();
  const live = useLiveQueryOptions();
  const [trendOpen, setTrendOpen] = useState(false);
  const [picked, setPicked] = useState<PortfolioHolding | null>(null);
  // 도넛 가운데를 눌러서 여는 두 팝업. 조각 클릭(=picked)과 뜻이 다르다.
  const [holdingsOpen, setHoldingsOpen] = useState(false);
  const [classOpen, setClassOpen] = useState(false);
  // 배분 도넛 조각 → 그 분류에 든 종목 바스켓.
  const [basket, setBasket] = useState<DonutSlice | null>(null);
  const [axis, setAxis] = useState<AllocationDimension>("exposure");
  // 왼쪽 큰 카드의 두 얼굴 — 손익 분해(기본) / 자산 추이(총 평가액).
  const [leftView, setLeftView] = useState<"pnl" | "assets">("pnl");
  // 손익 분해 그래프 구간. ★기본은 '전체' = 투자 시작일(2026-06-01)부터 — 2026-10-01
  //   사용자 결정. 총기간·실현이 그 날 0 에서 출발하는 것이 전체에서만 보인다.
  //   최근 움직임은 30일로 좁혀 본다. 1년은 뺐다 — 시작일이 1년 안이라 전체와 같다.
  const [pnlRange, setPnlRange] = useState<30 | "all">("all");
  // ★2026-10-01 타일 드릴다운 — 실현손익(누적) / 총기간 손익을 일별 그래프 + 분해로.
  //   은퇴한 체결·실현손익 화면의 쓸모 있던 부분(일별 누적 · 건별 목록)이 여기로 왔다.
  const [realizedOpen, setRealizedOpen] = useState(false);
  const [totalOpen, setTotalOpen] = useState(false);

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
  // ★손익 분해(2026-10-01 사용자 정의) — 실현손익(누적)·평가손익·총기간 손익·총 평가액.
  //   그래프 끝점(오늘)이 서버에서 /summary 값으로 채워지므로 5초 갱신에 같이 얹는다.
  const breakdown = useQuery({
    queryKey: ["pnlBreakdown", accountId],
    queryFn: () => getPnlBreakdown(accountId),
    staleTime: 3_000,
    ...live,
  });
  // 실시간 시세(Yahoo/토스) — **종목 행의 현재가·당일 등락 표시에만** 쓴다.
  // ★2026-10-01 사용자 지정: 화면의 금액(평가액·평가손익·비중)은 **키움 한 원천**.
  //   잔고 동기화가 5초마다 ust21070 의 pl_amt_krw(제비용·세금 반영 평가손익)를
  //   갈아 넣으므로, 시세로 다시 계산한 합계를 끼워 넣을 이유가 사라졌다.
  //   ⚠️실측(2026-10-01 13:04 KST, 데이마켓): 키움 현재가는 15초 간격으로 움직였고
  //     (SOXL 154.28→154.40) Yahoo 는 전일 정규장 종가(147.86)에 멈춰 있었다.
  //     시세 합계로 갈아끼우면 오히려 **더 오래된 값**을 보여 주게 된다.
  const quotes = useQuery({
    queryKey: ["liveQuotes", accountId],
    queryFn: () => getLiveQuotes(accountId),
    staleTime: 3_000,
    ...live,
  });

  const s = summary.data;
  const rows = holdings.data?.items ?? [];

  // 티커 → 실시간 시세. 행의 현재가·당일 칸만 쓴다(못 받은 종목은 증권사 현재가).
  const liveByTicker = useMemo(() => {
    const map = new Map<string, LiveQuote>();
    for (const q of quotes.data?.items ?? []) map.set(q.ticker, q);
    return map;
  }, [quotes.data]);

  // ★합계·비중은 증권사 값만 쓴다(위 quotes 주석 참고). 실시간 합계로 갈아끼우던
  //   분기(allLive)는 지웠다 — 한 칸이 두 원천을 오가면 숫자가 왜 뛰는지 설명할 수 없다.
  const stockKrw = holdings.data?.total_market_value_krw ?? s?.securities_value_krw ?? null;
  const cashKrw = s?.cash_krw ?? null;

  // ★2026-09-22 사용자 지정: **자산 = 주식 평가액 + 예수금.** 비중의 분모도
  //   같은 총자산이다.
  //   ⚠️여기만 주식만으로 나누면 같은 종목이 이 화면 20.9%, 리밸런싱 20.1% 로
  //     갈린다(실측). 사용자는 그걸 버그로 읽는다.
  const totalKrw =
    stockKrw != null && cashKrw != null
      ? String(Number(stockKrw) + Number(cashKrw))
      : stockKrw;

  // ★평가손익의 값과 비율은 **증권사(키움) 한 원천**이다 — /summary 가 더한
  //   pl_amt_krw 와 그 매입원가 대비 비율. 제비용·세금은 증권사가 이미 반영했다.
  const pnlKrw = s?.unrealized_pnl_krw ?? null;
  const pnlRate =
    s?.unrealized_return != null ? formatPercentString(s.unrealized_return) : null;

  // 실현손익(누적)은 원장 값(/realized 와 같은 식·같은 시작일 — 투자 시작일부터).
  // 총기간 손익은 **화면에서** 실현 + 평가 − 시작 시점 평가로 만든다 — 서버의 오늘 점
  // 규칙과 같은 식이라, 두 질의가 5초 갱신 사이에 엇갈려 와도 타일 셋이
  // "총기간 − 실현 = 평가 − 시작 평가" 를 늘 지킨다. 시작 평가를 모르면 총기간도 모른다.
  const realizedKrw = breakdown.data?.realized_cum_krw ?? null;
  const pnlStart = breakdown.data?.start ?? null;
  // 타일 설명용 짧은 날짜("6/01").
  const pnlStartShort = pnlStart ? `${Number(pnlStart.slice(5, 7))}/${pnlStart.slice(8, 10)}` : null;
  const unrealizedAtStart = breakdown.data?.unrealized_at_start_krw ?? null;
  const totalPeriodKrw =
    realizedKrw != null && pnlKrw != null && unrealizedAtStart != null
      ? String(Number(realizedKrw) + Number(pnlKrw) - Number(unrealizedAtStart))
      : null;

  // ⚠️조각도 **오른쪽 표와 같은 값**을 써야 한다. 분자(조각)와 분모(totalKrw)가
  //   다른 원천이면 같은 화면에서 SOXL 이 도넛 19.9% · 표 20.5% 로 갈리고(실측)
  //   비중 합도 100% 가 안 된다. 둘 다 증권사 값이다.
  const holdingSlices: DonutSlice[] = useMemo(() => {
    const slices = rows.map((h) => {
      const valueKrw = h.market_value_krw;
      return {
        key: h.asset_id,
        // 범례 폭을 아끼려고 이름 대신 티커로 적는다(2026-09-25 사용자 지시).
        label: h.ticker,
        value: Number(valueKrw ?? 0),
        caption: formatKrwString(valueKrw),
      };
    });
    // 분모에만 더하고 조각에서 빼면 비중 합이 100% 가 안 된다 — 현금도 넣는다.
    if (cashKrw != null && Number(cashKrw) > 0) {
      slices.push({
        key: "__cash__",
        label: "예수금",
        value: Number(cashKrw),
        caption: formatKrwString(cashKrw),
      });
    }
    return slices;
  }, [rows, cashKrw]);

  // 자산 추이 — 총 평가금액(왼쪽 축) + 누적 손익(오른쪽 축). 카드와 팝업이 같이 쓴다.
  const trendPoints = useMemo(
    () =>
      (performance.data?.items ?? []).map((p) => ({
        date: p.base_date,
        value: p.deposit_assets_krw == null ? null : Number(p.deposit_assets_krw),
      })),
    [performance.data],
  );
  const trendPnl: SecondarySeries = useMemo(
    () => ({
      label: "누적 손익",
      values: (performance.data?.items ?? []).map((p) =>
        p.cumulative_pnl_krw == null ? null : Number(p.cumulative_pnl_krw),
      ),
      tooltipFormat: (v) => formatKrwSigned(String(Math.round(v))),
    }),
    [performance.data],
  );

  // 손익 분해 그래프 — 총기간 손익·실현손익·평가손익을 **한 축**에 둔다. 총기간·실현은
  // 시작일에 0 에서 출발하고, 평가손익은 보유분 수준이라 시작 시점 평가손익에서
  // 출발한다(평가 − 총기간 = 시작 평가 − 실현). 과거 평가손익은 **역산한 값**이고(서버
  // 독스트링), 오늘 점만 키움 실제 평가손익이다 — 그래서 끝점이 타일과 같다.
  const pnlItems = useMemo(() => {
    const items = breakdown.data?.items ?? [];
    return pnlRange === "all" ? items : items.slice(-pnlRange);
  }, [breakdown.data, pnlRange]);
  const pnlDates = useMemo(() => pnlItems.map((p) => p.date), [pnlItems]);
  const pnlSeries = useMemo(() => {
    const items = pnlItems;
    const num = (v: string | null) => (v == null ? null : Number(v));
    return [
      { name: "총기간 손익", emphasis: true, values: items.map((p) => num(p.total_period_pnl_krw)) },
      { name: "평가손익", values: items.map((p) => num(p.unrealized_krw)) },
      { name: "실현손익(누적)", values: items.map((p) => num(p.realized_cum_krw)) },
    ];
  }, [pnlItems]);

  // 드릴다운 그래프 — 구간을 자르지 않고 시작일부터 전부. 서버 값을 그대로 쓴다.
  //   실현 = 매매(비용 뺀 뒤) + 배당(세후·원천징수 뒤). 배당에서 세금을 또 빼지 않는다.
  const allDates = useMemo(() => (breakdown.data?.items ?? []).map((p) => p.date), [breakdown.data]);
  const realizedSeries = useMemo(() => {
    const items = breakdown.data?.items ?? [];
    return [
      { name: "실현손익(누적)", emphasis: true, values: items.map((p) => numOrNull(p.realized_cum_krw)) },
      { name: "주식 실현(매매)", values: items.map((p) => numOrNull(p.realized_trading_cum_krw)) },
      { name: "배당(세후)", values: items.map((p) => numOrNull(p.realized_dividend_cum_krw)) },
    ];
  }, [breakdown.data]);
  // 총기간 = 실현(누적) + (평가손익 − 시작 시점 평가손익). 시작 평가를 모르면 둘째 항도 모른다.
  const totalSeries = useMemo(() => {
    const items = breakdown.data?.items ?? [];
    const base = numOrNull(breakdown.data?.unrealized_at_start_krw ?? null);
    return [
      { name: "총기간 손익", emphasis: true, values: items.map((p) => numOrNull(p.total_period_pnl_krw)) },
      { name: "실현(누적)", values: items.map((p) => numOrNull(p.realized_cum_krw)) },
      {
        name: `평가손익 − ${pnlStartShort ?? "시작"} 평가손익`,
        values: items.map((p) => {
          const u = numOrNull(p.unrealized_krw);
          return u == null || base == null ? null : u - base;
        }),
      },
    ];
  }, [breakdown.data, pnlStartShort]);
  // 타일과 같은 값으로 쓰는 둘째 항(평가손익은 /summary 그대로) — 합이 타일과 똑같다.
  const unrealizedDeltaKrw =
    pnlKrw != null && unrealizedAtStart != null
      ? String(Number(pnlKrw) - Number(unrealizedAtStart))
      : null;

  // 조각 하나에 든 종목들. ⚠️값은 **동기화 스냅샷**(market_value_krw)으로 낸다 —
  //   배분 카드가 그 기준이라, 실시간 값을 쓰면 바스켓 합이 조각 금액과 어긋난다.
  const basketRows = useMemo(() => {
    if (!basket) return [];
    const key = basket.key === "__none__" ? null : basket.key;
    return rows
      .filter((h) => h.market_value_krw != null && axisKeyOf(h, axis) === key)
      .sort((a, b) => Number(b.market_value_krw) - Number(a.market_value_krw));
  }, [basket, rows, axis]);
  const basketTotal = basketRows.reduce((sum, h) => sum + Number(h.market_value_krw), 0);

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
                ? "API 서버에 연결하지 못했습니다"
                : undefined
            }
          />
        )}

        {/* 1행: 요약 6칸 — 높이 고정.
            ★2026-10-01 사용자 정의로 손익을 셋으로 가른다: 실현(누적) + 평가 = 총기간.
              뒤의 셋은 계좌 가치다: 총 평가액 = 보유종목 평가액 + 예수금. */}
        <div className="grid shrink-0 grid-cols-2 gap-2.5 sm:grid-cols-3 xl:grid-cols-6">
          <StatTile
            label="실현손익(누적)"
            value={formatKrwSigned(realizedKrw)}
            // ⚠️칸이 좁아(1280 폭에서 17자 남짓) 날짜·정의는 왼쪽 카드 부제와 아래 숫자에 둔다.
            hint={`${pnlStartShort ?? "시작일"}부터 · 매도+세후배당`}
            accent="auto"
            loading={breakdown.isLoading}
            onClick={() => setRealizedOpen(true)}
            actionHint="눌러서 일별 추이·건별 보기"
          />
          <StatTile
            label="평가손익"
            value={formatKrwSigned(pnlKrw)}
            hint={
              pnlRate != null
                ? `보유분 · 원가 대비 ${pnlRate}`
                : "보유분 · 키움 기준"
            }
            accent="auto"
            loading={summary.isLoading}
            onClick={() => setTrendOpen(true)}
            // ⚠️추이 그래프는 이제 왼쪽 카드에 늘 떠 있다. 팝업이 더 주는 것은
            //   **순입금을 뺀 기간 손익**이다 — 그걸 적어야 눌러 볼 이유가 된다.
            actionHint="눌러서 기간 손익 보기"
          />
          <StatTile
            label="총기간 손익"
            value={formatKrwSigned(totalPeriodKrw)}
            hint={`${pnlStartShort ?? "시작일"}부터 · 일별 손익 누적`}
            accent="auto"
            loading={summary.isLoading || breakdown.isLoading}
            onClick={() => setTotalOpen(true)}
            actionHint="눌러서 일별 추이·분해 보기"
          />
          {/* 부제의 "보유종목 + 예수금" 이 늘 성립하도록 같은 stockKrw 로 만든
              totalKrw 를 쓴다(둘 다 키움 5초 동기화 값). ⚠️실현손익을 더하지 않는다
              — 판 돈은 이미 예수금 안에 있다. */}
          <StatTile
            label="총 평가액"
            value={formatKrwString(totalKrw)}
            hint="보유종목 평가액 + 예수금"
            loading={summary.isLoading}
          />
          <StatTile
            label="보유종목 평가액"
            value={formatKrwString(stockKrw)}
            hint={s?.position_count ? `${s.position_count}종목` : "보유 종목 평가액"}
            loading={summary.isLoading}
          />
          <StatTile
            label="예수금"
            value={formatKrwString(s?.cash_krw)}
            hint={foreignCashHint(s) ?? "주문 가능 금액"}
            loading={summary.isLoading}
          />
        </div>

        {/* 2행: 왼쪽 자산 추이 + 오른쪽 도넛 둘 (2026-09-23 사용자 지시).
            ★[보유 종목 상세] 표는 **화면에서 뺐다.** 도넛 가운데를 누르면 팝업으로
              뜬다 — 좁은 칸에 6열을 우겨넣어 손익·비중이 잘리던 것을, 넓은 팝업에서
              매입 평단까지 붙여 보여 주는 쪽으로 바꿨다. */}
        <div
          className={cn(
            "grid min-h-0 flex-1 gap-3",
            // ⚠️`auto-rows-[minmax(0,1fr)]` 가 핵심이다. 없으면 행이 내용 높이로
            //   자라서 1열일 때 페이지가 넘친다(좁은 창에서 실제로 스크롤이 생겼다).
            "grid-cols-1 auto-rows-[minmax(0,1fr)]",
            "lg:auto-rows-auto lg:grid-cols-[minmax(0,1.25fr)_minmax(0,1fr)]",
          )}
        >
          {/* ★2026-10-01: 왼쪽 카드를 '손익 분해'(기본)와 '자산 추이'(총 평가액) 둘로.
              카드를 하나 더 얹으면 한 화면 원칙이 깨진다 — 같은 자리에서 전환한다. */}
          <StubCard
            title={leftView === "pnl" ? "손익 분해" : "자산 추이"}
            subtitle={
              leftView === "pnl"
                ? `${pnlStart ?? "시작일"}부터 · 총기간·실현은 0에서 누적 · 평가손익은 보유분 실제 수준`
                : performance.data?.first_date
                  ? `${performance.data.first_date} ~ ${performance.data.last_date}`
                  : "예탁자산 시계열"
            }
            scrollBody
            action={
              <div className="flex gap-1">
                {(
                  [
                    { id: "pnl", label: "손익 분해", hint: "총기간 손익 · 평가손익 · 실현손익(누적)" },
                    { id: "assets", label: "자산 추이", hint: "총 평가액(주식 + 예수금) 일별" },
                  ] as const
                ).map((v) => (
                  <button
                    key={v.id}
                    type="button"
                    onClick={() => setLeftView(v.id)}
                    aria-pressed={leftView === v.id}
                    title={v.hint}
                    className={cn(
                      "rounded px-1.5 py-0.5 text-[10px] font-bold transition-colors",
                      leftView === v.id
                        ? "bg-white/90 text-ge-header"
                        : "text-white/60 hover:bg-white/15 hover:text-white",
                    )}
                  >
                    {v.label}
                  </button>
                ))}
              </div>
            }
          >
            {leftView === "pnl" ? (
              breakdown.data && breakdown.data.items.length > 0 ? (
                <div className="flex flex-col gap-3">
                  <div className="flex items-center justify-between">
                    <span className="text-[11px] font-bold text-ink-muted">
                      {pnlDates.length ? `${pnlDates[0]} ~ ${pnlDates[pnlDates.length - 1]}` : ""}
                    </span>
                    <div className="flex gap-1">
                      {(["all", 30] as const).map((r) => (
                        <button
                          key={r}
                          type="button"
                          onClick={() => setPnlRange(r)}
                          aria-pressed={pnlRange === r}
                          className={cn(
                            "rounded px-1.5 py-0.5 text-[10px] font-bold transition-colors",
                            pnlRange === r
                              ? "bg-ge-header text-white"
                              : "text-ink-muted hover:bg-canvas-soft hover:text-ink",
                          )}
                        >
                          {r === "all" ? "전체" : `${r}일`}
                        </button>
                      ))}
                    </div>
                  </div>
                  <CompareChart
                    height={300}
                    dates={pnlDates}
                    series={pnlSeries}
                    valueFormat={compactKrw}
                    legendFormat={(v) => formatKrwSigned(String(Math.round(v)))}
                  />
                  {/* 실현손익이 무엇으로 이루어졌나 — 타일에 다 못 적는 정의를 여기 둔다. */}
                  <dl className="grid grid-cols-2 gap-3 border-t border-hairline pt-3 sm:grid-cols-4">
                    <Figure
                      label="매매 실현(비용 뺀 뒤)"
                      value={formatKrwSigned(breakdown.data.realized_trading_krw)}
                      tone={toneOf(breakdown.data.realized_trading_krw)}
                    />
                    <Figure
                      label="배당(원천징수 뒤)"
                      value={formatKrwSigned(breakdown.data.dividend_krw)}
                      tone={toneOf(breakdown.data.dividend_krw)}
                    />
                    {/* 평가손익은 0 에서 출발하지 않는다 — 시작 시점 수준을 적어 두어야
                        "총기간 − 실현 = 평가 − 이 값" 이 화면에서 읽힌다. */}
                    <Figure
                      label={`${pnlStartShort ?? "시작"} 시점 평가손익`}
                      value={formatKrwSigned(unrealizedAtStart)}
                      tone={toneOf(unrealizedAtStart)}
                    />
                    {/* 과거 평가손익은 역산이다(키움 일별 손익이 있는 마지막 날까지) —
                        시작 시점 평가손익 + 총기간 − 실현. 오늘 점만 키움 실제 평가손익. */}
                    <Figure
                      label={
                        breakdown.data.daily_pnl_until
                          ? `과거 평가손익(~${breakdown.data.daily_pnl_until.slice(5)})`
                          : "과거 평가손익"
                      }
                      value="시작+총기간−실현"
                    />
                  </dl>
                </div>
              ) : (
                <StubChart
                  height={240}
                  note={breakdown.isLoading ? "불러오는 중…" : "손익 데이터 없음"}
                />
              )
            ) : performance.data && performance.data.items.length > 0 ? (
              <SeriesChart
                height={260}
                points={trendPoints}
                label="총 평가금액"
                secondary={trendPnl}
                tooltipFormat={(p) =>
                  formatKrwString(p.value == null ? null : String(Math.round(p.value)))
                }
              />
            ) : (
              <StubChart
                height={240}
                note={performance.isLoading ? "불러오는 중…" : "계좌 성과 데이터 없음"}
              />
            )}
          </StubCard>

          {/* 오른쪽 칸을 둘이 나눠 갖는다. 바깥 그리드의 한 칸이라 여기서 다시 쪼갠다. */}
          <div className="grid min-h-0 auto-rows-[minmax(0,1fr)] gap-3">
            <StubCard
              title="보유 종목"
              subtitle={totalKrw ? `${formatKrwString(totalKrw)} · 예수금 포함` : "총자산 비중"}
              scrollBody
            >
              <DonutChart
                slices={holdingSlices}
                size={132}
                maxLegend={10}
                legendColumns={2}
                compactLegend
                centerLabel="자산"
                // ⚠️"17종목"이라고만 쓰면 예수금 조각이 어디서 왔는지 모른다.
                centerValue={
                  rows.length
                    ? `${rows.length}종목${cashKrw && Number(cashKrw) > 0 ? " + 현금" : ""}`
                    : undefined
                }
                centerHint="눌러서 전체 보기"
                onCenterClick={() => setHoldingsOpen(true)}
                // 조각은 '그 종목 하나', 가운데는 '전부'다.
                onSliceClick={(slice) => {
                  const found = rows.find((h) => h.asset_id === slice.key);
                  if (found) setPicked(found);
                }}
              />
            </StubCard>

            {/* ⚠️이 카드만 **마지막 동기화 기준**이다. 왼쪽 도넛은 실시간 시세로
                갈아끼우는데, 배분은 /allocation 이 주는 스냅샷을 쓴다(리밸런싱·자산
                현황과 분모를 맞춰 둔 값이라 여기만 실시간으로 바꾸면 그쪽이
                어긋난다). 기준이 다르면 화면에 적는다. */}
            <StubCard
              title="배분"
              subtitle={
                allocation.data?.unclassified_market_value_krw &&
                Number(allocation.data.unclassified_market_value_krw) > 0
                  ? `마지막 동기화 기준 · 미분류 ${formatKrwString(allocation.data.unclassified_market_value_krw)}`
                  : "마지막 동기화 기준"
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
                compactLegend
                centerLabel={AXES.find((a) => a.id === axis)?.label}
                centerValue={axisSlices.length ? `${axisSlices.length}개` : undefined}
                centerHint="눌러서 분류 보기"
                onCenterClick={() => setClassOpen(true)}
                // 조각은 '그 분류에 든 종목들'. 예수금 조각은 종목이 없어 열지 않는다.
                onSliceClick={(slice) => {
                  const key = slice.key === "__none__" ? null : slice.key;
                  if (rows.some((h) => axisKeyOf(h, axis) === key)) setBasket(slice);
                }}
              />
            </StubCard>
          </div>
        </div>
      </PageContainer>

      <Modal
        open={trendOpen}
        onClose={() => setTrendOpen(false)}
        title="자산 추이와 기간 손익"
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
              points={trendPoints}
              label="총 평가금액"
              secondary={trendPnl}
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

      {/* 실현손익(누적) 타일 → 일별 누적(매매 · 배당 · 합) + 건별 목록. */}
      <Modal
        open={realizedOpen}
        onClose={() => setRealizedOpen(false)}
        title="실현손익(누적) 일별 추이"
        subtitle={`${pnlStart ?? "시작일"}부터 · 매매는 수수료·세금 뺀 뒤 · 배당은 세후(원천징수 후)`}
        width={940}
      >
        {breakdown.data && allDates.length > 0 ? (
          <div className="space-y-3">
            <CompareChart
              height={260}
              dates={allDates}
              series={realizedSeries}
              valueFormat={compactKrw}
              legendFormat={(v) => formatKrwSigned(String(Math.round(v)))}
            />
            <dl className="grid grid-cols-3 gap-3 border-t border-hairline pt-3">
              <Figure
                label="주식 실현(매매)"
                value={formatKrwSigned(breakdown.data.realized_trading_krw)}
                tone={toneOf(breakdown.data.realized_trading_krw)}
              />
              <Figure
                label="배당(세후)"
                value={formatKrwSigned(breakdown.data.dividend_krw)}
                tone={toneOf(breakdown.data.dividend_krw)}
              />
              <Figure
                label="합계 = 타일"
                value={formatKrwSigned(realizedKrw)}
                tone={toneOf(realizedKrw)}
              />
            </dl>
            <div className="max-h-[30vh] overflow-y-auto">
              <DataTable
                columns={["날짜", "종목", "구분", "금액"]}
                align={["left", "left", "left", "right"]}
                empty="시작일 이후 매도·배당이 없습니다"
              >
                {breakdown.data.events.map((e, i) => (
                  <tr key={`${e.date}-${e.kind}-${e.ticker}-${i}`} className="border-b border-hairline">
                    <Cell left tone="muted">{e.date}</Cell>
                    <Cell left strong>
                      <span className="flex items-center gap-1.5">
                        <span>{e.ticker}</span>
                        <span className="max-w-[220px] truncate text-[10px] font-semibold text-ink-faint">
                          {e.asset_name}
                        </span>
                      </span>
                    </Cell>
                    <Cell left>
                      <span
                        className={cn(
                          "rounded px-1.5 py-0.5 text-[10px] font-bold",
                          e.kind === "trade" ? "bg-ask-soft text-ask" : "bg-bid-soft text-bid",
                        )}
                      >
                        {e.kind === "trade" ? "매매" : "배당"}
                      </span>
                    </Cell>
                    {/* 매매 금액을 모르는 행은 "—" — 0 으로 적지 않는다. */}
                    <Cell strong tone={toneOf(e.amount_krw)}>{formatKrwSigned(e.amount_krw)}</Cell>
                  </tr>
                ))}
              </DataTable>
            </div>
          </div>
        ) : (
          <StubChart height={260} note={breakdown.isLoading ? "불러오는 중…" : "손익 데이터 없음"} />
        )}
      </Modal>

      {/* 총기간 손익 타일 → 일별 총기간 손익 + 분해(실현 누적 · 평가손익 − 시작 평가손익). */}
      <Modal
        open={totalOpen}
        onClose={() => setTotalOpen(false)}
        title="총기간 손익 일별 추이"
        subtitle={`${pnlStart ?? "시작일"}부터 · 총기간 = 실현(누적) + (평가손익 − ${pnlStartShort ?? "시작"} 평가손익)`}
        width={940}
      >
        {breakdown.data && allDates.length > 0 ? (
          <div className="space-y-3">
            <CompareChart
              height={280}
              dates={allDates}
              series={totalSeries}
              valueFormat={compactKrw}
              legendFormat={(v) => formatKrwSigned(String(Math.round(v)))}
            />
            <dl className="grid grid-cols-2 gap-3 border-t border-hairline pt-3 sm:grid-cols-4">
              <Figure label="실현(누적)" value={formatKrwSigned(realizedKrw)} tone={toneOf(realizedKrw)} />
              <Figure
                label={`평가손익 − ${pnlStartShort ?? "시작"} 평가손익`}
                value={formatKrwSigned(unrealizedDeltaKrw)}
                tone={toneOf(unrealizedDeltaKrw)}
              />
              <Figure
                label="총기간 손익 = 타일"
                value={formatKrwSigned(totalPeriodKrw)}
                tone={toneOf(totalPeriodKrw)}
              />
              <Figure
                label={`${pnlStartShort ?? "시작"} 시점 평가손익`}
                value={formatKrwSigned(unrealizedAtStart)}
                tone={toneOf(unrealizedAtStart)}
              />
            </dl>
            <p className="text-[11px] leading-snug text-ink-muted">
              과거 평가손익은 역산 값입니다(키움 일별 손익이 있는 마지막 날
              {breakdown.data.daily_pnl_until ? ` ${breakdown.data.daily_pnl_until}` : ""}까지 — 시작
              평가 + 총기간 − 실현). 오늘 점만 키움 실제 평가손익이라, 마지막 일별 행과 오늘 사이에
              계단이 생길 수 있습니다.
            </p>
          </div>
        ) : (
          <StubChart height={280} note={breakdown.isLoading ? "불러오는 중…" : "손익 데이터 없음"} />
        )}
      </Modal>

      {/* 보유 종목 도넛 가운데 → 전체 상세. 화면에서 뺀 표가 여기로 왔다.
          ⚠️좁은 칸이 아니라 팝업이라 **매입 평단**을 컬럼으로 넣을 수 있다
            (2026-09-23 사용자 요청). 인라인 표에서는 6열도 잘렸다. */}
      <Modal
        open={holdingsOpen}
        onClose={() => setHoldingsOpen(false)}
        title="보유 종목 상세"
        subtitle={
          totalKrw
            ? `${rows.length}종목 · 평가금액 순 · 비중은 총자산(${formatKrwString(totalKrw)}) 기준`
            : "평가금액 순"
        }
        width={980}
      >
        <DataTable
          columns={[
            "종목", "수량", "매입 평단", "현재가", "당일", "평가금액", "손익", "비중",
          ]}
          align={[
            "left", "right", "right", "right", "right", "right", "right", "right",
          ]}
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
      </Modal>

      {/* 배분 도넛 가운데 → 종목별 분류표. "이 조각이 왜 이 조각인지"를 답한다. */}
      <Modal
        open={classOpen}
        onClose={() => setClassOpen(false)}
        title="종목별 분류"
        subtitle={`${rows.length}종목 · 평가금액 순`}
        width={980}
      >
        <DataTable
          columns={["종목", "대분류", "중분류", "소분류", "전통 섹터", "국가", "비중"]}
          align={[
            "left", "left", "left", "left", "left", "left", "right",
          ]}
          empty={
            holdings.isLoading ? "불러오는 중…" : "보유 종목이 없습니다"
          }
        >
          {rows.map((h) => (
            <ClassRow
              key={`${h.account_id}-${h.asset_id}`}
              holding={h}
              totalKrw={totalKrw}
              onClick={() => setPicked(h)}
            />
          ))}
        </DataTable>
      </Modal>

      {/* 배분 도넛 조각 → 그 분류 바스켓. 비중의 분모는 총자산이 아니라 **그 분류
          합계**다(2026-09-25 사용자 지시: 컴퓨팅 인프라 1000원 중 AMD 700원 → 70%). */}
      <Modal
        open={basket != null}
        onClose={() => setBasket(null)}
        title={basket?.label ?? ""}
        subtitle={
          basket
            ? `${AXES.find((a) => a.id === axis)?.label} · ${basketRows.length}종목 · 분류 합계 ${formatKrwString(String(basketTotal))} · 마지막 동기화 기준`
            : undefined
        }
        width={640}
      >
        <DataTable
          columns={["종목", "평가금액", "분류 내 비중"]}
          align={["left", "right", "right"]}
          empty="이 분류에 든 종목이 없습니다"
        >
          {basketRows.map((h) => {
            const share = basketTotal > 0 ? Number(h.market_value_krw) / basketTotal : 0;
            return (
              <tr
                key={`${h.account_id}-${h.asset_id}`}
                onClick={() => setPicked(h)}
                className="cursor-pointer border-b border-hairline transition-colors hover:bg-canvas-soft"
              >
                <Cell left strong>
                  <span className="flex items-center gap-1.5">
                    <span>{h.ticker}</span>
                    <span className="max-w-[200px] truncate text-[10px] font-semibold text-ink-muted">
                      {h.name}
                    </span>
                  </span>
                </Cell>
                <Cell>{formatKrwString(h.market_value_krw)}</Cell>
                <Cell strong>{`${(share * 100).toFixed(1)}%`}</Cell>
              </tr>
            );
          })}
        </DataTable>
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
  /** 실시간 시세 — 현재가·당일 칸에만 쓴다. 없으면(못 받은 종목) 증권사 현재가. */
  live?: LiveQuote;
  totalKrw: string | null;
  onClick: () => void;
}) {
  // ★평가금액·손익·비중은 증권사 값이다 — 위 합계·도넛과 같은 원천이어야 행의
  //   합이 합계와 맞는다. 없으면 "—".
  const valueKrw = h.market_value_krw;
  const pnlKrw = h.unrealized_pnl_krw;
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
      <Cell tone="muted">{formatQuantityString(h.quantity)}</Cell>
      {/* 매입 평단 — 현지 통화다. 원화로 바꾸지 않는다(환율 시점이 섞인다). */}
      <Cell>{formatPriceString(h.average_purchase_price, h.currency)}</Cell>
      <Cell>
        {live ? (
          <span className="inline-flex items-center gap-1">
            {`$${Number(live.price).toLocaleString("en-US", {
              minimumFractionDigits: 2,
              maximumFractionDigits: 2,
            })}`}
            {/* ⚠️데이마켓 체결가를 정규장 종가인 척 두지 않는다. 값은 버리지
                않는다 — 한국 투자자가 실제로 체결할 수 있는 가격이다. 실측
                (2026-09-22 3회)에서 거래량이 12배 붙는 동안 괴리의 부호까지
                뒤집혔다(SOXL +2.58% → +3.50% → -2.12%). '틀린 값'이 아니라
                '살아 움직이는 다른 세션의 값'이라 그렇게 적는다. */}
            {live.thin_session && (
              <span
                title={
                  `미국 정규장을 아직 거치지 않은 가격입니다 (한국 데이마켓·프리마켓).` +
                  (live.volume
                    ? ` 이 봉의 거래량 ${Number(live.volume).toLocaleString("en-US")}주 — 실제로 체결 가능한 가격이지만 정규장 종가와는 다를 수 있습니다.`
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

function ClassRow({
  holding: h,
  totalKrw,
  onClick,
}: {
  holding: PortfolioHolding;
  totalKrw: string | null;
  onClick: () => void;
}) {
  // 비중은 증권사 평가액 기준(합계·도넛과 같은 원천).
  const valueKrw = h.market_value_krw;
  const weight =
    totalKrw && valueKrw && Number(totalKrw) !== 0
      ? `${((Number(valueKrw) / Number(totalKrw)) * 100).toFixed(1)}%`
      : "—";
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
      {/* ⚠️빈 값을 "—" 로만 적지 않는다. '분류가 없다'와 '아직 안 봤다'는 다르고,
          배분 도넛의 회색 조각과 같은 말을 써야 두 화면이 이어진다. */}
      <ClassCell value={h.tech_l1} missing="미분류" />
      <ClassCell value={h.tech_l2} />
      <ClassCell value={h.tech_l3} />
      <ClassCell value={h.sector} missing="미분류" />
      <ClassCell value={h.country} />
      <Cell tone="muted">{weight}</Cell>
    </tr>
  );
}

function ClassCell({ value, missing = "—" }: { value: string | null; missing?: string }) {
  const empty = value == null || value === "";
  return (
    <Cell left tone={empty ? "muted" : undefined} className="max-w-[140px] truncate">
      {empty ? missing : value}
    </Cell>
  );
}

function numOrNull(v: string | null): number | null {
  return v == null ? null : Number(v);
}

/** 축 눈금용 접은 금액 — "393만". 축은 자릿수를 다 보여줄 자리가 없다. */
function compactKrw(v: number): string {
  const abs = Math.abs(v);
  const sign = v < 0 ? "-" : "";
  if (abs >= 100_000_000) return `${sign}${(abs / 100_000_000).toFixed(1)}억`;
  if (abs >= 10_000) return `${sign}${Math.round(abs / 10_000).toLocaleString("ko-KR")}만`;
  return `${sign}${Math.round(abs).toLocaleString("ko-KR")}`;
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
