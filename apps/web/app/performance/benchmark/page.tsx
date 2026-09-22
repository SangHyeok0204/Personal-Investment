"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { PageContainer } from "@/components/layout/page-header";
import { Topbar } from "@/components/layout/topbar";
import { useAccount } from "@/components/layout/account-context";
import { CompareChart, type CompareSeries } from "@/components/charts/compare-chart";
import { Modal } from "@/components/ui/modal";
import { Cell, DataTable, NotConnectedBanner, StatTile, StubCard } from "@/components/stub";
import { getBenchmark, type BenchmarkPeriod } from "@/lib/api";
import { cn } from "@/lib/utils";

// 벤치마크 비교 — 내 계좌 vs S&P 500 · 필라델피아 반도체.
//
// ★기준 지수는 보유 구성을 보고 골랐다. 섹터 축에서 컴퓨팅 인프라가 47%이고
//   최대 비중이 SOXL(반도체 3배)이라, 시장 전체(S&P 500)와 반도체(SOX) 둘을
//   나란히 둔다. 하나만 두면 "시장을 이겼나"와 "내 분야를 이겼나"가 섞인다.
//
// ★**통화를 맞춘다.** 내 계좌 수익률은 원화 기준(키움이 KRW 로 준다)이고 지수는
//   달러 기준이다. 그대로 비교하면 환율 변동이 통째로 내 실력처럼 보인다.
//   원화 환산이 정본이고, USD 기준은 "환율을 빼면 얼마였나"로 따로 보여 준다.
//
// ⚠️내 수익률에는 **예수금이 포함**돼 있다(키움 예탁자산 기준). 지수는 100%
//   투자된 상태다. 현금을 들고 있던 기간만큼 수익률이 희석되는 건 사실이고,
//   그게 실제 계좌 성과이므로 보정하지 않는다 — 대신 화면에 적어 둔다.

/** 표 헤더용 짧은 이름. 이름마다 따로 정한다 — 길이로 자르면 서로 겹친다. */
const SHORT_NAME: Record<string, string> = {
  "S&P 500": "S&P 500",
  "필라델피아 반도체": "SOX",
};

function shortName(name: string): string {
  return SHORT_NAME[name] ?? name;
}

function pct(value: string | null | undefined, digits = 2): string {
  if (value == null) return "—";
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  return `${n > 0 ? "+" : ""}${(n * 100).toFixed(digits)}%`;
}

function tone(value: string | null | undefined): "up" | "down" | undefined {
  if (value == null) return undefined;
  const n = Number(value);
  if (!Number.isFinite(n) || n === 0) return undefined;
  return n > 0 ? "up" : "down";
}

export default function BenchmarkPage() {
  const { accountId, connected } = useAccount();
  const [picked, setPicked] = useState<BenchmarkPeriod | null>(null);
  const [noteOpen, setNoteOpen] = useState(false);

  const benchmark = useQuery({
    queryKey: ["benchmark", accountId],
    queryFn: () => getBenchmark(accountId),
    staleTime: 10 * 60_000,
  });

  const data = benchmark.data;
  const names = data?.benchmarks ?? [];

  const chart = useMemo(() => {
    if (!data || data.series.length === 0) return null;
    const dates = data.series.map((p) => p.base_date);
    const series: CompareSeries[] = [
      {
        name: "내 계좌",
        emphasis: true,
        values: data.series.map((p) => (p.portfolio == null ? null : Number(p.portfolio))),
      },
      ...names.map((name) => ({
        name,
        values: data.series.map((p) => {
          const v = p.benchmarks[name];
          return v == null ? null : Number(v);
        }),
      })),
    ];
    return { dates, series };
  }, [data, names]);

  const full = data?.periods.find((p) => p.label === "전체");
  const oneYear = data?.periods.find((p) => p.label === "1Y");

  return (
    <>
      <Topbar title="벤치마크 비교" subtitle="S&P 500 · 반도체(SOX) 대비 — 원화 환산" />
      <PageContainer fit>
        {!connected && <NotConnectedBanner what="일별 계좌 수익률" />}

        <div className="grid shrink-0 grid-cols-2 gap-2.5 lg:grid-cols-4">
          <StatTile
            label="내 계좌 (전체)"
            value={full ? pct(full.portfolio) : null}
            hint={
              data?.first_date ? `${data.first_date} ~ ${data.last_date}` : "전체 기간"
            }
            accent="auto"
            loading={benchmark.isLoading}
          />
          {names.map((name) => (
            <StatTile
              key={name}
              label={`${name} (전체)`}
              value={full ? pct(full.benchmarks_krw[name]) : null}
              hint={
                full
                  ? `내 계좌 대비 ${pct(full.excess[name])}`
                  : "원화 환산"
              }
              accent="auto"
              loading={benchmark.isLoading}
            />
          ))}
          <StatTile
            label="1년 초과수익"
            value={oneYear && names[0] ? pct(oneYear.excess[names[0]]) : null}
            hint={names[0] ? `${names[0]} 대비 · 눌러서 설명` : "초과수익"}
            actionHint="눌러서 읽는 법 보기"
            onClick={() => setNoteOpen(true)}
            accent="auto"
            loading={benchmark.isLoading}
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
            title="누적 비교"
            subtitle={data?.first_date ? `${data.first_date} = 100` : "구간 시작 = 100"}
          >
            {benchmark.isLoading ? (
              <Empty text="불러오는 중…" />
            ) : !chart ? (
              <Empty text="비교할 데이터가 없습니다" />
            ) : (
              <CompareChart
                dates={chart.dates}
                series={chart.series}
                height={250}
                valueFormat={(v) => v.toFixed(0)}
              />
            )}
          </StubCard>

          <StubCard
            title="기간별"
            subtitle="원화 환산 기준"
            scrollBody
            action={
              <button
                type="button"
                onClick={() => setNoteOpen(true)}
                className="rounded-full bg-white/15 px-2.5 py-1 text-[11px] font-bold text-white transition-colors hover:bg-white/25"
              >
                읽는 법
              </button>
            }
          >
            <DataTable
              // ⚠️`DataTable` 은 컬럼명을 그대로 key 로 쓴다. 길다고 잘라 쓰면
              //   "S&P 500"(7자)과 "필라델피아 반도체"가 **둘 다 "반도체"**가 되어
              //   중복 key 경고가 나고 헤더도 같은 글자가 두 번 찍혔다(실제로 그랬다).
              //   축약은 이름별로 따로 정한다.
              columns={["기간", "내 계좌", ...names.map(shortName)]}
              align={["left", "right", ...names.map(() => "right" as const)]}
              empty={benchmark.isLoading ? "불러오는 중…" : "데이터가 없습니다"}
            >
              {(data?.periods ?? []).map((p) => (
                <tr
                  key={p.label}
                  onClick={() => setPicked(p)}
                  className="cursor-pointer border-b border-hairline transition-colors hover:bg-canvas-soft"
                >
                  <Cell left strong>
                    {p.label}
                  </Cell>
                  <Cell strong tone={tone(p.portfolio)}>
                    {pct(p.portfolio)}
                  </Cell>
                  {names.map((n) => (
                    <Cell key={n} tone={tone(p.benchmarks_krw[n])}>
                      {pct(p.benchmarks_krw[n])}
                    </Cell>
                  ))}
                </tr>
              ))}
            </DataTable>
          </StubCard>
        </div>
      </PageContainer>

      <Modal
        open={picked != null}
        onClose={() => setPicked(null)}
        title={`${picked?.label ?? ""} 비교`}
        subtitle={
          picked
            ? `${picked.start_date} ~ ${picked.end_date} · ${picked.observations}일`
            : undefined
        }
      >
        {picked && <PeriodDetail period={picked} names={names} />}
      </Modal>

      <Modal
        open={noteOpen}
        onClose={() => setNoteOpen(false)}
        title="이 화면 읽는 법"
        subtitle="비교가 성립하려면 맞춰야 하는 것들"
      >
        <ul className="space-y-2.5 text-[12px] leading-relaxed text-ink-secondary">
          <li>
            <strong>통화를 맞춥니다.</strong> {data?.currency_note} 기간 상세를 열면
            USD 기준 수익률도 함께 보여, 환율이 얼마나 갉아먹었는지 알 수 있습니다.
          </li>
          {/* ⚠️예전에는 "컴퓨팅 인프라가 47%" 라고 숫자를 박아 뒀다. 비중은
              매일 바뀌므로 그런 문구는 곧 거짓이 된다 — 세는 것은 서버가 한다. */}
          <li>
            <strong>기준 지수는 보유 구성에서 골랐습니다.</strong>{" "}
            {data?.top_ticker ? (
              <>
                지금 최대 비중이 {data.top_ticker}
                {data.top_weight &&
                  ` (${(Number(data.top_weight) * 100).toFixed(1)}%)`}
                이라,{" "}
              </>
            ) : null}
            시장 전체(S&amp;P 500)와 반도체(SOX)를 나란히 둡니다 — 하나만 보면
            &quot;시장을 이겼나&quot;와 &quot;내 분야를 이겼나&quot;가 섞입니다.
          </li>
          {/* ★지수는 1배다. 이걸 안 적으면 오른 장에서는 실력처럼, 빠진 장에서는
              불운처럼 읽힌다. */}
          {data?.effective_exposure && (
            <li>
              <strong>
                지수는 1배인데 이 계좌는{" "}
                {Number(data.effective_exposure).toFixed(2)}배입니다.
              </strong>{" "}
              레버리지 상품 때문에 같은 시장 움직임에 그만큼 크게 반응합니다 —
              지수를 이기고 지는 폭이 실력보다 크게 나옵니다. 초과수익을 읽을 때
              이 배수를 같이 보세요.{" "}
              <strong>이 값은 하루 기준입니다</strong> — 레버리지 ETF 는 여러
              날에 걸치면 변동성 끌림 때문에 배수 × 기간수익률이 되지 않습니다.
            </li>
          )}
          <li>
            <strong>내 수익률에는 예수금이 포함됩니다.</strong> 키움 예탁자산 기준이라
            현금을 들고 있던 기간만큼 희석됩니다. 지수는 100% 투자된 상태입니다.
            보정하지 않는 이유는 그게 실제 계좌 성과이기 때문입니다.
          </li>
          <li>
            <strong>SOX 는 지수이고 제가 들고 있는 건 3배 레버리지(SOXL)</strong>
            입니다. 방향은 같아도 변동폭이 다르므로, 같은 숫자로 우열을 가리기보다
            방향과 시점을 보는 편이 낫습니다.
          </li>
          <li>
            양쪽에 모두 값이 있는 날짜만 씁니다 — 계좌 시계열에는 주말 행이 있고
            지수에는 없습니다.
          </li>
          <li>
            <strong>기준일은 첫 수익률 직전 날입니다.</strong> 첫 수익률일의
            지수를 기준으로 삼으면 그날 수익률이 통째로 빠집니다 — 실제로 그
            상태였고, 같은 구간·같은 관측일수인데 이 화면은 −1.21%, &apos;성과
            분석&apos;은 −1.98% 를 보였습니다. 값이 비슷해서 오류로 보이지도
            않았습니다. 지금은 두 화면을 맞대는 검사가 걸려 있습니다.
          </li>
          <li>
            <strong>시차를 밀지 않습니다.</strong> 한국 마감 기준 계좌와 미국
            지수 종가를 같은 날짜로 맞댑니다 — 계좌 일간수익률과 SOX 일간수익률의
            상관이 같은 날 +0.70, 하루 밀면 +0.02, 이틀 밀면 −0.21 이었습니다
            (75일). 증권사가 같은 달력날짜로 기록한다는 뜻입니다.
          </li>
        </ul>
      </Modal>
    </>
  );
}

function PeriodDetail({
  period: p,
  names,
}: {
  period: BenchmarkPeriod;
  names: string[];
}) {
  return (
    <div className="space-y-3">
      <div className="flex items-baseline justify-between border-b border-hairline pb-2">
        <span className="text-[12px] text-ink-secondary">내 계좌</span>
        <span
          className={cn(
            "text-[20px] font-extrabold tabular-nums",
            tone(p.portfolio) === "up" && "text-bid",
            tone(p.portfolio) === "down" && "text-ask",
          )}
        >
          {pct(p.portfolio)}
        </span>
      </div>

      <DataTable
        columns={["지수", "원화 환산", "USD 기준", "환율 효과", "초과수익"]}
        align={["left", "right", "right", "right", "right"]}
      >
        {names.map((n) => {
          const krw = p.benchmarks_krw[n];
          const usd = p.benchmarks_usd[n];
          const fx =
            krw != null && usd != null
              ? (Number(krw) - Number(usd)).toFixed(4)
              : null;
          return (
            <tr key={n} className="border-b border-hairline">
              <Cell left strong>
                {n}
              </Cell>
              <Cell strong tone={tone(krw)}>
                {pct(krw)}
              </Cell>
              <Cell tone={tone(usd)}>{pct(usd)}</Cell>
              <Cell tone={tone(fx)}>{fx == null ? "—" : `${pct(fx)}p`}</Cell>
              <Cell strong tone={tone(p.excess[n])}>
                {pct(p.excess[n])}
              </Cell>
            </tr>
          );
        })}
      </DataTable>

      <p className="text-[11px] leading-relaxed text-ink-muted">
        <strong>환율 효과</strong>는 원화 환산 수익률에서 USD 기준을 뺀 값입니다 —
        음수면 원화가 강해져 달러 자산의 원화 수익률이 줄었다는 뜻입니다.{" "}
        <strong>초과수익</strong>은 내 계좌 수익률에서 원화 환산 지수 수익률을 뺀
        값이고, 통화를 맞춘 뒤라야 의미가 있습니다.
      </p>
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
