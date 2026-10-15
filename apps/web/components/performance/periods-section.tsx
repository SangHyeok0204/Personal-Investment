"use client";

import { useState } from "react";
import { Modal } from "@/components/ui/modal";
import { CardEmpty, Cell, DataTable, StatTile, StubCard } from "@/components/stub";
import type { BenchmarkPeriod, PerformanceAnalytics, RiskMetrics } from "@/lib/api";
import { formatKrwString } from "@/lib/format";
import { cn } from "@/lib/utils";
import { num, pct, pctPlain, shortName, toneOfRatio } from "./format";
import { useAnalytics, useBenchmark } from "./queries";

// 4. 기간별 — 옛 벤치마크 '기간별' 표 + 옛 성과 분석 '기간별 위험지표'.
//
// ★2026-10-15 한 화면 통합: 둘 다 팝업 안에 있던 것을 본문으로 꺼냈다(이제 화면이 스크롤된다).
//   · 기간별 수익률 표 — 벤치마크 API. 행을 누르면 USD 기준·환율 효과(옛 팝업 그대로).
//   · 1개월·3개월·1년 칸 — 옛 성과 분석 상단 칸(성과분석 API). 둘 다 '참고: 시간가중(TWR)'이지만
//     **계산 경로가 다르다**: 성과분석은 입출금 기록일을 보정한 일별 연쇄, 벤치마크 표는 지수가
//     있는 날만 골라 두 날의 수준 비. 같은 값이라고 확인되지 않아 둘 다 남긴다.
//   ⚠️옛 성과 분석의 '최대낙폭 (참고 TWR)' 칸은 걷었다 — 같은 값(전체 구간 최대낙폭)이 오른쪽
//     위험지표 표와 아래 낙폭 섹션 제목에 있다. 그 칸 힌트(대표 기간 변동성·샤프)는 표 위 요약에 있다.
//
// ⚠️양식(ETF성과분석_양식)에는 BM 대비 상대 위험지표도 있지만 넣지 않았다 — 위험지표는 절대값만.


export function PeriodsSection() {
  const analytics = useAnalytics();
  const benchmark = useBenchmark();
  const [picked, setPicked] = useState<BenchmarkPeriod | null>(null);
  const data = analytics.data;
  const names = benchmark.data?.benchmarks ?? [];
  const primaryRisk = data?.risk[0];

  return (
    <section id="periods" className="scroll-mt-28 space-y-3">
      {/* 참고 — 일별 연쇄 수익률(TWR). 맨 위 '내 계좌'(정본)와 정의가 다르다. */}
      <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-3">
        {(data?.periods ?? [])
          .filter((p) => ["1개월", "3개월", "1년"].includes(p.label))
          .map((p) => (
            <StatTile
              key={p.label}
              label={`${p.label} (참고 TWR)`}
              value={p.return_ratio == null ? null : pct(p.return_ratio)}
              hint={
                p.start_date
                  ? `시간가중 · ${p.start_date.slice(5)}~${p.end_date?.slice(5)}`
                  : "시간가중(TWR)"
              }
              accent="auto"
              loading={analytics.isLoading}
            />
          ))}
      </div>

      <div className="grid grid-cols-1 gap-3 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)]">
        <StubCard
          title="기간별 수익률"
          subtitle="참고: 시간가중(TWR) · 원화 환산 기준 · 행을 누르면 USD 기준·환율 효과"
        >
          {benchmark.isLoading ? (
            <div className="h-[200px]">
              <CardEmpty text="불러오는 중…" />
            </div>
          ) : (
            <DataTable
              // ⚠️`DataTable` 은 컬럼명을 그대로 key 로 쓴다. 길다고 잘라 쓰면
              //   "S&P 500"(7자)과 "필라델피아 반도체"가 **둘 다 "반도체"**가 되어
              //   중복 key 경고가 나고 헤더도 같은 글자가 두 번 찍혔다(실제로 그랬다).
              //   축약은 이름별로 따로 정한다.
              columns={["기간", "내 계좌", ...names.map(shortName)]}
              align={["left", "right", ...names.map(() => "right" as const)]}
              empty="데이터가 없습니다"
            >
              {(benchmark.data?.periods ?? []).map((p) => (
                <tr
                  key={p.label}
                  onClick={() => setPicked(p)}
                  className="cursor-pointer border-b border-hairline transition-colors hover:bg-canvas-soft"
                >
                  <Cell left strong>
                    {p.label}
                  </Cell>
                  <Cell strong tone={toneOfRatio(p.portfolio)}>
                    {pct(p.portfolio)}
                  </Cell>
                  {names.map((n) => (
                    <Cell key={n} tone={toneOfRatio(p.benchmarks_krw[n])}>
                      {pct(p.benchmarks_krw[n])}
                    </Cell>
                  ))}
                </tr>
              ))}
            </DataTable>
          )}
        </StubCard>

        <StubCard
          title="기간별 위험지표"
          subtitle={
            data?.first_date
              ? `참고: 시간가중(TWR) 일별 수익률 · ${data.first_date} ~ ${data.last_date}`
              : "참고: 시간가중(TWR) 일별 수익률"
          }
        >
          {analytics.isLoading ? (
            <div className="h-[200px]">
              <CardEmpty text="불러오는 중…" />
            </div>
          ) : (
            <div className="space-y-4">
              {primaryRisk && <RiskSummary primary={primaryRisk} />}
              <RiskDetail risk={data?.risk ?? []} shifts={data?.flow_shifts ?? []} />
            </div>
          )}
        </StubCard>
      </div>

      <Modal
        open={picked != null}
        onClose={() => setPicked(null)}
        title={`${picked?.label ?? ""} 비교`}
        subtitle={
          picked
            ? `${picked.start_date} ~ ${picked.end_date} · ${picked.observations}일 · 참고: 시간가중(TWR)`
            : undefined
        }
      >
        {picked && <PeriodDetail period={picked} names={names} />}
      </Modal>
    </section>
  );
}

function PeriodDetail({ period: p, names }: { period: BenchmarkPeriod; names: string[] }) {
  return (
    <div className="space-y-3">
      <div className="flex items-baseline justify-between border-b border-hairline pb-2">
        <span className="text-[12px] text-ink-secondary">내 계좌</span>
        <span
          className={cn(
            "text-[20px] font-extrabold tabular-nums",
            toneOfRatio(p.portfolio) === "up" && "text-bid",
            toneOfRatio(p.portfolio) === "down" && "text-ask",
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
          const fx = krw != null && usd != null ? (Number(krw) - Number(usd)).toFixed(4) : null;
          return (
            <tr key={n} className="border-b border-hairline">
              <Cell left strong>
                {n}
              </Cell>
              <Cell strong tone={toneOfRatio(krw)}>
                {pct(krw)}
              </Cell>
              <Cell tone={toneOfRatio(usd)}>{pct(usd)}</Cell>
              <Cell tone={toneOfRatio(fx)}>{fx == null ? "—" : `${pct(fx)}p`}</Cell>
              <Cell strong tone={toneOfRatio(p.excess[n])}>
                {pct(p.excess[n])}
              </Cell>
            </tr>
          );
        })}
      </DataTable>
    </div>
  );
}

// ── 위험지표 ────────────────────────────────────────────────────────────────

const RISK_ROWS: { key: keyof RiskMetrics; label: string }[] = [
  { key: "annualized_return", label: "연환산 수익률" },
  { key: "volatility", label: "연환산 변동성" },
  { key: "max_drawdown", label: "최대낙폭" },
  { key: "sharpe", label: "샤프" },
  { key: "hit_ratio", label: "승률" },
];

/** 연환산이 필요한 지표는 1년치가 모여야 낸다. 서버의 TRADING_DAYS_PER_YEAR. */
const TRADING_DAYS_PER_YEAR = 252;

/** 빈 칸에 **왜 비었는지**를 적는다.
 *
 * ⚠️'—' 만 있으면 고장으로 읽힌다. 실제로 연환산 수익률과 샤프가 나란히
 *   비어 있었는데, 이유는 "3개월 수익률을 4제곱해 연 +180% 라고 쓰지 않는다"
 *   는 **의도된 규칙**이었다. 규칙을 화면이 말하지 않으면 없는 것과 같다.
 */
function missingReason(key: keyof RiskMetrics, r: RiskMetrics): string | null {
  if (key !== "annualized_return" && key !== "sharpe") return null;
  if (r.observations >= TRADING_DAYS_PER_YEAR) return null;
  return `1년치부터 (${r.observations}/${TRADING_DAYS_PER_YEAR}일)`;
}

/** 대표 기간 하나의 지표 다섯. 표 위에 둔다. */
function RiskSummary({ primary }: { primary: RiskMetrics }) {
  return (
    <div className="rounded-xl bg-canvas-soft/70 p-3">
      <p className="mb-1 text-[12px] font-extrabold text-ge-navy">{primary.label}</p>
      <dl className="grid grid-cols-1 gap-x-5 sm:grid-cols-2">
        {RISK_ROWS.map((row) => {
          const raw = primary[row.key] as string | null;
          const text =
            raw == null
              ? "—"
              : row.key === "sharpe"
                ? num(raw)
                : row.key === "volatility" || row.key === "hit_ratio"
                  ? pctPlain(raw)
                  : pct(raw);
          return (
            <div
              key={row.label}
              className="flex items-baseline justify-between border-b border-hairline py-1.5"
            >
              <dt className="text-[12px] font-medium text-ink-secondary">
                {row.label}
                {raw == null && missingReason(row.key, primary) && (
                  <span className="ml-1.5 text-[10px] font-semibold text-ink-faint">
                    {missingReason(row.key, primary)}
                  </span>
                )}
              </dt>
              <dd
                className={cn(
                  "text-[15px] font-bold tabular-nums",
                  row.key === "max_drawdown" && "text-ask",
                  row.key === "annualized_return" && toneOfRatio(raw) === "up" && "text-bid",
                  row.key === "annualized_return" && toneOfRatio(raw) === "down" && "text-ask",
                )}
              >
                {text}
              </dd>
            </div>
          );
        })}
      </dl>
    </div>
  );
}

function RiskDetail({
  risk,
  shifts,
}: {
  risk: RiskMetrics[];
  shifts: PerformanceAnalytics["flow_shifts"];
}) {
  return (
    <div className="space-y-4">
      <DataTable
        columns={["지표", ...risk.map((r) => r.label)]}
        align={["left", ...risk.map(() => "right" as const)]}
      >
        {[
          ["관측일수", (r: RiskMetrics) => `${r.observations}일`],
          ["연환산 수익률", (r: RiskMetrics) => pct(r.annualized_return)],
          ["연환산 변동성", (r: RiskMetrics) => pctPlain(r.volatility)],
          ["하방 변동성", (r: RiskMetrics) => pctPlain(r.downside_volatility)],
          ["최대낙폭", (r: RiskMetrics) => pct(r.max_drawdown)],
          [
            "낙폭 구간",
            (r: RiskMetrics) =>
              r.max_drawdown_peak_date
                ? `${r.max_drawdown_peak_date} → ${r.max_drawdown_trough_date}`
                : "—",
          ],
          ["샤프", (r: RiskMetrics) => num(r.sharpe)],
          ["소르티노", (r: RiskMetrics) => num(r.sortino)],
          ["승률", (r: RiskMetrics) => pctPlain(r.hit_ratio)],
        ].map(([label, render]) => (
          <tr key={label as string} className="border-b border-hairline">
            <Cell left strong>
              {label as string}
            </Cell>
            {risk.map((r) => (
              <Cell key={r.label}>{(render as (r: RiskMetrics) => string)(r)}</Cell>
            ))}
          </tr>
        ))}
      </DataTable>

      {shifts.length > 0 && (
        // 계산을 위해 원본 데이터를 건드렸다면 그 사실을 숨기지 않는다.
        <div className="rounded-xl border border-amber-200 bg-amber-50 px-3.5 py-3">
          <p className="text-[12px] font-bold text-amber-900">입출금 기록일 보정 {shifts.length}건</p>
          <ul className="mt-2 space-y-0.5">
            {shifts.map((s) => (
              <li key={`${s.moved_from}-${s.amount}`} className="text-[11px] tabular-nums text-amber-900">
                {s.moved_from} → {s.moved_to} · {formatKrwString(s.amount)}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
