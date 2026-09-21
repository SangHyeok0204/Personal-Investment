"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { PageContainer } from "@/components/layout/page-header";
import { Topbar } from "@/components/layout/topbar";
import { useAccount } from "@/components/layout/account-context";
import { useLiveQueryOptions } from "@/components/layout/auto-refresh-context";
import { SeriesChart } from "@/components/charts/series-chart";
import { Modal } from "@/components/ui/modal";
import {
  Cell,
  DataTable,
  NotConnectedBanner,
  StatTile,
  StubCard,
} from "@/components/stub";
import {
  getPerformanceAnalytics,
  type Contribution,
  type PerformanceAnalytics,
  type RiskMetrics,
} from "@/lib/api";
import { formatKrwSigned, formatKrwString } from "@/lib/format";
import { cn } from "@/lib/utils";

// 성과분석 — `ETF성과분석_양식_v2.html` 의 구성을 개인 계좌에 맞춰 옮긴 화면.
//
// 양식에는 BM/Peer 대비 초과성과와 상대 기여도가 있지만 **뺐다**. 개인 계좌에는
// 비교 기준이 정의돼 있지 않아서, 아무 지수나 골라 "초과수익 +3%" 라고 쓰면 그
// 숫자에 근거가 없다. 절대 기여도와 절대 위험지표만 낸다.
//
// ★한 페이지 안에 다 들어간다(스크롤 없음). 세부는 hover 로 알리고 click 으로
//   가운데 팝업을 띄운다 — 표를 길게 늘어놓는 대신.

/** 비율 문자열(0.0711) → "+7.11%". null 은 "—". */
function pct(value: string | null | undefined, digits = 2): string {
  if (value == null || value === "") return "—";
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  return `${n > 0 ? "+" : ""}${(n * 100).toFixed(digits)}%`;
}

/** 부호 없는 비율(변동성 등). 음수가 나올 수 없는 값에 + 를 붙이지 않는다. */
function pctPlain(value: string | null | undefined, digits = 2): string {
  if (value == null || value === "") return "—";
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  return `${(n * 100).toFixed(digits)}%`;
}

function num(value: string | null | undefined, digits = 2): string {
  if (value == null || value === "") return "—";
  const n = Number(value);
  return Number.isFinite(n) ? n.toFixed(digits) : "—";
}

function toneOfRatio(value: string | null | undefined): "up" | "down" | undefined {
  if (value == null || value === "") return undefined;
  const n = Number(value);
  if (!Number.isFinite(n) || n === 0) return undefined;
  return n > 0 ? "up" : "down";
}

export default function PerformanceAnalysisPage() {
  const { accountId } = useAccount();
  const live = useLiveQueryOptions();
  const [detail, setDetail] = useState<Contribution | null>(null);
  const [openRisk, setOpenRisk] = useState(false);
  const [openMonthly, setOpenMonthly] = useState(false);

  const { data, isLoading, isError } = useQuery({
    queryKey: ["performance-analytics", accountId],
    queryFn: () => getPerformanceAnalytics(accountId),
    ...live,
  });

  const connected = !isError && (data?.contributions.length ?? 0) > 0;
  const primaryRisk = data?.risk[0];

  return (
    <>
      <Topbar title="성과 분석" subtitle="기간수익률 · 위험지표 · 종목 기여도" />
      <PageContainer fit>
        {!connected && !isLoading && (
          <NotConnectedBanner what="일별 계좌 수익률" />
        )}

        <div className="grid shrink-0 grid-cols-2 gap-2.5 lg:grid-cols-4">
          {(data?.periods ?? [])
            .filter((p) => ["1개월", "3개월", "1년", "전체"].includes(p.label))
            .map((p) => (
              <StatTile
                key={p.label}
                label={`${p.label} 수익률`}
                value={p.return_ratio == null ? null : pct(p.return_ratio)}
                hint={
                  p.start_date
                    ? `${p.start_date} ~ ${p.end_date} · ${p.observations}일`
                    : undefined
                }
                accent="auto"
                loading={isLoading}
              />
            ))}
        </div>

        <div
          className={cn(
            "grid min-h-0 flex-1 gap-3",
            // 포트폴리오 화면과 같은 규칙 — auto-rows 를 1fr 로 묶어야 한 열일 때
            // 행이 내용 높이로 자라 페이지가 넘치지 않는다.
            "grid-cols-1 auto-rows-[minmax(0,1fr)]",
            "md:grid-cols-2 lg:auto-rows-auto",
            "lg:grid-cols-[minmax(0,1.15fr)_minmax(0,0.85fr)_minmax(0,1.2fr)]",
          )}
        >
          <DrawdownCard data={data} loading={isLoading} />
          <RiskCard
            risk={data?.risk ?? []}
            loading={isLoading}
            onOpen={() => setOpenRisk(true)}
          />
          <ContributionCard
            data={data}
            loading={isLoading}
            onPick={setDetail}
            onOpenMonthly={() => setOpenMonthly(true)}
          />
        </div>
      </PageContainer>

      <Modal
        open={openRisk}
        onClose={() => setOpenRisk(false)}
        title="기간별 위험지표"
        subtitle={
          data?.first_date ? `${data.first_date} ~ ${data.last_date}` : undefined
        }
      >
        <RiskDetail risk={data?.risk ?? []} shifts={data?.flow_shifts ?? []} />
      </Modal>

      <Modal
        open={openMonthly}
        onClose={() => setOpenMonthly(false)}
        title="월별 수익률"
        subtitle="일별 수익률을 그 달 안에서 곱해 누적한 값"
      >
        <MonthlyGrid data={data} />
      </Modal>

      <Modal
        open={detail != null}
        onClose={() => setDetail(null)}
        title={detail?.name ?? detail?.ticker ?? ""}
        subtitle={detail?.ticker}
      >
        {detail && <ContributionDetail item={detail} total={data} />}
      </Modal>
    </>
  );
}

// ── 낙폭 추이 ───────────────────────────────────────────────────────────────

function DrawdownCard({
  data,
  loading,
}: {
  data?: PerformanceAnalytics;
  loading: boolean;
}) {
  const points = useMemo(
    () =>
      (data?.drawdown ?? []).map((d) => ({
        date: d.base_date,
        value: Number(d.drawdown) * 100,
      })),
    [data],
  );
  const worst = data?.risk.find((r) => r.label === "전체");

  return (
    <StubCard
      title="낙폭(Drawdown) 추이"
      subtitle={
        worst?.max_drawdown
          ? `최대 ${pct(worst.max_drawdown)} (${worst.max_drawdown_trough_date})`
          : undefined
      }
    >
      {loading ? (
        <Placeholder text="불러오는 중" />
      ) : points.length === 0 ? (
        <Placeholder text="일별 수익률이 없습니다" />
      ) : (
        <div className="flex h-full flex-col">
          {/* 낙폭은 항상 0 이하 — 0 을 축에 포함해야 '얼마나 빠졌는지'가 읽힌다. */}
          <SeriesChart
            points={points}
            height={200}
            includeZero
            valueFormat={(v) => `${v.toFixed(0)}%`}
            tooltipFormat={(p) =>
              `${p.date} · ${p.value == null ? "—" : `${p.value.toFixed(2)}%`}`
            }
          />
          <p className="mt-auto pt-2 text-[11px] leading-snug text-ink-muted">
            고점 대비 하락률. 입출금은 수익률에서 제외한 뒤 계산한다.
          </p>
        </div>
      )}
    </StubCard>
  );
}

// ── 위험지표 요약 ───────────────────────────────────────────────────────────

const RISK_ROWS: { key: keyof RiskMetrics; label: string; kind: "pct" | "num" }[] = [
  { key: "annualized_return", label: "연환산 수익률", kind: "pct" },
  { key: "volatility", label: "연환산 변동성", kind: "num" },
  { key: "max_drawdown", label: "최대낙폭", kind: "pct" },
  { key: "sharpe", label: "샤프", kind: "num" },
  { key: "hit_ratio", label: "승률", kind: "num" },
];

function RiskCard({
  risk,
  loading,
  onOpen,
}: {
  risk: RiskMetrics[];
  loading: boolean;
  onOpen: () => void;
}) {
  const primary = risk[0];
  return (
    <StubCard
      title="위험지표"
      subtitle={primary ? primary.label : undefined}
      action={
        <button
          type="button"
          onClick={onOpen}
          className="rounded-full bg-white/15 px-2.5 py-1 text-[11px] font-bold text-white transition-colors hover:bg-white/25"
        >
          기간별 보기
        </button>
      }
    >
      {loading ? (
        <Placeholder text="불러오는 중" />
      ) : !primary ? (
        <Placeholder text="계산할 데이터가 없습니다" />
      ) : (
        <dl className="flex h-full flex-col justify-between gap-1">
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
                className="flex items-baseline justify-between border-b border-hairline py-1.5 last:border-b-0"
              >
                <dt className="text-[12px] font-medium text-ink-secondary">
                  {row.label}
                </dt>
                <dd
                  className={cn(
                    "text-[15px] font-bold tabular-nums",
                    row.key === "max_drawdown" && "text-ask",
                    row.key === "annualized_return" &&
                      toneOfRatio(raw) === "up" &&
                      "text-bid",
                    row.key === "annualized_return" &&
                      toneOfRatio(raw) === "down" &&
                      "text-ask",
                  )}
                >
                  {text}
                </dd>
              </div>
            );
          })}
        </dl>
      )}
    </StubCard>
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
              <Cell key={r.label}>
                {(render as (r: RiskMetrics) => string)(r)}
              </Cell>
            ))}
          </tr>
        ))}
      </DataTable>

      <p className="text-[11px] leading-relaxed text-ink-muted">
        연환산 수익률·샤프·소르티노는 <strong>관측 기간이 1년 미만이면 내지
        않는다</strong>. 짧은 기간을 연으로 환산하면 숫자만 부풀려진다.
        무위험수익률은 0% 로 둔다.
      </p>

      {shifts.length > 0 && (
        // 계산을 위해 원본 데이터를 건드렸다면 그 사실을 숨기지 않는다.
        <div className="rounded-xl border border-amber-200 bg-amber-50 px-3.5 py-3">
          <p className="text-[12px] font-bold text-amber-900">
            입출금 기록일 보정 {shifts.length}건
          </p>
          <p className="mt-1 text-[11px] leading-snug text-amber-800">
            증권사가 입금을 자산 반영일보다 하루 늦게 기록한 건이다. 그대로 두면
            입금이 하루짜리 수익으로 잡혀 변동성과 낙폭이 실제보다 훨씬 커진다.
          </p>
          <ul className="mt-2 space-y-0.5">
            {shifts.map((s) => (
              <li
                key={`${s.moved_from}-${s.amount}`}
                className="text-[11px] tabular-nums text-amber-900"
              >
                {s.moved_from} → {s.moved_to} · {formatKrwString(s.amount)}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

// ── 종목별 기여도 ───────────────────────────────────────────────────────────

function ContributionCard({
  data,
  loading,
  onPick,
  onOpenMonthly,
}: {
  data?: PerformanceAnalytics;
  loading: boolean;
  onPick: (c: Contribution) => void;
  onOpenMonthly: () => void;
}) {
  const items = data?.contributions ?? [];
  return (
    <StubCard
      title="종목별 기여도"
      subtitle={
        data?.total_return
          ? `합계 ${pct(data.total_return)} = 평가수익률`
          : undefined
      }
      scrollBody
      action={
        <button
          type="button"
          onClick={onOpenMonthly}
          className="rounded-full bg-white/15 px-2.5 py-1 text-[11px] font-bold text-white transition-colors hover:bg-white/25"
        >
          월별 수익률
        </button>
      }
    >
      {loading ? (
        <Placeholder text="불러오는 중" />
      ) : (
        <DataTable
          columns={["종목", "비중", "손익", "기여도"]}
          empty="보유 종목이 없습니다"
        >
          {items.map((c) => (
            <tr
              key={c.asset_id}
              onClick={() => onPick(c)}
              className="cursor-pointer border-b border-hairline transition-colors hover:bg-canvas-soft"
            >
              <Cell left strong>
                <span className="flex items-center gap-1.5">
                  <span className="truncate">{c.name ?? c.ticker}</span>
                  <span className="shrink-0 text-[10px] font-bold text-ink-faint">
                    {c.ticker}
                  </span>
                </span>
              </Cell>
              <Cell>{pctPlain(c.weight, 1)}</Cell>
              <Cell tone={toneOfRatio(c.unrealized_pnl_krw)}>
                {formatKrwSigned(c.unrealized_pnl_krw)}
              </Cell>
              <Cell strong tone={toneOfRatio(c.contribution)}>
                {pct(c.contribution)}
              </Cell>
            </tr>
          ))}
        </DataTable>
      )}
    </StubCard>
  );
}

function ContributionDetail({
  item,
  total,
}: {
  item: Contribution;
  total?: PerformanceAnalytics;
}) {
  const rows: [string, string][] = [
    ["섹터", item.sector ?? "미분류"],
    ["AI/Tech 대분류", item.tech_l1 ?? "미분류"],
    ["비중", pctPlain(item.weight, 2)],
    ["매입원가", formatKrwString(item.purchase_krw)],
    ["평가금액", formatKrwString(item.market_value_krw)],
    ["평가손익", formatKrwSigned(item.unrealized_pnl_krw)],
    ["종목 수익률", pct(item.unrealized_return)],
    ["누적 배당", item.dividend_krw ? formatKrwString(item.dividend_krw) : "—"],
    ["포트폴리오 기여도", pct(item.contribution)],
  ];
  return (
    <div className="space-y-3">
      <dl className="grid grid-cols-2 gap-x-5 gap-y-0">
        {rows.map(([label, value]) => (
          <div
            key={label}
            className="flex items-baseline justify-between border-b border-hairline py-2"
          >
            <dt className="text-[12px] text-ink-secondary">{label}</dt>
            <dd className="text-[13px] font-bold tabular-nums text-ink">
              {value}
            </dd>
          </div>
        ))}
      </dl>
      <p className="text-[11px] leading-relaxed text-ink-muted">
        기여도 = 이 종목의 평가손익 ÷ <strong>전체 매입원가</strong>
        {total?.total_purchase_krw
          ? ` (${formatKrwString(total.total_purchase_krw)})`
          : ""}
        . 모든 종목의 기여도를 더하면 포트폴리오 평가수익률
        {total?.total_return ? ` ${pct(total.total_return)}` : ""} 과 같아진다.
        배당은 이미 받은 현금이라 성격이 달라 기여도에 넣지 않고 따로 보여 준다.
      </p>
    </div>
  );
}

// ── 월별 수익률 ─────────────────────────────────────────────────────────────

function MonthlyGrid({ data }: { data?: PerformanceAnalytics }) {
  const byYear = useMemo(() => {
    const out = new Map<string, Map<number, string>>();
    for (const m of data?.monthly ?? []) {
      const [year, month] = m.month.split("-");
      if (!out.has(year)) out.set(year, new Map());
      out.get(year)!.set(Number(month), m.return_ratio);
    }
    return [...out.entries()];
  }, [data]);

  if (byYear.length === 0) {
    return <Placeholder text="월별 수익률이 없습니다" />;
  }

  return (
    <div className="space-y-4">
      <DataTable
        columns={["연도", ...Array.from({ length: 12 }, (_, i) => `${i + 1}월`)]}
      >
        {byYear.map(([year, months]) => (
          <tr key={year} className="border-b border-hairline">
            <Cell left strong>
              {year}
            </Cell>
            {Array.from({ length: 12 }, (_, i) => i + 1).map((m) => {
              const v = months.get(m);
              return (
                <Cell key={m} tone={toneOfRatio(v)} className="px-2">
                  {v == null ? "·" : pct(v, 1)}
                </Cell>
              );
            })}
          </tr>
        ))}
      </DataTable>
      <p className="text-[11px] leading-relaxed text-ink-muted">
        그 달의 일별 수익률을 <strong>곱해서</strong> 누적한 값이다(단순 합이
        아니다). 거래일이 없는 달은 · 로 둔다 — 0% 와 다른 상태다.
      </p>
    </div>
  );
}

function Placeholder({ text }: { text: string }) {
  return (
    <div className="flex h-full items-center justify-center">
      <span className="text-[12px] font-semibold text-ink-faint">{text}</span>
    </div>
  );
}
