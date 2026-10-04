"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { PageContainer } from "@/components/layout/page-header";
import { Topbar } from "@/components/layout/topbar";
import { useAccount } from "@/components/layout/account-context";
import { useLiveQueryOptions } from "@/components/layout/auto-refresh-context";
import { SeriesChart } from "@/components/charts/series-chart";
import { SignedBarChart } from "@/components/charts/signed-bar-chart";
import { Modal } from "@/components/ui/modal";
import {
  Cell,
  DataTable,
  NotConnectedBanner,
  StatTile,
  StubCard,
} from "@/components/stub";
import {
  getAccountReturn,
  getPerformanceAnalytics,
  type AccountReturn,
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
//
// ⚠️2026-09-22: 이 화면에도 **기준이 다른 숫자가 섞여 있었다.** 상단은
//   '전체 수익률 −1.98%', 오른쪽은 '합계 +8.64% = 평가수익률'. 부호가 반대라
//   "종목은 다 잘했는데 왜 전체는 마이너스냐"로 읽힌다. 셋이 다르다:
//     · 기간    기간수익률은 조회 구간, 기여도는 **매입 시점 이후**
//     · 범위    기간수익률은 계좌 전체(판 것·배당·예수금 포함),
//               기여도는 **지금 들고 있는 종목만**
//     · 통화    기간수익률은 예탁자산 기반이라 **원화 기준**(환율 포함),
//               기여도는 원가·평가액 모두 오늘 환율로 환산해 **주가 기준**
//   실측으로 같은 가족끼리는 맞는다 — 주가 기준 +7.25%(수익률 추이의 연쇄
//   수익률) vs +8.64%, 원화 기준 −1.86% vs −1.98%.
//   숫자를 고치는 게 아니라 **기준을 화면에 적는다.**
//
// ★2026-09-25 사용자 지시(전체 메뉴 공통 패턴): 화면에는 대표 숫자, 누르면 상세.
//   위험지표 카드와 종목 기여도 표는 **칸**(최대낙폭 · 기여도 합계)으로 줄이고 누르면
//   팝업으로 뜬다. 팝업 안에 있던 월별 수익률은 본문의 **월별 막대**로 꺼냈다 —
//   막대를 누르면 그 달, 헤더 '전체 목록'은 옛 연×월 표다. 낙폭은 일별 추이라 선.
//
// ★2026-10-04 사용자 지정: 첫 칸과 왼쪽 기본 그래프는 **내 계좌 수익률**(/account-return —
//   시작일 이후 손익 ÷ 투입 원금, 6/01~)이다. 옛 '전체 수익률'(연쇄 TWR)은 지웠고,
//   1·3개월·1년 칸·월별 막대·낙폭·위험지표는 일별 연쇄 수익률이라 '참고: 시간가중(TWR)'
//   으로 적어 둔다 — 두 정의를 한 칸에 섞지 않는다.

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
  const [openContrib, setOpenContrib] = useState(false);
  const [pickedMonth, setPickedMonth] = useState<string | null>(null);

  const { data, isLoading, isError } = useQuery({
    queryKey: ["performance-analytics", accountId],
    queryFn: () => getPerformanceAnalytics(accountId),
    ...live,
  });
  const account = useQuery({
    queryKey: ["account-return", accountId],
    queryFn: () => getAccountReturn(accountId),
    ...live,
  });
  const acct = account.data;

  const connected = !isError && (data?.contributions.length ?? 0) > 0;
  const primaryRisk = data?.risk[0];
  const worst = data?.risk.find((r) => r.label === "전체");

  const monthColumns = useMemo(
    () =>
      [...(data?.monthly ?? [])]
        .sort((a, b) => a.month.localeCompare(b.month))
        .map((m) => ({ key: m.month, label: m.month, value: Number(m.return_ratio) * 100 })),
    [data],
  );
  const monthPicked = data?.monthly.find((m) => m.month === pickedMonth) ?? null;

  return (
    <>
      <Topbar
        title="성과 분석"
        subtitle="내 계좌 수익률 · 참고: 시간가중(TWR) 위험지표 · 종목 기여도(주가 기준)"
      />
      <PageContainer fit>
        {!connected && !isLoading && (
          <NotConnectedBanner what="일별 계좌 수익률" />
        )}

        <div className="grid shrink-0 grid-cols-2 gap-2.5 md:grid-cols-3 xl:grid-cols-6">
          {/* ★정본 — 시작일 이후 손익 ÷ 투입 원금. */}
          <StatTile
            label="내 계좌 수익률"
            value={acct?.return_ratio == null ? null : pct(acct.return_ratio)}
            // 보조: 원화 실질(환차 포함, 총자산 − 원금). 위 값은 환율 제외(키움 손익).
            hint={[
              acct?.krw_return_ratio != null ? `원화 실질 ${pct(acct.krw_return_ratio)}` : null,
              acct?.return_date
                ? `~${acct.return_date.slice(5)}`
                : "시작일 이후 손익 ÷ 투입 원금",
            ]
              .filter(Boolean)
              .join(" · ")}
            accent="auto"
            loading={account.isLoading}
          />
          {/* 참고 — 일별 연쇄 수익률(TWR). 위 정본과 정의가 다르다. */}
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
                loading={isLoading}
              />
            ))}
          {/* 옛 위험지표 카드의 대표값. 나머지 지표는 팝업에서. */}
          <StatTile
            label="최대낙폭 (참고 TWR)"
            value={worst?.max_drawdown == null ? null : pct(worst.max_drawdown)}
            hint={
              primaryRisk
                ? `${primaryRisk.label} 변동성 ${pctPlain(primaryRisk.volatility)} · 샤프 ${num(primaryRisk.sharpe)}`
                : "고점 대비 하락"
            }
            accent="down"
            actionHint="눌러서 위험지표 보기"
            onClick={() => setOpenRisk(true)}
            loading={isLoading}
          />
          {/* ⚠️기준이 다른 숫자다 — 보유분 · 매입 이후 · 주가 기준. 옆 칸들(원화
              기준 기간수익률)과 더하거나 견주지 않도록 힌트에 기준을 적는다. */}
          <StatTile
            label="종목 기여도 합계"
            value={data?.total_return ? pct(data.total_return) : null}
            hint={`보유분 · 매입 이후 · 주가 기준 · ${data?.contributions.length ?? 0}종목`}
            accent="auto"
            actionHint="눌러서 종목별 보기"
            onClick={() => setOpenContrib(true)}
            loading={isLoading}
          />
        </div>

        <div
          className={cn(
            "grid min-h-0 flex-1 gap-3",
            // 포트폴리오 화면과 같은 규칙 — auto-rows 를 1fr 로 묶어야 한 열일 때
            // 행이 내용 높이로 자라 페이지가 넘치지 않는다.
            "grid-cols-1 auto-rows-[minmax(0,1fr)]",
            "md:grid-cols-2 lg:auto-rows-auto",
            "lg:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)]",
          )}
        >
          <MainChartCard
            data={data}
            loading={isLoading}
            account={acct}
            accountLoading={account.isLoading}
          />
          <StubCard
            title="월별 수익률"
            subtitle="참고: 시간가중(TWR) · 원화 기준 · 막대를 누르면 그 달"
            scrollBody
            action={
              <button
                type="button"
                onClick={() => setOpenMonthly(true)}
                className="rounded-full bg-white/15 px-2.5 py-1 text-[11px] font-bold text-white transition-colors hover:bg-white/25"
              >
                전체 목록
              </button>
            }
          >
            {isLoading ? (
              <Placeholder text="불러오는 중" />
            ) : (
              <SignedBarChart
                columns={monthColumns}
                height={220}
                formatValue={(v) => `${v > 0 ? "+" : ""}${v.toFixed(2)}%`}
                selected={pickedMonth}
                onPick={setPickedMonth}
              />
            )}
          </StubCard>
        </div>
      </PageContainer>

      <Modal
        open={openRisk}
        onClose={() => setOpenRisk(false)}
        title="기간별 위험지표"
        subtitle={
          data?.first_date
            ? `참고: 시간가중(TWR) 일별 수익률 · ${data.first_date} ~ ${data.last_date}`
            : "참고: 시간가중(TWR) 일별 수익률"
        }
      >
        <div className="space-y-4">
          {primaryRisk && <RiskSummary primary={primaryRisk} />}
          <RiskDetail risk={data?.risk ?? []} shifts={data?.flow_shifts ?? []} />
        </div>
      </Modal>

      <Modal
        open={openMonthly}
        onClose={() => setOpenMonthly(false)}
        title="월별 수익률"
        subtitle="참고: 시간가중(TWR) — 일별 수익률을 그 달 안에서 곱해 누적한 값"
      >
        <MonthlyGrid data={data} />
      </Modal>

      <Modal
        open={openContrib}
        onClose={() => setOpenContrib(false)}
        title="종목별 기여도"
        subtitle={
          data?.total_return
            ? `합계 ${pct(data.total_return)} · 보유분 · 매입 이후 · 주가 기준`
            : "보유분 · 매입 이후 · 주가 기준"
        }
        width={680}
      >
        <ContributionTable data={data} onPick={setDetail} />
      </Modal>

      {/* ── 막대 → 그 달 ───────────────────────────────────────────────── */}
      <Modal
        open={monthPicked != null}
        onClose={() => setPickedMonth(null)}
        title={monthPicked ? `${monthPicked.month} 수익률` : ""}
        subtitle="참고: 시간가중(TWR) · 원화 기준 · 일별 수익률을 그 달 안에서 곱해 누적"
        width={620}
      >
        {monthPicked && <MonthDetail month={monthPicked.month} ratio={monthPicked.return_ratio} data={data} />}
      </Modal>

      <Modal
        open={detail != null}
        onClose={() => setDetail(null)}
        title={detail?.name ?? detail?.ticker ?? ""}
        subtitle={detail?.ticker}
      >
        {detail && <ContributionDetail item={detail} />}
      </Modal>
    </>
  );
}

// ── 왼쪽 그래프 — 내 계좌 수익률(기본) · 낙폭(참고 TWR) ──────────────────────

function MainChartCard({
  data,
  loading,
  account,
  accountLoading,
}: {
  data?: PerformanceAnalytics;
  loading: boolean;
  account?: AccountReturn;
  accountLoading: boolean;
}) {
  const [view, setView] = useState<"return" | "drawdown">("return");
  const toggle = (
    <div className="flex gap-1">
      {(
        [
          ["return", "수익률"],
          ["drawdown", "낙폭(참고 TWR)"],
        ] as const
      ).map(([id, text]) => (
        <button
          key={id}
          type="button"
          onClick={() => setView(id)}
          aria-pressed={view === id}
          className={cn(
            "rounded px-1.5 py-0.5 text-[10px] font-bold transition-colors",
            view === id
              ? "bg-white/90 text-ge-header"
              : "text-white/60 hover:bg-white/15 hover:text-white",
          )}
        >
          {text}
        </button>
      ))}
    </div>
  );
  return view === "drawdown" ? (
    <DrawdownCard data={data} loading={loading} action={toggle} />
  ) : (
    <AccountReturnCard data={account} loading={accountLoading} action={toggle} />
  );
}

function AccountReturnCard({
  data,
  loading,
  action,
}: {
  data?: AccountReturn;
  loading: boolean;
  action: React.ReactNode;
}) {
  const points = useMemo(
    () =>
      (data?.items ?? []).map((p) => ({
        date: p.date,
        value: p.return_ratio == null ? null : Number(p.return_ratio) * 100,
      })),
    [data],
  );
  return (
    <StubCard
      title="내 계좌 수익률 추이"
      subtitle={data ? `${data.start} 부터 · 손익 ÷ 투입 원금` : undefined}
      action={action}
    >
      {loading ? (
        <Placeholder text="불러오는 중" />
      ) : points.length === 0 ? (
        <Placeholder text="수익률이 없습니다" />
      ) : (
        <div className="flex h-full flex-col">
          <SeriesChart
            points={points}
            height={200}
            includeZero
            valueFormat={(v) => `${v.toFixed(0)}%`}
            tooltipFormat={(p) =>
              `${p.value == null ? "—" : `${p.value > 0 ? "+" : ""}${p.value.toFixed(2)}%`}`
            }
          />
          <p className="mt-auto pt-2 text-[11px] leading-snug text-ink-muted">
            입금은 원금만 올린다 — 손익은 그대로 · 모르는 날은 비워 둔다
          </p>
        </div>
      )}
    </StubCard>
  );
}

// ── 낙폭 추이 ───────────────────────────────────────────────────────────────

function DrawdownCard({
  data,
  loading,
  action,
}: {
  data?: PerformanceAnalytics;
  loading: boolean;
  action?: React.ReactNode;
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
          ? `참고: 시간가중(TWR) · 최대 ${pct(worst.max_drawdown)} (${worst.max_drawdown_trough_date})`
          : "참고: 시간가중(TWR)"
      }
      action={action}
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
            고점 대비 하락률 · 입출금 제외
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

/** 옛 위험지표 카드의 본문 — 대표 기간 하나의 지표 다섯. 팝업 맨 위에 둔다. */
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
              <Cell key={r.label}>
                {(render as (r: RiskMetrics) => string)(r)}
              </Cell>
            ))}
          </tr>
        ))}
      </DataTable>

      {shifts.length > 0 && (
        // 계산을 위해 원본 데이터를 건드렸다면 그 사실을 숨기지 않는다.
        <div className="rounded-xl border border-amber-200 bg-amber-50 px-3.5 py-3">
          <p className="text-[12px] font-bold text-amber-900">
            입출금 기록일 보정 {shifts.length}건
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

function ContributionTable({
  data,
  onPick,
}: {
  data?: PerformanceAnalytics;
  onPick: (c: Contribution) => void;
}) {
  const items = data?.contributions ?? [];
  return (
    <div className="max-h-[60vh] overflow-y-auto">
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
                <span className="max-w-[240px] truncate">{c.name ?? c.ticker}</span>
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
    </div>
  );
}

function ContributionDetail({ item }: { item: Contribution }) {
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
    </div>
  );
}

// ── 월별 수익률 ─────────────────────────────────────────────────────────────

/** 막대 하나의 상세 — 그 달 수익률과, 그 달 안의 낙폭 추이. */
function MonthDetail({
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
      <p className="text-[12px] font-extrabold text-ge-navy">
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
          tooltipFormat={(p) =>
            `${p.date} · ${p.value == null ? "—" : `${p.value.toFixed(2)}%`}`
          }
        />
      )}
    </div>
  );
}

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
