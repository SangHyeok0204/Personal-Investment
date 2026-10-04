"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { PageContainer } from "@/components/layout/page-header";
import { Topbar } from "@/components/layout/topbar";
import { useAccount } from "@/components/layout/account-context";
import { Modal } from "@/components/ui/modal";
import {
  CardEmpty,
  Cell,
  DataTable,
  Emphasized,
  NotConnectedBanner,
  StatTile,
  StubCard,
} from "@/components/stub";
import { accountReturnOn, getAccountReturn, getReport, type Report } from "@/lib/api";
import {
  formatKrwCompactString,
  formatKrwSigned,
  formatKrwString,
  formatPercentString,
} from "@/lib/format";
import { cn } from "@/lib/utils";

// 기간 리포트 — 그 기간에 무슨 일이 있었나.
//
// ★다른 화면과 겹치지 않는 부분은 **기간을 고른다**는 것이다. 성과 분석은
//   전체를, 월별 현금흐름은 흐름만 본다. 여기는 한 달/분기/연도를 잘라
//   자산 변화 · 수익률 · 매매 · 실현손익 · 신규/청산을 한 장에 모은다.
//
// ⚠️**기간별 평가 기여도를 만들지 않는다.** 종목별로 "이번 달 얼마 기여했나"를
//   내려면 보유 종목의 일별 시계열이 있어야 하는데 스냅샷이 6건뿐이다(실측).
//   그럴듯한 숫자를 만드는 대신 실현손익(증권사 실측)만 종목별로 낸다.
//
// ⚠️기간 끝을 오늘로 적지 않는다. 일별성과가 들어온 마지막 날까지만 잘라
//   보여 준다 — "9월"이라고 써 놓고 9/20 까지만 담겨 있으면 그렇게 말해야 한다.
//
// ★2026-09-25 사용자 지시(전체 메뉴 공통 패턴): 화면에는 대표 숫자, 누르면 상세.
//   벤치마크 대비 표는 수익률 칸, 종목별 실현손익 표는 실현손익 칸(과 '전체 목록'),
//   매매·배당·비용은 현금 칸을 눌러 여는 팝업으로 옮겼다. 본문에는 자산 분해와
//   신규/청산만 남는다.
//   ⚠️**월별 막대는 두지 않는다.** 리포트는 기간 하나를 한 번에 받아 오므로 달마다
//   숫자를 모으려면 달 수만큼 다시 불러야 한다 — 위의 기간 칩(월·분기·연도)이
//   그 역할을 한다.
//
// ★2026-10-04 사용자 지정: 첫 칸은 **내 계좌 수익률**(/account-return — 시작일 이후 손익 ÷
//   투입 원금)의 **기간 끝 값**이다. 이 정의는 시작일(6/01)부터 센 누적이라 '그 달만의
//   수익률'이 아니다 — 칸에 6/01~기간 끝이라고 적는다. 기간 안의 연쇄 수익률(TWR)과 벤치마크
//   대비는 '참고: 시간가중(TWR)'으로 남긴다. 기간 끝이 아직 진행 중(이번 달)이면 오늘 점이다.

function tone(value: string | null | undefined): "up" | "down" | undefined {
  if (value == null) return undefined;
  const n = Number(value);
  if (!Number.isFinite(n) || n === 0) return undefined;
  return n > 0 ? "up" : "down";
}

/** "+5.18%p" — 초과수익은 퍼센트가 아니라 **퍼센트포인트**다. */
function pp(value: string | null): string {
  if (value == null) return "—";
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  return `${n > 0 ? "+" : ""}${(n * 100).toFixed(2)}%p`;
}

export default function ReportPage() {
  const { accountId, connected } = useAccount();
  const [period, setPeriod] = useState<string | null>(null);
  const [notesOpen, setNotesOpen] = useState(false);
  const [residualOpen, setResidualOpen] = useState(false);
  const [panel, setPanel] = useState<"benchmarks" | "realized" | "trading" | null>(null);

  const report = useQuery({
    queryKey: ["report", accountId, period],
    queryFn: () => getReport(accountId, period),
    staleTime: 5 * 60_000,
  });

  const account = useQuery({
    queryKey: ["account-return", accountId],
    queryFn: () => getAccountReturn(accountId),
    staleTime: 60_000,
  });

  const data = report.data;
  const p = data?.period ?? null;
  // ⚠️리포트의 end_date 는 마지막 일별 행에서 잘린다. 진행 중인 마지막 기간이면 오늘(live)까지.
  const isLatest = p != null && data?.periods[0]?.key === p.key;
  const acctPoint = accountReturnOn(
    account.data,
    isLatest ? (account.data?.return_date ?? p?.end_date) : p?.end_date,
  );
  const netCash =
    data == null ? null : String(Number(data.dividend_krw) - Number(data.cost_krw));

  return (
    <>
      <Topbar title="기간 리포트" />
      <PageContainer fit>
        {!connected && !report.isLoading && <NotConnectedBanner what="일별 성과" />}

        <div className="flex shrink-0 items-center gap-2 overflow-x-auto pb-0.5">
          {(data?.periods ?? []).map((item) => (
            <button
              key={item.key}
              type="button"
              onClick={() => setPeriod(item.key)}
              className={cn(
                "shrink-0 rounded-full border px-3 py-1 text-[11px] font-bold transition-colors",
                p?.key === item.key
                  ? "border-ge-navy bg-ge-navy text-white"
                  : "border-hairline bg-canvas text-ink-secondary hover:bg-canvas-soft",
              )}
            >
              {item.label}
            </button>
          ))}
        </div>

        <div className="grid shrink-0 grid-cols-2 gap-2.5 lg:grid-cols-4">
          <StatTile
            label="내 계좌 수익률"
            value={
              acctPoint?.return_ratio == null ? null : formatPercentString(acctPoint.return_ratio)
            }
            hint={
              acctPoint
                ? `${account.data?.start.slice(5)}~${acctPoint.date.slice(5)} 누적 · 참고 TWR(기간) ${formatPercentString(data?.twr)}`
                : "시작일 이후 손익 ÷ 투입 원금"
            }
            actionHint="눌러서 벤치마크 대비 보기"
            onClick={() => setPanel("benchmarks")}
            accent="auto"
            loading={report.isLoading || account.isLoading}
          />
          <StatTile
            label="자산 변화"
            value={
              data?.opening_assets_krw && data.closing_assets_krw
                ? formatKrwSigned(
                    String(
                      Number(data.closing_assets_krw) - Number(data.opening_assets_krw),
                    ),
                  )
                : null
            }
            hint={
              data?.opening_assets_krw && data.closing_assets_krw
                ? `${formatKrwCompactString(data.opening_assets_krw)} → ${formatKrwCompactString(data.closing_assets_krw)}`
                : "시작 → 끝"
            }
            actionHint="눌러서 '그 외' 분해 보기"
            onClick={() => setResidualOpen(true)}
            accent="auto"
            loading={report.isLoading}
          />
          <StatTile
            label="실현손익"
            value={formatKrwSigned(data?.realized_total_krw)}
            hint={
              data
                ? `매수 ${data.buy_count} · 매도 ${data.sell_count}건`
                : "확정된 손익"
            }
            actionHint="눌러서 종목별 보기"
            onClick={() => setPanel("realized")}
            accent="auto"
            loading={report.isLoading}
          />
          <StatTile
            label="계좌가 만든 현금"
            value={formatKrwSigned(netCash)}
            hint={
              data
                ? `배당 ${formatKrwString(data.dividend_krw)} − 비용 ${formatKrwString(data.cost_krw)}`
                : "배당 − 수수료·세금"
            }
            actionHint="눌러서 매매·배당·비용 보기"
            onClick={() => setPanel("trading")}
            accent="auto"
            loading={report.isLoading}
          />
        </div>

        <div
          className={cn(
            "grid min-h-0 flex-1 gap-3",
            "grid-cols-1 auto-rows-[minmax(0,1fr)]",
            "md:grid-cols-2 lg:auto-rows-auto",
            "lg:grid-cols-[minmax(0,1fr)_minmax(0,1.15fr)]",
          )}
        >
          <StubCard
            title={p ? `${p.label} 요약` : "요약"}
            scrollBody
            action={
              <button
                type="button"
                onClick={() => setNotesOpen(true)}
                className="shrink-0 rounded-full bg-white/15 px-2.5 py-1 text-[11px] font-bold text-white transition-colors hover:bg-white/25"
              >
                한계
              </button>
            }
          >
            {report.isLoading ? (
              <CardEmpty text="불러오는 중…" />
            ) : data == null || p == null ? (
              <CardEmpty text="표시할 기간이 없습니다" />
            ) : (
              <Summary data={data} onExplain={() => setResidualOpen(true)} />
            )}
          </StubCard>

          <StubCard
            title="신규 · 청산"
            subtitle={
              data ? `포지션 변화 · 실현 ${data.realized.length}종목` : "포지션 변화"
            }
            scrollBody
            action={
              <button
                type="button"
                onClick={() => setPanel("realized")}
                className="shrink-0 rounded-full bg-white/15 px-2.5 py-1 text-[11px] font-bold text-white transition-colors hover:bg-white/25"
              >
                실현 목록
              </button>
            }
          >
            {report.isLoading ? (
              <CardEmpty text="불러오는 중…" />
            ) : data == null ? (
              <CardEmpty text="표시할 내역이 없습니다" />
            ) : (
              <Changes data={data} />
            )}
          </StubCard>
        </div>
      </PageContainer>

      {/* ── 요약 칸 → 상세 ───────────────────────────────────────────────── */}
      <Modal
        open={panel === "benchmarks"}
        onClose={() => setPanel(null)}
        title="벤치마크 대비"
        subtitle={
          p
            ? `${p.label} · 참고: 시간가중(TWR) 기간 수익률 ${formatPercentString(data?.twr)} · 원화 환산`
            : undefined
        }
        width={560}
      >
        {data && <Benchmarks data={data} />}
      </Modal>

      <Modal
        open={panel === "realized"}
        onClose={() => setPanel(null)}
        title="종목별 실현손익"
        subtitle={
          data
            ? `${p?.label ?? ""} · ${data.realized.length}종목 · 합계 ${formatKrwSigned(data.realized_total_krw)}`
            : undefined
        }
        width={640}
      >
        {data && <Realized data={data} />}
      </Modal>

      <Modal
        open={panel === "trading"}
        onClose={() => setPanel(null)}
        title="매매 · 배당 · 비용"
        subtitle={p ? `${p.label} · 계좌가 만든 현금 = 배당 − 수수료·세금` : undefined}
        width={520}
      >
        {data && (
          <div className="space-y-1">
            <Line
              label={`매수 ${data.buy_count} · 매도 ${data.sell_count}건`}
              value={data.turnover_krw}
              note="거래대금"
            />
            <Line label="수수료·세금" value={data.cost_krw} />
            <Line label="배당" value={data.dividend_krw} />
            <div className="mt-1 border-t border-ink pt-1">
              <Line label="계좌가 만든 현금" value={netCash} signed strong />
            </div>
          </div>
        )}
      </Modal>

      <Modal
        open={residualOpen}
        onClose={() => setResidualOpen(false)}
        title="'그 외'가 무엇인가"
        subtitle="환율(추정) · 배당(실측) · 수수료(실측) · 남는 것"
      >
        {data && <ResidualDetail data={data} />}
      </Modal>

      <Modal
        open={notesOpen}
        onClose={() => setNotesOpen(false)}
        title="이 리포트의 한계"
      >
        <ul className="space-y-2">
          {(data?.notes ?? []).map((text) => (
            <li key={text} className="flex items-start gap-2.5">
              <span className="mt-[7px] h-1.5 w-1.5 shrink-0 rounded-full bg-ge-point/50" />
              <span className="text-[12px] font-medium leading-snug text-ink-secondary">
                <Emphasized text={text} />
              </span>
            </li>
          ))}
        </ul>
      </Modal>
    </>
  );
}

function Summary({ data, onExplain }: { data: Report; onExplain: () => void }) {
  return (
    <div className="space-y-3">
      <div className="rounded-xl border border-hairline bg-canvas-soft px-3 py-2.5">
        <p className="mb-1.5 text-[11px] font-bold text-ge-navy">자산 분해</p>
        <Line label="시작 자산" value={data.opening_assets_krw} />
        <Line label="순납입" value={data.net_flow_krw} signed />
        <Line label="손익 (증권사)" value={data.pnl_krw} signed />
        {/* ⚠️'그 외'를 환차손익이라 부르지 않는다. 대신 **그 기간 환율 변동**을
            옆에 적어 사용자가 직접 견주게 한다 — 방향은 매달 같지만 크기가
            안 맞는 달이 있다(실측 8월: 잔차 −4.68% vs 환율 −3.80%). */}
        <Line
          label="그 외"
          value={data.unexplained_krw}
          signed
          muted
          note={
            data.fx_change_ratio == null
              ? undefined
              : `이 기간 환율 ${pp(data.fx_change_ratio).replace("%p", "%")}`
          }
        />
        <div className="mt-1 border-t border-ink pt-1">
          <Line label="끝 자산" value={data.closing_assets_krw} strong />
        </div>
        <button
          type="button"
          onClick={onExplain}
          className="mt-2 text-[11px] font-bold text-ge-point underline-offset-2 hover:underline"
        >
          &apos;그 외&apos;가 무엇인가 →
        </button>
      </div>

      <div>
        <p className="mb-1.5 text-[11px] font-bold text-ge-navy">가장 컸던 하루</p>
        <Line label={data.best_day ?? "—"} value={data.best_day_krw} signed />
        <Line label={data.worst_day ?? "—"} value={data.worst_day_krw} signed />
      </div>
    </div>
  );
}

/** 기간 수익률과 지수 수익률(원화 환산). 옛 요약 카드의 '벤치마크 대비'. */
function Benchmarks({ data }: { data: Report }) {
  return (
    <div>
      {data.benchmarks.length === 0 ? (
        <p className="text-[11px] text-ink-faint">
          이 기간은 비교할 지수 데이터가 없습니다.
        </p>
      ) : (
        <DataTable columns={["지수", "지수 수익률", "초과 (참고 TWR)"]} align={["left", "right", "right"]}>
          {data.benchmarks.map((b) => (
            <tr key={b.name} className="border-b border-hairline">
              <Cell left strong>
                {b.name}
              </Cell>
              <Cell tone={tone(b.return_krw)}>{formatPercentString(b.return_krw)}</Cell>
              {/* ⚠️단위가 %가 아니라 %p 다. 수익률의 차이이기 때문이다. */}
              <Cell strong tone={tone(b.excess)}>
                {pp(b.excess)}
              </Cell>
            </tr>
          ))}
        </DataTable>
      )}
    </div>
  );
}

function Realized({ data }: { data: Report }) {
  return (
    <div className="max-h-[60vh] overflow-y-auto">
      <DataTable
        columns={["종목", "매도", "실현손익", "환차"]}
        align={["left", "right", "right", "right"]}
        empty="이 기간에 매도한 종목이 없습니다"
      >
        {data.realized.map((r) => (
          <tr key={r.ticker} className="border-b border-hairline">
            <Cell left strong>
              <span className="flex items-center gap-1.5">
                <span className="max-w-[220px] truncate">{r.name ?? r.ticker}</span>
                <span className="shrink-0 text-[10px] font-bold text-ink-faint">
                  {r.ticker}
                </span>
              </span>
            </Cell>
            <Cell tone="muted">{r.sell_count}</Cell>
            <Cell strong tone={tone(r.pnl_krw)}>
              {formatKrwSigned(r.pnl_krw)}
            </Cell>
            {/* ⚠️환차를 주가 손익과 더하지 않는다 — 종목이 올라서 번 건지
                환율로 번 건지 구분이 사라진다. */}
            <Cell tone={tone(r.fx_pnl_krw)}>{formatKrwSigned(r.fx_pnl_krw)}</Cell>
          </tr>
        ))}
      </DataTable>
    </div>
  );
}

function Changes({ data }: { data: Report }) {
  const news = data.changes.filter((c) => c.kind === "NEW");
  const closed = data.changes.filter((c) => c.kind === "CLOSED");
  return (
    <div className="grid grid-cols-2 gap-2">
      <ChangeList title="신규 편입" items={news} empty="없음" kind="NEW" />
      <ChangeList title="전량 청산" items={closed} empty="없음" kind="CLOSED" />
    </div>
  );
}

function ChangeList({
  title,
  items,
  empty,
  kind,
}: {
  title: string;
  items: Report["changes"];
  empty: string;
  kind: "NEW" | "CLOSED";
}) {
  return (
    <div className="rounded-xl border border-hairline bg-canvas-soft px-2.5 py-2">
      <p className="mb-1.5 text-[11px] font-bold text-ge-navy">
        {title} ({items.length})
      </p>
      {items.length === 0 ? (
        <p className="text-[11px] font-semibold text-ink-faint">{empty}</p>
      ) : (
        <div className="space-y-1">
          {items.map((c) => (
            <div key={c.ticker} className="flex items-baseline justify-between gap-2">
              <span className="flex min-w-0 items-center gap-1">
                <span
                  className={cn(
                    "shrink-0 rounded px-1 py-0.5 text-[9px] font-extrabold",
                    kind === "NEW" ? "bg-bid-soft text-bid" : "bg-ask-soft text-ask",
                  )}
                >
                  {c.ticker}
                </span>
                <span className="truncate text-[11px] text-ink-secondary">
                  {c.name ?? ""}
                </span>
              </span>
              <span className="shrink-0 text-[10px] font-semibold text-ink-faint">
                {c.first_date.slice(5)}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── '그 외' 분해 ────────────────────────────────────────────────────────────
//
// ★잔차를 '그 외'로만 두면 사용자가 판단할 근거가 없다. 쪼개 보니 대부분
//   환율이었다 — 전체 구간 실측: 잔차 -3,203,574 = 환율 -3,091,778
//   + 배당 121,611 - 수수료 120,399 + 남는 것 -113,008(잔차의 3.5%).
//
// ⚠️환율만 **추정**이다(전일 주식평가액 × 환율 변동률). 증권사가 준 일별 환율
//   칸이 532행 전부 비어 있다. 배당·수수료는 실측이다. 화면에서 구분해 적는다.
//
// ⚠️**월 단위로는 어긋난다.** 남는 것이 월별로 +25만 / +26만 / -37만 / -26만
//   으로 흔들리는데 합치면 -11만이다. 부호가 번갈아 나며 상쇄되는 모양이라
//   환산 시점 차이로 월 경계에서 밀리는 것으로 보인다. 월별 숫자를 "이만큼이
//   환율이다"라고 읽으면 안 된다고 화면에 적는다.

function ResidualDetail({ data }: { data: Report }) {
  const r = data.residual;
  return (
    <div className="space-y-3">
      <div className="rounded-xl border border-hairline bg-canvas-soft/60 p-3">
        <Line
          label="환율"
          value={r.fx_estimate_krw}
          signed
          note={`추정 · ${r.fx_days}일`}
        />
        <Line label="배당" value={r.dividend_krw} signed note="실측" />
        <Line
          label="수수료·세금"
          value={r.cost_krw === "0" ? "0" : `-${r.cost_krw}`}
          signed
          note="실측"
        />
        <Line label="남는 것" value={r.leftover_krw} signed muted note="설명 안 됨" />
        <div className="mt-1 border-t border-ink pt-1">
          <Line label="그 외 (합)" value={r.total_krw} signed strong />
        </div>
      </div>
    </div>
  );
}

function Line({
  label,
  value,
  signed,
  strong,
  muted,
  note,
}: {
  label: string;
  value: string | null;
  signed?: boolean;
  strong?: boolean;
  muted?: boolean;
  note?: string;
}) {
  return (
    <div className="flex items-baseline justify-between gap-2">
      <span
        className={cn(
          "truncate text-[12px]",
          strong ? "font-bold text-ink" : muted ? "text-ink-faint" : "text-ink-secondary",
        )}
      >
        {label}
        {note && (
          <span className="ml-1.5 text-[10px] font-semibold text-ink-faint">
            {note}
          </span>
        )}
      </span>
      <span
        className={cn(
          "shrink-0 tabular-nums",
          strong ? "text-[13px] font-extrabold text-ink" : "text-[12px] font-semibold",
          muted && !strong && "text-ink-faint",
          !muted && !strong && "text-ink-secondary",
        )}
      >
        {signed ? formatKrwSigned(value) : formatKrwString(value)}
      </span>
    </div>
  );
}

/** 서버 문구의 `**강조**` 만 굵게. dangerouslySetInnerHTML 을 쓰지 않는다. */

