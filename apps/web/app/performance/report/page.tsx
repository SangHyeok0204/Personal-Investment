"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { PageContainer } from "@/components/layout/page-header";
import { Topbar } from "@/components/layout/topbar";
import { useAccount } from "@/components/layout/account-context";
import { Modal } from "@/components/ui/modal";
import {
  Cell,
  DataTable,
  NotConnectedBanner,
  StatTile,
  StubCard,
} from "@/components/stub";
import { getReport, type Report } from "@/lib/api";
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

  const report = useQuery({
    queryKey: ["report", accountId, period],
    queryFn: () => getReport(accountId, period),
    staleTime: 5 * 60_000,
  });

  const data = report.data;
  const p = data?.period ?? null;
  const netCash =
    data == null ? null : String(Number(data.dividend_krw) - Number(data.cost_krw));

  return (
    <>
      <Topbar title="기간 리포트" subtitle="그 기간에 무슨 일이 있었나" />
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
            label="기간 수익률 (TWR)"
            value={formatPercentString(data?.twr)}
            hint={
              p
                ? `${p.start_date} ~ ${p.end_date} · ${data?.trading_days ?? 0}거래일`
                : "시간가중 수익률"
            }
            accent="auto"
            loading={report.isLoading}
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
            subtitle="자산이 왜 그만큼 바뀌었나"
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
              <Empty text="불러오는 중…" />
            ) : data == null || p == null ? (
              <Empty text="표시할 기간이 없습니다" />
            ) : (
              <Summary data={data} onExplain={() => setNotesOpen(true)} />
            )}
          </StubCard>

          <StubCard
            title="종목"
            subtitle="확정된 손익과 포지션 변화"
            scrollBody
          >
            {report.isLoading ? (
              <Empty text="불러오는 중…" />
            ) : data == null ? (
              <Empty text="표시할 내역이 없습니다" />
            ) : (
              <Tickers data={data} />
            )}
          </StubCard>
        </div>
      </PageContainer>

      <Modal
        open={notesOpen}
        onClose={() => setNotesOpen(false)}
        title="이 리포트의 한계"
        subtitle="무엇을 넣지 않았나"
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
  const p = data.period!;
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
        <p className="mb-1.5 text-[11px] font-bold text-ge-navy">벤치마크 대비</p>
        {data.benchmarks.length === 0 ? (
          <p className="text-[11px] text-ink-faint">
            이 기간은 비교할 지수 데이터가 없습니다.
          </p>
        ) : (
          <DataTable columns={["지수", "지수 수익률", "초과"]} align={["left", "right", "right"]}>
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
        <p className="mt-1.5 text-[11px] leading-relaxed text-ink-muted">
          원화 환산 기준입니다 — 지수를 달러로 보면 환율 효과가 빠져 내 계좌와
          비교가 되지 않습니다.
        </p>
      </div>

      <div>
        <p className="mb-1.5 text-[11px] font-bold text-ge-navy">가장 컸던 하루</p>
        <Line label={data.best_day ?? "—"} value={data.best_day_krw} signed />
        <Line label={data.worst_day ?? "—"} value={data.worst_day_krw} signed />
      </div>

      <div>
        <p className="mb-1.5 text-[11px] font-bold text-ge-navy">매매</p>
        <Line
          label={`매수 ${data.buy_count} · 매도 ${data.sell_count}건`}
          value={data.turnover_krw}
        />
        <Line label="수수료·세금" value={data.cost_krw} />
        <Line label="배당" value={data.dividend_krw} />
      </div>

      {/* ⚠️"9월"이라고 써 놓고 9/20 까지만 담겨 있으면 그렇게 말해야 한다. */}
      <p className="text-[11px] leading-relaxed text-ink-faint">
        이 리포트는 <strong>{p.start_date} ~ {p.end_date}</strong> 의 일별 성과를
        담고 있습니다({data.trading_days}거래일). 증권사 일별 성과가 들어온
        마지막 날까지만 집계합니다.
      </p>
    </div>
  );
}

function Tickers({ data }: { data: Report }) {
  const news = data.changes.filter((c) => c.kind === "NEW");
  const closed = data.changes.filter((c) => c.kind === "CLOSED");

  return (
    <div className="space-y-3">
      <div>
        <p className="mb-1.5 text-[11px] font-bold text-ge-navy">
          실현손익 · {data.realized.length}종목
        </p>
        <DataTable
          columns={["종목", "매도", "실현손익", "환차"]}
          align={["left", "right", "right", "right"]}
          empty="이 기간에 매도한 종목이 없습니다"
        >
          {data.realized.map((r) => (
            <tr key={r.ticker} className="border-b border-hairline">
              <Cell left strong>
                <span className="flex items-center gap-1.5">
                  <span className="max-w-[110px] truncate">{r.name ?? r.ticker}</span>
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

      <div className="grid grid-cols-2 gap-2">
        <ChangeList title="신규 편입" items={news} empty="없음" kind="NEW" />
        <ChangeList title="전량 청산" items={closed} empty="없음" kind="CLOSED" />
      </div>
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
function Emphasized({ text }: { text: string }) {
  return (
    <>
      {text.split(/\*\*(.+?)\*\*/g).map((part, i) =>
        i % 2 === 1 ? (
          <strong key={i} className="text-ink">
            {part}
          </strong>
        ) : (
          part
        ),
      )}
    </>
  );
}

function Empty({ text }: { text: string }) {
  return (
    <div className="flex h-full items-center justify-center px-4 text-center">
      <span className="text-[12px] font-semibold text-ink-faint">{text}</span>
    </div>
  );
}
