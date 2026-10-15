"use client";

import { useMemo, useState } from "react";
import { CompareChart, type CompareSeries } from "@/components/charts/compare-chart";
import { SeriesChart } from "@/components/charts/series-chart";
import { CardEmpty, HeaderChip, StatTile, StubCard } from "@/components/stub";
import { formatKrwSigned, formatKrwString } from "@/lib/format";
import { pctOrNull } from "./format";
import { useAccountReturn, useBenchmark, usePerformanceSeries } from "./queries";

// 2. 수익률 추이 — 내 계좌 수익률 시계열(왼쪽) + 벤치마크 누적 비교(오른쪽).
//
// ★2026-10-04 사용자 지정: 기본 그래프는 **내 계좌 수익률**(/account-return — 시작일 이후
//   손익 ÷ 투입 원금, 6/01~)이다. 입출금 날은 그래프 아래 세모로 표시한다.
//   연쇄 수익률(TWR)은 '참고: 시간가중(TWR)'으로만 남긴다 — 두 정의를 섞지 않는다.
//   ⚠️옛 '원금 대비 %'(원화 증감 ÷ (시작 + 순입금))는 세 번째 정의라 지웠다.
//
// ★**통화를 맞춘다(벤치마크).** 내 계좌는 원화로 오고 지수는 달러 기준이다. 그대로 비교하면
//   환율 변동이 통째로 내 실력처럼 보인다. 같은 기준끼리 짝짓는다:
//     · 내 계좌 (환율 제외) = 키움 손익 기준 ↔ S&P 500 (USD)
//     · 내 계좌 원화 실질 (환차 포함) = 총자산 − 투입 원금 ↔ S&P 500 원화 환산
//   ⚠️원화 −9% 대는 계산이 맞다 — 같은 구간 환율이 −11% 빠졌다(키움 환율도 같은 방향).
//
// ⚠️내 수익률에는 **예수금이 포함**돼 있다(키움 예탁자산 기준). 지수는 100% 투자된
//   상태다. 현금을 들고 있던 기간만큼 희석되는 건 실제 계좌 성과이므로 보정하지 않는다.
//
// ★2026-09-25 반도체(SOX)는 사용자 지시로 뺐다. 지수 목록은 서버(_BENCHMARKS)가 정하고
//   이 섹션은 받은 이름을 그대로 그린다 — 되살리면 칸·선이 저절로 돌아온다.
//
// ★2026-10-15 한 화면 통합에서 걷은 중복:
//   · 옛 성과 분석 화면의 '내 계좌 수익률 추이' 카드 — 같은 /account-return 시계열을 같은
//     정의로 그리던 것이라 지웠다. 그 카드에만 있던 설명 한 줄(입금은 원금만 올린다)은
//     왼쪽 그래프 아래로 옮겼다.
//   · 옛 벤치마크 화면의 '내 계좌 (환율 제외)' · '내 계좌 원화 실질' 칸 — 같은 /account-return
//     값이라 맨 위 요약 첫 칸(두 값을 같이 적는다)으로 줄였다. 지수 쪽 칸(USD · 원화 환산 · 환율)은
//     여기 남긴다. 짝의 계좌 쪽 끝값은 누적 비교 범례에 같이 찍힌다.

const RANGES = [
  { id: 90, label: "3개월" },
  { id: 180, label: "6개월" },
  { id: 365, label: "1년" },
  { id: 1000, label: "전체" },
];

export function ReturnsSection() {
  const perf = usePerformanceSeries();
  const account = useAccountReturn();
  const benchmark = useBenchmark();
  const [days, setDays] = useState(365);
  const [metric, setMetric] = useState<"return" | "assets" | "cumulative">("return");

  const items = useMemo(() => perf.data?.items ?? [], [perf.data]);
  const acct = account.data;
  const from = useMemo(
    () => new Date(Date.now() - days * 86_400_000).toISOString().slice(0, 10),
    [days],
  );
  // 수익률 그래프도 기간 칩을 따른다 — 값은 늘 6/01 부터 센 그대로다.
  const returnPoints = useMemo(
    () => (acct?.items ?? []).filter((p) => p.date >= from),
    [acct, from],
  );
  // 예탁자산 선 그래프도 칩을 따른다(값은 그대로, 앞을 자를 뿐).
  const shownItems = useMemo(() => items.filter((p) => p.base_date >= from), [items, from]);
  const flowMarkers = useMemo(
    () =>
      returnPoints.flatMap((p, index) =>
        p.net_flow_krw == null
          ? []
          : [
              {
                index,
                label: `${Number(p.net_flow_krw) > 0 ? "입금" : "출금"} ${formatKrwSigned(p.net_flow_krw)}`,
                tone: (Number(p.net_flow_krw) > 0 ? "up" : "down") as "up" | "down",
              },
            ],
      ),
    [returnPoints],
  );

  // ⚠️누적손익은 **증권사 값을 쓰지 않는다.** acum_pl_amt 는 조회 창 경계에서
  //   그날 손익으로 초기화된다(실측: 2025-09-18, 2026-09-14). 차트로 그리면 없던
  //   절벽이 생긴다. 일별 손익을 직접 누적한다 — 끝값이 요약 '주가 손익' 칸과 같다.
  // ★2026-10-05 06-01 손익부터 넣는다(시작 = 05-31 종가). 누적은 시작일부터 세고,
  //   칩은 그 뒤에 앞을 자른다 — 그래야 끝값이 칩과 상관없이 타일과 같다.
  const cumulativePnl = useMemo(() => {
    let sum = 0;
    return items
      .map((p) => {
        sum += Number(p.pnl_krw ?? 0);
        return { date: p.base_date, value: sum };
      })
      .filter((p) => p.date >= from);
  }, [items, from]);

  const ss = benchmark.data?.since_start ?? null;
  const main = ss?.indices[0] ?? null;
  // 누적 비교 — 기준점(시작일 장 시작 전) = 100. 내 계좌 · 지수 USD · 지수 원화.
  const sinceChart = useMemo(() => {
    if (!ss || ss.series.length === 0) return null;
    const n = (v: string | null | undefined) => (v == null ? null : Number(v));
    const series: CompareSeries[] = [
      { name: "내 계좌 (환율 제외)", emphasis: true, values: ss.series.map((p) => n(p.account)) },
      ...ss.indices.flatMap((i) => [
        { name: `${i.name} (USD)`, values: ss.series.map((p) => n(p.benchmarks_usd[i.name])) },
        { name: `${i.name} (원화)`, values: ss.series.map((p) => n(p.benchmarks_krw[i.name])) },
      ]),
      // 원화 실질 계좌는 맨 뒤 — 색(연갈색)이 계좌 계열로 읽히고 지수 색 순서가 그대로다.
      { name: "내 계좌 (원화 실질)", values: ss.series.map((p) => n(p.account_krw)) },
    ];
    return { dates: ss.series.map((p) => p.date), series };
  }, [ss]);

  return (
    <section id="returns" className="scroll-mt-28 space-y-3">
      {/* 지수 쪽 칸 — 짝: S&P USD ↔ 내 계좌(환율 제외), S&P 원화 ↔ 내 계좌 원화 실질. */}
      <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-3">
        <StatTile
          label={`${main?.name ?? "S&P 500"} (USD)`}
          value={main ? pctOrNull(main.return_usd) : null}
          hint={
            main?.end_date
              ? `지수 자체 · ${main.base_date?.slice(5)} → ${main.end_date.slice(5)} 종가`
              : "지수 자체의 움직임"
          }
          subHint="짝: 내 계좌 (환율 제외)"
          accent="auto"
          loading={benchmark.isLoading}
        />
        <StatTile
          label={`${main?.name ?? "S&P 500"} 원화 환산`}
          value={main ? pctOrNull(main.return_krw) : null}
          hint={main?.end_date ? `환율 효과 포함 · ${main.end_date} 기준` : "환율 효과 포함"}
          subHint="짝: 내 계좌 원화 실질 (환차 포함)"
          accent="auto"
          loading={benchmark.isLoading}
        />
        <StatTile
          label="환율 (USD/KRW)"
          value={main ? pctOrNull(main.fx_change) : null}
          hint={
            main?.fx_base && main.fx_end
              ? `${Number(main.fx_base).toFixed(2)} → ${Number(main.fx_end).toFixed(2)} (${main.fx_end_date?.slice(5)})`
              : "원화 환산의 차이"
          }
          accent="auto"
          loading={benchmark.isLoading}
        />
      </div>

      <div className="grid grid-cols-1 gap-3 xl:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]">
        <StubCard
          title={
            metric === "return"
              ? "내 계좌 수익률 추이"
              : metric === "assets"
                ? "예탁자산 추이"
                : "누적손익 추이"
          }
          subtitle={
            metric === "return"
              ? "시작일 이후 손익 ÷ 투입 원금 · ▲입금 ▼출금"
              : metric === "assets"
                ? "현금 + 주식 평가 (원화 환산)"
                : "일별 주가손익 누적 (환율 제외)"
          }
          action={
            <div className="flex flex-wrap items-center justify-end gap-1">
              {RANGES.map((r) => (
                <HeaderChip key={r.id} active={days === r.id} onClick={() => setDays(r.id)}>
                  {r.label}
                </HeaderChip>
              ))}
              <span className="mx-1 h-3.5 w-px bg-white/25" />
              <HeaderChip active={metric === "return"} onClick={() => setMetric("return")}>
                수익률
              </HeaderChip>
              <HeaderChip active={metric === "assets"} onClick={() => setMetric("assets")}>
                예탁자산
              </HeaderChip>
              <HeaderChip active={metric === "cumulative"} onClick={() => setMetric("cumulative")}>
                누적손익
              </HeaderChip>
            </div>
          }
        >
          {metric === "return" ? (
            returnPoints.length > 0 ? (
              <SeriesChart
                height={280}
                includeZero
                markers={flowMarkers}
                valueFormat={(v) => `${v.toFixed(1)}%`}
                points={returnPoints.map((p) => ({
                  date: p.date,
                  value: p.return_ratio == null ? null : Number(p.return_ratio) * 100,
                }))}
                tooltipFormat={(p) => {
                  const row = returnPoints.find((r) => r.date === p.date);
                  return `${p.value == null ? "—" : `${p.value > 0 ? "+" : ""}${p.value.toFixed(2)}%`} · 손익 ${formatKrwSigned(row?.pnl_since_start_krw)} ÷ 원금 ${formatKrwString(row?.invested_krw)} · 원화 실질 ${pctOrNull(row?.krw_return_ratio) ?? "—"}`;
                }}
              />
            ) : (
              <div className="flex h-[280px] items-center justify-center text-[12px] font-semibold text-ink-faint">
                {account.isLoading ? "불러오는 중…" : "데이터가 없습니다"}
              </div>
            )
          ) : shownItems.length > 0 ? (
            <SeriesChart
              height={280}
              includeZero={metric === "cumulative"}
              points={
                metric === "assets"
                  ? shownItems.map((p) => ({
                      date: p.base_date,
                      value: p.deposit_assets_krw == null ? null : Number(p.deposit_assets_krw),
                    }))
                  : cumulativePnl
              }
              tooltipFormat={(p) =>
                formatKrwString(p.value == null ? null : String(Math.round(p.value)))
              }
            />
          ) : (
            <div className="flex h-[280px] items-center justify-center text-[12px] font-semibold text-ink-faint">
              {perf.isLoading ? "불러오는 중…" : "데이터가 없습니다"}
            </div>
          )}
          <p className="mt-2 flex flex-wrap justify-between gap-x-3 text-[11px] leading-snug text-ink-muted">
            <span>
              {metric === "return"
                ? // 옛 성과 분석 화면 '내 계좌 수익률 추이' 카드의 설명 — 그 카드는 중복이라 걷었다.
                  "입금은 원금만 올린다 — 손익은 그대로 · 모르는 날은 비워 둔다"
                : "기간 칩은 그래프 앞을 자를 뿐 — 값은 늘 시작일부터 센다"}
            </span>
            {shownItems.length > 0 && (
              <span className="font-semibold text-ink-faint">
                {shownItems[0].base_date} ~ {shownItems[shownItems.length - 1].base_date} (
                {shownItems.length}일)
              </span>
            )}
          </p>
        </StubCard>

        <StubCard
          title="누적 비교"
          subtitle={
            ss
              ? `${ss.start} 장 시작 전 = 100 · 지수는 ${main?.end_date ?? "—"} 종가까지`
              : "시작일 = 100"
          }
        >
          <div className="grid min-h-[280px]">
            {benchmark.isLoading ? (
              <CardEmpty text="불러오는 중…" />
            ) : !sinceChart ? (
              <CardEmpty text="비교할 데이터가 없습니다" />
            ) : (
              <CompareChart
                dates={sinceChart.dates}
                series={sinceChart.series}
                height={250}
                valueFormat={(v) => v.toFixed(0)}
                legendFormat={(v) => `${v >= 100 ? "+" : ""}${(v - 100).toFixed(2)}%`}
              />
            )}
          </div>
          <p className="mt-2 text-[11px] leading-snug text-ink-muted">
            같은 기준끼리 견준다 — 환율 제외 ↔ USD · 원화 실질 ↔ 원화 환산 · 내 계좌에는 예수금 포함
          </p>
        </StubCard>
      </div>
    </section>
  );
}
