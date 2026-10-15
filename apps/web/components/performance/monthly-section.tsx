"use client";

import { useMemo, useState } from "react";
import { SeriesChart } from "@/components/charts/series-chart";
import { SignedBarChart } from "@/components/charts/signed-bar-chart";
import { Modal } from "@/components/ui/modal";
import {
  CardEmpty,
  Cell,
  DataTable,
  HeaderChip,
  ListButton,
  StubCard,
  toneOf,
} from "@/components/stub";
import type { DailyPerformancePoint, PerformanceAnalytics } from "@/lib/api";
import { formatKrwSigned, formatKrwString } from "@/lib/format";
import { cn } from "@/lib/utils";
import { pct, shortName, toneOfRatio } from "./format";
import { useAnalytics, useBenchmark, usePerformanceSeries } from "./queries";

// 3. 월별 — 옛 세 화면의 월별 막대를 한 카드로.
//
// ★2026-10-15 한 화면 통합: 월별 막대가 세 화면에 따로 있었다. **재는 것이 다르다**:
//   · 주가손익(원)   옛 수익률 추이 — 그 달 증권사 일별 손익 합. 환율 제외, 금액.
//   · 수익률(%)      옛 성과 분석 — 일별 연쇄 수익률(참고 TWR)을 그 달 안에서 곱한 값. 원화 기준.
//   · 초과수익(%p)   옛 벤치마크 — 내 계좌 − 지수(원화 환산). 참고 TWR.
//   금액과 %, 환율 제외와 원화 기준이라 하나로 합칠 수 없다 — 셋 다 남기고 헤더 칩으로
//   막대만 바꾼다. 막대를 누르면 **그 달의 세 가지를 한 팝업에** 모아 보여 준다(옛 세 팝업을
//   한 곳으로). 헤더 '전체 목록'은 세 숫자를 한 줄에 둔 월별 표다.
//   ⚠️옛 성과 분석의 연×월 격자 표는 같은 월별 TWR 값을 다른 모양으로 놓은 것이라 걷었다 —
//   같은 값이 월별 표의 '월 수익률' 열에 있다.
//
// ⚠️'월 손익'이 아니라 '월 주가손익'이다. 예탁자산은 원화 환산액이고 이 막대는 환율이
//   빠진 주가 손익이라, 이름을 같게 두면 "왜 자산은 줄었는데 손익은 플러스냐"가 된다.
//
// ★2026-10-05 첫날(06-01) 손익도 6월에 넣는다 — 요약 '주가 손익' 칸이 05-31 종가
//   기준으로 06-01 부터 세므로, 막대 합 = 칸. 그래서 막대는 기간 칩을 따르지 않는다.
//
// ⚠️벤치마크 월별 수익률은 **화면에서** 계산한다 — 서버 시계열(구간 시작 = 100, 원화 환산)의
//   월말 값 ÷ 전월 말 값 − 1. 서버의 기간별 수익률과 같은 방식(두 날의 수준 비)이지만
//   시계열이 소수 둘째 자리로 반올림돼 와서 기간별 표와 0.01%p 안팎 어긋날 수 있다.
//   첫 달은 구간 시작일부터, 마지막 달은 마지막 관측일까지다. 성과분석의 월 수익률(TWR)과도
//   계산 경로가 달라(입출금 날짜 보정 여부 등) 작은 차이가 날 수 있다 — 팝업에서 따로 적는다.

type Measure = "pnl" | "twr" | "excess";

type BenchMonth = {
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
): BenchMonth[] {
  const ratio = (end: string | null | undefined, start: string | null | undefined) =>
    end == null || start == null || Number(start) === 0 ? null : Number(end) / Number(start) - 1;
  const out: BenchMonth[] = [];
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

/** 월말 예탁자산과 그 달 주가손익 합. 최근 달이 위로. */
function aggregateMonthly(
  items: { base_date: string; deposit_assets_krw: string | null; pnl_krw: string | null }[],
) {
  const acc = new Map<string, { month: string; assets: number; pnl: number }>();
  items.forEach((p) => {
    const month = p.base_date.slice(0, 7);
    const entry = acc.get(month) ?? { month, assets: 0, pnl: 0 };
    // 마지막으로 본 값이 월말 값이다(items 는 날짜 오름차순).
    if (p.deposit_assets_krw != null) entry.assets = Number(p.deposit_assets_krw);
    // ★2026-10-05 첫날(06-01)도 센다 — 기준선은 서버가 붙인 05-31 종가다(items 밖).
    entry.pnl += Number(p.pnl_krw ?? 0);
    acc.set(month, entry);
  });
  return [...acc.values()].reverse();
}


export function MonthlySection({
  listOpen,
  onListOpenChange,
}: {
  /** 요약 '주가 손익' 칸이 여는 월별 표 — 그래서 상태를 화면이 들고 있다. */
  listOpen: boolean;
  onListOpenChange: (open: boolean) => void;
}) {
  const perf = usePerformanceSeries();
  const analytics = useAnalytics();
  const benchmark = useBenchmark();
  const [measure, setMeasure] = useState<Measure>("pnl");
  // 막대가 비교할 지수 — 하나만 고른다(초과수익은 지수마다 다르다).
  const [against, setAgainst] = useState<string | null>(null);
  const [pickedMonth, setPickedMonth] = useState<string | null>(null);

  const items = useMemo(() => perf.data?.items ?? [], [perf.data]);
  const pnlMonths = useMemo(() => aggregateMonthly(items), [items]);
  const twrMonths = useMemo(() => analytics.data?.monthly ?? [], [analytics.data]);
  const names = useMemo(() => benchmark.data?.benchmarks ?? [], [benchmark.data]);
  const vs = against ?? names[0] ?? null;
  const benchMonths = useMemo(
    () =>
      benchmark.data && benchmark.data.series.length > 1
        ? monthlyFromSeries(benchmark.data.series, names)
        : [],
    [benchmark.data, names],
  );

  // 막대는 왼쪽이 과거다(표는 최근 달이 위).
  const columns = useMemo(() => {
    if (measure === "pnl") {
      return [...pnlMonths].reverse().map((m) => ({ key: m.month, label: m.month, value: m.pnl }));
    }
    if (measure === "twr") {
      return [...twrMonths]
        .sort((a, b) => a.month.localeCompare(b.month))
        .map((m) => ({ key: m.month, label: m.month, value: Number(m.return_ratio) * 100 }));
    }
    // 초과수익 = 내 계좌 − 지수(원화 환산). 막대 값은 %p 라 ×100 해 둔다.
    return benchMonths
      .filter((m) => vs != null && m.portfolio != null && m.benchmarks[vs] != null)
      .map((m) => ({ key: m.month, label: m.month, value: (m.portfolio! - m.benchmarks[vs!]!) * 100 }));
  }, [measure, pnlMonths, twrMonths, benchMonths, vs]);

  // 세 출처의 달을 합친 목록(최근 달이 위). 한쪽에만 있는 달은 다른 칸이 '—'.
  const allMonths = useMemo(() => {
    const set = new Set<string>();
    pnlMonths.forEach((m) => set.add(m.month));
    twrMonths.forEach((m) => set.add(m.month));
    benchMonths.forEach((m) => set.add(m.month));
    return [...set].sort().reverse();
  }, [pnlMonths, twrMonths, benchMonths]);

  const loading =
    measure === "pnl" ? perf.isLoading : measure === "twr" ? analytics.isLoading : benchmark.isLoading;

  const subtitle =
    measure === "pnl"
      ? "환율 제외 · 막대를 누르면 그 달 일별 내역"
      : measure === "twr"
        ? "참고: 시간가중(TWR) · 원화 기준 · 막대를 누르면 그 달"
        : vs
          ? `참고: 시간가중(TWR) · 내 계좌 − ${shortName(vs)}(원화)`
          : "참고: 시간가중(TWR)";

  const picked = pickedMonth
    ? {
        month: pickedMonth,
        pnl: pnlMonths.find((m) => m.month === pickedMonth) ?? null,
        twr: twrMonths.find((m) => m.month === pickedMonth) ?? null,
        bench: benchMonths.find((m) => m.month === pickedMonth) ?? null,
        days: items.filter((p) => p.base_date.startsWith(pickedMonth)),
      }
    : null;

  return (
    <section id="monthly" className="scroll-mt-28">
      <StubCard
        title={measure === "pnl" ? "월별 주가손익" : measure === "twr" ? "월별 수익률" : "월별 초과수익"}
        subtitle={subtitle}
        action={
          <div className="flex items-center gap-1">
            <HeaderChip active={measure === "pnl"} onClick={() => setMeasure("pnl")}>
              주가손익(원)
            </HeaderChip>
            <HeaderChip active={measure === "twr"} onClick={() => setMeasure("twr")}>
              수익률(TWR)
            </HeaderChip>
            <HeaderChip active={measure === "excess"} onClick={() => setMeasure("excess")}>
              초과수익(%p)
            </HeaderChip>
            {/* 지수가 하나면 고를 게 없다 — 칩을 숨긴다. */}
            {measure === "excess" && names.length > 1 && (
              <>
                <span className="mx-1 h-3.5 w-px bg-white/25" />
                {names.map((n) => (
                  <HeaderChip key={n} active={vs === n} onClick={() => setAgainst(n)}>
                    {shortName(n)}
                  </HeaderChip>
                ))}
              </>
            )}
            <span className="mx-1 h-3.5 w-px bg-white/25" />
            <ListButton
              onClick={() => {
                setPickedMonth(null);
                onListOpenChange(true);
              }}
            />
          </div>
        }
      >
        {loading ? (
          <div className="h-[260px]">
            <CardEmpty text="불러오는 중…" />
          </div>
        ) : (
          <SignedBarChart
            columns={columns}
            height={240}
            formatValue={(v) =>
              measure === "pnl"
                ? formatKrwSigned(String(Math.round(v)))
                : `${v > 0 ? "+" : ""}${v.toFixed(2)}%${measure === "excess" ? "p" : ""}`
            }
            selected={pickedMonth}
            onPick={setPickedMonth}
          />
        )}
        <p className="mt-2 text-[11px] leading-snug text-ink-muted">
          {measure === "pnl"
            ? "월 주가손익 = 그 달 증권사 일별 손익 합 · 환율 제외 · 늘 시작일부터"
            : measure === "twr"
              ? "참고: 시간가중(TWR) — 일별 수익률을 그 달 안에서 곱해 누적한 값"
              : "참고: 시간가중(TWR) · 원화 환산 기준 · 위: 이긴 달 · 아래: 진 달"}
        </p>
      </StubCard>

      {/* ── 막대·행 → 그 달(세 가지를 한 팝업에) ───────────────────────────── */}
      <Modal
        open={picked != null}
        onClose={() => setPickedMonth(null)}
        title={picked ? `${picked.month}` : ""}
        subtitle="주가손익(환율 제외) · 월 수익률(참고 TWR) · 벤치마크 대비(원화 환산)"
        width={760}
      >
        {picked && (
          <div className="space-y-5">
            <MonthBlock
              title="주가손익 · 일별"
              note={
                picked.pnl
                  ? `월 주가손익 ${formatKrwSigned(String(Math.round(picked.pnl.pnl)))} · 월말 예탁자산 ${formatKrwString(String(Math.round(picked.pnl.assets)))}`
                  : "환율 제외"
              }
            >
              <MonthDays days={picked.days} />
            </MonthBlock>
            <MonthBlock
              title="월 수익률"
              note="참고: 시간가중(TWR) · 원화 기준 · 일별 수익률을 그 달 안에서 곱해 누적"
            >
              {picked.twr ? (
                <TwrMonthDetail month={picked.month} ratio={picked.twr.return_ratio} data={analytics.data} />
              ) : (
                <p className="text-[11px] text-ink-faint">이 달의 월 수익률이 없습니다.</p>
              )}
            </MonthBlock>
            <MonthBlock
              title="벤치마크 대비"
              note={
                picked.bench
                  ? `${picked.bench.start_date} 종가 → ${picked.bench.end_date} · 원화 환산 · 참고: 시간가중(TWR)`
                  : "원화 환산 · 참고: 시간가중(TWR)"
              }
            >
              {picked.bench ? (
                <BenchMonthDetail row={picked.bench} names={names} />
              ) : (
                <p className="text-[11px] text-ink-faint">이 달은 비교할 지수 데이터가 없습니다.</p>
              )}
            </MonthBlock>
          </div>
        )}
      </Modal>

      {/* ── 헤더 '전체 목록'·요약 '주가 손익' 칸 → 월별 표 ─────────────────── */}
      <Modal
        open={listOpen}
        onClose={() => onListOpenChange(false)}
        title="월별"
        subtitle="월말 자산(원화) · 주가손익(환율 제외) · 월 수익률·초과수익(참고 TWR) · 행을 누르면 그 달"
        width={760}
      >
        <div className="max-h-[60vh] overflow-y-auto">
          <DataTable
            columns={[
              "월",
              "월말 예탁자산",
              "월 주가손익",
              "월 수익률 (TWR)",
              vs ? `초과 vs ${shortName(vs)}` : "초과수익",
            ]}
            align={["left", "right", "right", "right", "right"]}
            empty={perf.isLoading || analytics.isLoading || benchmark.isLoading ? "불러오는 중…" : "데이터가 없습니다"}
          >
            {allMonths.map((month) => {
              const p = pnlMonths.find((m) => m.month === month);
              const t = twrMonths.find((m) => m.month === month);
              const b = benchMonths.find((m) => m.month === month);
              const ex =
                b && vs && b.portfolio != null && b.benchmarks[vs] != null
                  ? String(b.portfolio - b.benchmarks[vs]!)
                  : null;
              return (
                <tr
                  key={month}
                  onClick={() => {
                    onListOpenChange(false);
                    setPickedMonth(month);
                  }}
                  className="cursor-pointer border-b border-hairline transition-colors hover:bg-canvas-soft"
                >
                  <Cell left strong>
                    {month}
                  </Cell>
                  <Cell>{p ? formatKrwString(String(Math.round(p.assets))) : "—"}</Cell>
                  <Cell tone={p ? toneOf(String(p.pnl)) : undefined}>
                    {p ? formatKrwSigned(String(Math.round(p.pnl))) : "—"}
                  </Cell>
                  <Cell tone={toneOfRatio(t?.return_ratio)}>{pct(t?.return_ratio)}</Cell>
                  <Cell tone={toneOfRatio(ex)}>{ex == null ? "—" : `${pct(ex)}p`}</Cell>
                </tr>
              );
            })}
          </DataTable>
        </div>
      </Modal>
    </section>
  );
}

function MonthBlock({
  title,
  note,
  children,
}: {
  title: string;
  note: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <p className="mb-2 text-[12px] font-extrabold text-ge-navy">
        {title}
        <span className="ml-2 text-[11px] font-medium text-ink-muted">{note}</span>
      </p>
      {children}
    </div>
  );
}

/** 그 달의 일별 행. 막대가 월로 묶어 잃은 '어느 날'을 여기서 돌려준다. */
function MonthDays({ days }: { days: DailyPerformancePoint[] }) {
  return (
    <div className="max-h-[40vh] overflow-y-auto">
      <DataTable
        columns={["날짜", "예탁자산", "주가손익", "입금", "출금"]}
        empty="이 달에는 일별 성과가 없습니다"
      >
        {/* ★2026-10-05 기준선이 05-31 종가로 옮겨 가 06-01 도 세는 날이다 — '기준선' 표시를 뗐다. */}
        {days.map((p) => (
          <tr key={p.base_date} className="border-b border-hairline">
            <Cell left>{p.base_date}</Cell>
            <Cell>{formatKrwString(p.deposit_assets_krw)}</Cell>
            <Cell tone={toneOf(p.pnl_krw)}>{formatKrwSigned(p.pnl_krw)}</Cell>
            <Cell tone={Number(p.deposit_krw ?? 0) ? "up" : "muted"}>
              {formatKrwString(p.deposit_krw)}
            </Cell>
            <Cell tone={Number(p.withdrawal_krw ?? 0) ? "down" : "muted"}>
              {formatKrwString(p.withdrawal_krw)}
            </Cell>
          </tr>
        ))}
      </DataTable>
    </div>
  );
}

/** 월 수익률(참고 TWR)과, 그 달 안의 낙폭 추이. */
function TwrMonthDetail({
  month,
  ratio,
  data,
}: {
  month: string;
  ratio: string;
  data?: PerformanceAnalytics;
}) {
  const points = (data?.drawdown ?? [])
    .filter((d) => d.base_date.startsWith(month))
    .map((d) => ({ date: d.base_date, value: Number(d.drawdown) * 100 }));
  const deepest = points.reduce<(typeof points)[number] | null>(
    (lo, p) => (lo == null || p.value < lo.value ? p : lo),
    null,
  );
  return (
    <div className="space-y-3">
      <div className="flex items-baseline justify-between border-b border-hairline pb-2">
        <span className="text-[12px] text-ink-secondary">월 수익률</span>
        <span
          className={cn(
            "text-[20px] font-extrabold tabular-nums",
            toneOfRatio(ratio) === "up" && "text-bid",
            toneOfRatio(ratio) === "down" && "text-ask",
          )}
        >
          {pct(ratio)}
        </span>
      </div>
      <p className="text-[12px] font-bold text-ink-secondary">
        그 달의 낙폭
        {deepest && (
          <span className="ml-2 text-[11px] font-medium text-ink-muted">
            가장 깊었던 날 {deepest.date} · {deepest.value.toFixed(2)}%
          </span>
        )}
      </p>
      {points.length === 0 ? (
        <p className="text-[11px] text-ink-faint">이 달의 낙폭 기록이 없습니다.</p>
      ) : (
        <SeriesChart
          points={points}
          height={160}
          includeZero
          valueFormat={(v) => `${v.toFixed(0)}%`}
          tooltipFormat={(p) => `${p.date} · ${p.value == null ? "—" : `${p.value.toFixed(2)}%`}`}
        />
      )}
    </div>
  );
}

/** 한 달의 계좌·지수 수익률(벤치마크 시계열에서). 초과수익은 수익률의 차이라 %p 다. */
function BenchMonthDetail({ row: m, names }: { row: BenchMonth; names: string[] }) {
  const ratio = (v: number | null) => (v == null ? null : String(v));
  return (
    <div className="space-y-3">
      <div className="flex items-baseline justify-between border-b border-hairline pb-2">
        {/* ⚠️위 '월 수익률'(성과분석)과 계산 경로가 다르다 — 지수와 같은 날짜로 맞춘 벤치마크
            시계열의 월말 ÷ 전월 말이다. 그래서 어느 값인지 이름에 적는다. */}
        <span className="text-[12px] text-ink-secondary">내 계좌 (지수와 같은 날짜 기준)</span>
        <span
          className={cn(
            "text-[20px] font-extrabold tabular-nums",
            toneOfRatio(ratio(m.portfolio)) === "up" && "text-bid",
            toneOfRatio(ratio(m.portfolio)) === "down" && "text-ask",
          )}
        >
          {pct(ratio(m.portfolio))}
        </span>
      </div>
      <DataTable columns={["지수", "원화 환산", "초과수익"]} align={["left", "right", "right"]}>
        {names.map((n) => {
          const b = m.benchmarks[n];
          const ex = m.portfolio != null && b != null ? String(m.portfolio - b) : null;
          return (
            <tr key={n} className="border-b border-hairline">
              <Cell left strong>
                {n}
              </Cell>
              <Cell tone={toneOfRatio(ratio(b))}>{pct(ratio(b))}</Cell>
              <Cell strong tone={toneOfRatio(ex)}>
                {ex == null ? "—" : `${pct(ex)}p`}
              </Cell>
            </tr>
          );
        })}
      </DataTable>
    </div>
  );
}
