"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { PageContainer } from "@/components/layout/page-header";
import { Topbar } from "@/components/layout/topbar";
import { useAccount } from "@/components/layout/account-context";
import { CompareChart, type CompareSeries } from "@/components/charts/compare-chart";
import { SignedBarChart } from "@/components/charts/signed-bar-chart";
import { Modal } from "@/components/ui/modal";
import {
  CardEmpty,
  Cell,
  DataTable,
  NotConnectedBanner,
  StatTile,
  StubCard,
} from "@/components/stub";
import { getBenchmark, type BenchmarkPeriod } from "@/lib/api";
import { cn } from "@/lib/utils";

// 벤치마크 비교 — 내 계좌 vs S&P 500.
//
// ★2026-09-25 사용자 지시로 반도체(SOX)를 뺐다. 원래는 최대 비중이 SOXL 이라
//   S&P 500 과 SOX 를 나란히 뒀었다. 지수 목록은 서버(_BENCHMARKS)가 정하고
//   이 화면은 받은 이름을 그대로 그린다 — 되살리면 칩·칸이 저절로 돌아온다.
//
// ★**통화를 맞춘다.** 내 계좌 수익률은 원화 기준(키움이 KRW 로 준다)이고 지수는
//   달러 기준이다. 그대로 비교하면 환율 변동이 통째로 내 실력처럼 보인다.
//   원화 환산이 정본이고, USD 기준은 "환율을 빼면 얼마였나"로 따로 보여 준다.
//
// ⚠️내 수익률에는 **예수금이 포함**돼 있다(키움 예탁자산 기준). 지수는 100%
//   투자된 상태다. 현금을 들고 있던 기간만큼 수익률이 희석되는 건 사실이고,
//   그게 실제 계좌 성과이므로 보정하지 않는다 — 대신 화면에 적어 둔다.
//
// ★2026-09-25 사용자 지시(전체 메뉴 공통 패턴): 오른쪽 '기간별' **표**를 칸을 눌러
//   여는 팝업으로 옮기고, 그 자리에 **월별 초과수익 막대**를 둔다. 막대를 누르면
//   그 달 내 계좌·지수 수익률이 뜬다. 누적 비교는 일별 추이라 선 그대로 둔다.
//
// ⚠️월별 수익률은 **화면에서** 계산한다 — 서버 시계열(구간 시작 = 100, 원화 환산)의
//   월말 값 ÷ 전월 말 값 − 1. 서버의 기간별 수익률과 같은 방식(두 날의 수준 비)이지만
//   시계열이 소수 둘째 자리로 반올림돼 와서 기간별 표와 0.01%p 안팎 어긋날 수 있다.
//   첫 달은 구간 시작일부터, 마지막 달은 마지막 관측일까지다.

/** 표 헤더용 짧은 이름. 이름마다 따로 정한다 — 길이로 자르면 서로 겹친다. */
const SHORT_NAME: Record<string, string> = {
  "S&P 500": "S&P 500",
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

type MonthRow = {
  month: string;
  start_date: string;
  end_date: string;
  /** 비율(0.0123). 계좌·지수 모두 원화 기준. */
  portfolio: number | null;
  benchmarks: Record<string, number | null>;
};

/** 100 기준 시계열 → 월별 수익률. 월 경계 값은 전월 마지막 관측일. */
function monthlyFromSeries(
  series: { base_date: string; portfolio: string | null; benchmarks: Record<string, string | null> }[],
  names: string[],
): MonthRow[] {
  const ratio = (end: string | null | undefined, start: string | null | undefined) =>
    end == null || start == null || Number(start) === 0 ? null : Number(end) / Number(start) - 1;
  const out: MonthRow[] = [];
  let prev = series[0];
  for (let i = 0; i < series.length; i++) {
    const cur = series[i];
    const month = cur.base_date.slice(0, 7);
    const next = series[i + 1];
    if (next && next.base_date.slice(0, 7) === month) continue;
    // cur 가 이 달 마지막 관측일. prev 는 전월 마지막(첫 달은 구간 시작).
    const benchmarks: Record<string, number | null> = {};
    for (const n of names) benchmarks[n] = ratio(cur.benchmarks[n], prev.benchmarks[n]);
    out.push({
      month,
      start_date: prev.base_date,
      end_date: cur.base_date,
      portfolio: ratio(cur.portfolio, prev.portfolio),
      benchmarks,
    });
    prev = cur;
  }
  return out;
}

export default function BenchmarkPage() {
  const { accountId, connected } = useAccount();
  const [picked, setPicked] = useState<BenchmarkPeriod | null>(null);
  const [periodsOpen, setPeriodsOpen] = useState(false);
  // 막대가 비교할 지수 — 하나만 고른다(초과수익은 지수마다 다르다).
  const [against, setAgainst] = useState<string | null>(null);
  const [pickedMonth, setPickedMonth] = useState<string | null>(null);

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

  const vs = against ?? names[0] ?? null;
  const months = useMemo(
    () => (data && data.series.length > 1 ? monthlyFromSeries(data.series, names) : []),
    [data, names],
  );
  // 초과수익 = 내 계좌 − 지수(원화 환산). 막대 값은 %p 라 ×100 해 둔다.
  const excessColumns = useMemo(
    () =>
      months
        .filter((m) => vs != null && m.portfolio != null && m.benchmarks[vs] != null)
        .map((m) => ({
          key: m.month,
          label: m.month,
          value: (m.portfolio! - m.benchmarks[vs!]!) * 100,
        })),
    [months, vs],
  );
  const monthPicked = months.find((m) => m.month === pickedMonth) ?? null;

  const full = data?.periods.find((p) => p.label === "전체");
  const oneYear = data?.periods.find((p) => p.label === "1Y");

  return (
    <>
      <Topbar title="벤치마크 비교" subtitle="S&P 500 대비 — 원화 환산" />
      <PageContainer fit>
        {!connected && <NotConnectedBanner what="일별 계좌 수익률" />}

        <div className="grid shrink-0 grid-cols-2 gap-2.5 lg:grid-cols-3">
          <StatTile
            label="내 계좌 (전체)"
            value={full ? pct(full.portfolio) : null}
            hint={
              data?.first_date ? `${data.first_date} ~ ${data.last_date}` : "전체 기간"
            }
            actionHint="눌러서 기간별 보기"
            onClick={() => setPeriodsOpen(true)}
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
              actionHint="눌러서 기간별 보기"
              onClick={() => setPeriodsOpen(true)}
              accent="auto"
              loading={benchmark.isLoading}
            />
          ))}
          <StatTile
            label="1년 초과수익"
            value={oneYear && names[0] ? pct(oneYear.excess[names[0]]) : null}
            hint={names[0] ? `${names[0]} 대비` : "초과수익"}
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
              <CardEmpty text="불러오는 중…" />
            ) : !chart ? (
              <CardEmpty text="비교할 데이터가 없습니다" />
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
            title="월별 초과수익"
            subtitle={vs ? `내 계좌 − ${shortName(vs)} · 막대를 누르면 그 달` : "막대를 누르면 그 달"}
            scrollBody
            action={
              <div className="flex items-center gap-2">
                {/* 지수가 하나면 고를 게 없다 — 칩을 숨긴다. */}
                {names.length > 1 && (
                <div className="flex gap-1">
                  {names.map((n) => (
                    <button
                      key={n}
                      type="button"
                      onClick={() => setAgainst(n)}
                      aria-pressed={vs === n}
                      className={cn(
                        "rounded px-1.5 py-0.5 text-[10px] font-bold transition-colors",
                        vs === n
                          ? "bg-white/90 text-ge-header"
                          : "text-white/60 hover:bg-white/15 hover:text-white",
                      )}
                    >
                      {shortName(n)}
                    </button>
                  ))}
                </div>
                )}
                <button
                  type="button"
                  onClick={() => setPeriodsOpen(true)}
                  className="rounded-full bg-white/15 px-2.5 py-1 text-[11px] font-bold text-white transition-colors hover:bg-white/25"
                >
                  기간별
                </button>
              </div>
            }
          >
            {benchmark.isLoading ? (
              <CardEmpty text="불러오는 중…" />
            ) : (
              <SignedBarChart
                columns={excessColumns}
                height={250}
                formatValue={(v) => `${v > 0 ? "+" : ""}${v.toFixed(2)}%p`}
                selected={pickedMonth}
                onPick={setPickedMonth}
              />
            )}
            <p className="mt-2 text-[11px] leading-snug text-ink-muted">
              원화 환산 기준 · 위: 이긴 달 · 아래: 진 달
            </p>
          </StubCard>
        </div>
      </PageContainer>

      {/* ── 막대 → 그 달 ───────────────────────────────────────────────── */}
      <Modal
        open={monthPicked != null}
        onClose={() => setPickedMonth(null)}
        title={monthPicked ? `${monthPicked.month} 비교` : ""}
        subtitle={
          monthPicked
            ? `${monthPicked.start_date} 종가 → ${monthPicked.end_date} · 원화 환산`
            : undefined
        }
        width={560}
      >
        {monthPicked && <MonthDetail row={monthPicked} names={names} />}
      </Modal>

      {/* ── 칸·'기간별' → 옛 기간별 표 ─────────────────────────────────── */}
      <Modal
        open={periodsOpen}
        onClose={() => setPeriodsOpen(false)}
        title="기간별"
        subtitle="원화 환산 기준 · 행을 누르면 USD 기준·환율 효과"
        width={620}
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
      </Modal>

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
    </div>
  );
}

/** 한 달의 계좌·지수 수익률. 초과수익은 수익률의 차이라 %p 다. */
function MonthDetail({ row: m, names }: { row: MonthRow; names: string[] }) {
  const ratio = (v: number | null) => (v == null ? null : String(v));
  return (
    <div className="space-y-3">
      <div className="flex items-baseline justify-between border-b border-hairline pb-2">
        <span className="text-[12px] text-ink-secondary">내 계좌</span>
        <span
          className={cn(
            "text-[20px] font-extrabold tabular-nums",
            tone(ratio(m.portfolio)) === "up" && "text-bid",
            tone(ratio(m.portfolio)) === "down" && "text-ask",
          )}
        >
          {pct(ratio(m.portfolio))}
        </span>
      </div>
      <DataTable
        columns={["지수", "원화 환산", "초과수익"]}
        align={["left", "right", "right"]}
      >
        {names.map((n) => {
          const b = m.benchmarks[n];
          const ex = m.portfolio != null && b != null ? String(m.portfolio - b) : null;
          return (
            <tr key={n} className="border-b border-hairline">
              <Cell left strong>
                {n}
              </Cell>
              <Cell tone={tone(ratio(b))}>{pct(ratio(b))}</Cell>
              <Cell strong tone={tone(ex)}>
                {ex == null ? "—" : `${pct(ex)}p`}
              </Cell>
            </tr>
          );
        })}
      </DataTable>
    </div>
  );
}

