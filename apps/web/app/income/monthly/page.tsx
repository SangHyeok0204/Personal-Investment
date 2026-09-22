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
import { getMonthlyCashflow, type MonthlyCashflowRow } from "@/lib/api";
import { formatKrwCompactString, formatKrwSigned, formatKrwString } from "@/lib/format";
import { cn } from "@/lib/utils";

// 월별 현금흐름 — 한 달 동안 돈이 어디서 들어오고 어디로 나갔나.
//
// ★금액이 **전부 원화**인 유일한 매매 화면이다. 원천이 account_daily_performance
//   하나뿐이라(증권사가 입금·출금·배당·수수료·매수·매도를 전부 원화로 준다)
//   통화를 섞을 일이 없다. 수수료/세금 화면은 trades 원천이라 USD 다 —
//   같은 '비용'이라도 **출처가 다르므로 두 숫자를 이어 붙이지 않는다.**
//
// ⚠️세 층을 한 숫자로 합치지 않는다. 합치면 뜻이 사라진다:
//   · 외부 흐름(입금−출금)   내 지갑 ↔ 계좌. **수익이 아니다.**
//   · 계좌가 만든 현금(배당−비용)  시장과 무관하게 실제로 생긴/사라진 현금.
//   · 매매 회전(매수/매도)   계좌 안에서 현금 ↔ 주식. 손익이 아니다.
//
// ⚠️'그 외'를 **환차손익이라고 부르지 않는다.** 일별성과의 환율 칸이 530행 전부
//   비어 있어 실측이 불가능하다. 상관 0.937 로 환율이 대부분을 설명하지만,
//   실측할 수 없는 것에 이름을 붙이는 순간 추정이 실측인 척하게 된다.

type Layer = "flow" | "cash" | "turnover";

const LAYERS: { key: Layer; label: string; hint: string }[] = [
  { key: "cash", label: "계좌가 만든 현금", hint: "배당 − 수수료·세금" },
  { key: "flow", label: "외부 흐름", hint: "입금 − 출금 (수익 아님)" },
  { key: "turnover", label: "매매 회전", hint: "매수 · 매도 대금" },
];

export default function MonthlyCashflowPage() {
  const { accountId, connected } = useAccount();
  const [layer, setLayer] = useState<Layer>("cash");
  const [picked, setPicked] = useState<MonthlyCashflowRow | null>(null);
  const [noteOpen, setNoteOpen] = useState(false);

  const cashflow = useQuery({
    queryKey: ["monthlyCashflow", accountId],
    queryFn: () => getMonthlyCashflow(accountId),
    staleTime: 60_000,
  });

  const data = cashflow.data;
  const rows = data?.rows ?? [];
  const latest = rows[0];

  return (
    <>
      <Topbar title="월별 현금흐름" subtitle="한 달 동안 돈이 어디서 들어오고 어디로 나갔나" />
      <PageContainer fit>
        {!connected && !cashflow.isLoading && <NotConnectedBanner what="계좌 일별 성과" />}

        <div className="grid shrink-0 grid-cols-2 gap-2.5 lg:grid-cols-4">
          <StatTile
            label="계좌가 만든 현금"
            value={formatKrwSigned(data?.net_cash_generated_krw)}
            hint={
              data
                ? `배당 ${formatKrwString(data.total_dividend_krw)} − 비용 ${formatKrwString(data.total_cost_krw)}`
                : "배당 − 수수료·세금"
            }
            accent="auto"
            actionHint="눌러서 읽는 법 보기"
            onClick={() => setNoteOpen(true)}
            loading={cashflow.isLoading}
          />
          <StatTile
            label="배당이 비용을 덮은 달"
            value={
              data ? `${data.months_dividend_covered_cost} / ${data.months_total}` : null
            }
            hint={
              data
                ? `${data.first_month} ~ ${data.last_month}`
                : "배당 > 수수료·세금 인 달"
            }
            loading={cashflow.isLoading}
          />
          <StatTile
            label="순납입"
            value={
              data
                ? formatKrwCompactString(
                    String(Number(data.total_deposit_krw) - Number(data.total_withdrawal_krw)),
                  )
                : null
            }
            hint={
              data
                ? `입금 ${formatKrwCompactString(data.total_deposit_krw)} · 출금 ${formatKrwCompactString(data.total_withdrawal_krw)}`
                : "내 지갑에서 들어온 돈"
            }
            loading={cashflow.isLoading}
          />
          <StatTile
            label="매매 회전"
            value={data ? formatKrwCompactString(data.total_buy_krw) : null}
            hint={
              data
                ? `매도 ${formatKrwCompactString(data.total_sell_krw)} · 손익 아님`
                : "매수 대금 누계"
            }
            loading={cashflow.isLoading}
          />
        </div>

        <div
          className={cn(
            "grid min-h-0 flex-1 gap-3",
            "grid-cols-1 auto-rows-[minmax(0,1fr)]",
            "md:grid-cols-2 lg:auto-rows-auto",
            "lg:grid-cols-[minmax(0,1.45fr)_minmax(0,1fr)]",
          )}
        >
          <StubCard
            title="월별"
            subtitle={`${rows.length}개월 · 최근이 위 · 눌러서 상세`}
            scrollBody
            action={
              <div className="flex shrink-0 gap-1">
                {LAYERS.map((l) => (
                  <button
                    key={l.key}
                    type="button"
                    title={l.hint}
                    onClick={() => setLayer(l.key)}
                    className={cn(
                      "rounded-full px-2.5 py-1 text-[11px] font-bold transition-colors",
                      layer === l.key
                        ? "bg-white text-ge-navy"
                        : "bg-white/15 text-white hover:bg-white/25",
                    )}
                  >
                    {l.label}
                  </button>
                ))}
              </div>
            }
          >
            <DataTable
              columns={
                layer === "cash"
                  ? ["월", "배당", "수수료·세금", "순현금"]
                  : layer === "flow"
                    ? ["월", "입금", "출금", "순납입"]
                    : ["월", "매수", "매도", "월말 자산"]
              }
              align={["left", "right", "right", "right"]}
              empty={
                cashflow.isLoading
                  ? "불러오는 중…"
                  : connected
                    ? "일별 성과 데이터가 없습니다"
                    : "계좌를 연동하면 월별 현금흐름이 표시됩니다"
              }
            >
              {rows.map((r) => (
                <tr
                  key={r.month}
                  onClick={() => setPicked(r)}
                  className="cursor-pointer border-b border-hairline transition-colors hover:bg-canvas-soft"
                >
                  <Cell left strong>
                    {r.month}
                  </Cell>
                  {layer === "cash" && (
                    <>
                      <Cell tone={Number(r.dividend_krw) > 0 ? "up" : "muted"}>
                        {formatKrwString(r.dividend_krw)}
                      </Cell>
                      <Cell tone={Number(r.cost_krw) > 0 ? "down" : "muted"}>
                        {formatKrwString(r.cost_krw)}
                      </Cell>
                      <Cell
                        strong
                        tone={Number(r.net_cash_generated_krw) >= 0 ? "up" : "down"}
                      >
                        {formatKrwSigned(r.net_cash_generated_krw)}
                      </Cell>
                    </>
                  )}
                  {layer === "flow" && (
                    <>
                      <Cell tone={Number(r.deposit_krw) > 0 ? undefined : "muted"}>
                        {formatKrwString(r.deposit_krw)}
                      </Cell>
                      <Cell tone={Number(r.withdrawal_krw) > 0 ? undefined : "muted"}>
                        {formatKrwString(r.withdrawal_krw)}
                      </Cell>
                      <Cell strong tone={Number(r.net_flow_krw) === 0 ? "muted" : undefined}>
                        {formatKrwSigned(r.net_flow_krw)}
                      </Cell>
                    </>
                  )}
                  {layer === "turnover" && (
                    <>
                      <Cell tone={Number(r.buy_krw) > 0 ? undefined : "muted"}>
                        {formatKrwCompactString(r.buy_krw)}
                      </Cell>
                      <Cell tone={Number(r.sell_krw) > 0 ? undefined : "muted"}>
                        {formatKrwCompactString(r.sell_krw)}
                      </Cell>
                      <Cell strong>{formatKrwCompactString(r.closing_assets_krw)}</Cell>
                    </>
                  )}
                </tr>
              ))}
            </DataTable>
          </StubCard>

          {/* 오른쪽 열은 카드 둘이다 — '이번 달'(고정 높이)과 '누적'(남는 높이). */}
          <div className="flex min-h-0 flex-col gap-3">
            {/* ⚠️'이번 달'을 shrink-0 으로 두면 아래 카드가 화면 밖으로 밀려
                 **닿을 수 없게** 된다(페이지 스크롤이 없는 레이아웃이라 더 그렇다).
                 두 카드가 높이를 나눠 갖고 각자 안에서 스크롤한다.
                 ⚠️다만 **반씩 나누면 위 카드가 모자란다.** 위는 세 묶음(계좌가
                 만든 현금·외부 흐름·매매 회전)이라 14줄쯤 되고 아래는 8줄인데,
                 1:1 로 두니 '매매 회전'이 카드 밖으로 잘려 렌더 오류처럼 보였다.
                 내용 비율에 맞춰 1.6:1 로 나눈다. */}
            <StubCard
              title="이번 달"
              subtitle={latest ? latest.month : "최근 달"}
              className="min-h-0 flex-[1.6]"
              scrollBody
            >
              {cashflow.isLoading ? (
                <Empty text="불러오는 중…" />
              ) : latest == null ? (
                <Empty text="표시할 달이 없습니다" />
              ) : (
                <MonthDetail row={latest} onExplain={() => setNoteOpen(true)} />
              )}
            </StubCard>

            <StubCard
              title="누적 순현금"
              subtitle="계좌가 스스로 번 돈이 쌓이고 있나"
              className="min-h-0 flex-1"
              scrollBody
            >
              {cashflow.isLoading ? (
                <Empty text="불러오는 중…" />
              ) : rows.length === 0 ? (
                <Empty text="표시할 달이 없습니다" />
              ) : (
                <Cumulative rows={rows} />
              )}
            </StubCard>
          </div>
        </div>
      </PageContainer>

      <Modal
        open={picked != null}
        onClose={() => setPicked(null)}
        title={picked ? `${picked.month} 현금흐름` : ""}
        subtitle="세 층을 합치지 않는다"
      >
        {picked && <MonthDetail row={picked} onExplain={() => { setPicked(null); setNoteOpen(true); }} />}
      </Modal>

      <Modal
        open={noteOpen}
        onClose={() => setNoteOpen(false)}
        title="이 화면 읽는 법"
        subtitle="세 가지 돈은 성격이 다르다"
      >
        <ul className="space-y-2.5 text-[12px] leading-relaxed text-ink-secondary">
          <li>
            <strong>입금은 수익이 아닙니다.</strong> 자산은 늘지만 내 돈이 늘어난 게
            아니라 지갑에서 계좌로 <strong>위치만 바뀐 것</strong>입니다. 그래서
            입출금과 배당을 더하지 않았습니다 — 더하면 &quot;이번 달 900만원 벌었다&quot;는
            말이 나오는데 아무 뜻이 없습니다.
          </li>
          <li>
            <strong>계좌가 만든 현금 = 배당 − 수수료·세금.</strong> 주가가 오르든
            내리든 실제로 생기거나 사라진 현금입니다. 주가 손익과 달리 이건 팔지
            않아도 이미 확정된 돈입니다.
          </li>
          <li>
            <strong>매수·매도 대금은 손익이 아닙니다.</strong> 계좌 안에서 현금이
            주식이 되고 주식이 현금이 된 것뿐입니다. 회전이 얼마나 컸는지만 봅니다.
          </li>
          <li>
            <strong>&apos;그 외&apos;를 환차손익이라고 적지 않았습니다.</strong>{" "}
            {cashflow.data?.note}
          </li>
          <li>
            <strong>여기 금액은 전부 원화입니다.</strong> 수수료/세금 화면은 체결
            기록(USD)이 원천이라 달러로 적혀 있습니다. 같은 &apos;비용&apos;이라도
            출처가 다르므로 <strong>두 화면의 숫자를 환율로 이어 붙이지 마세요.</strong>
          </li>
        </ul>
      </Modal>
    </>
  );
}

/**
 * 배당 − 비용의 **누적**. 총계 타일(+₩194,298)이 감추는 것을 드러낸다 —
 * 그 숫자는 지금까지의 합일 뿐이라 **지금 늘고 있는지 줄고 있는지**를 말하지 않는다.
 *
 * ⚠️고점을 "최대값"이라고만 적지 않는다. 고점 이후 줄고 있다는 사실이 요점이고,
 *   줄고 있지 않으면 그 문장을 **띄우지 않는다**(없는 추세를 만들지 않는다).
 */
function Cumulative({ rows }: { rows: MonthlyCashflowRow[] }) {
  // rows 는 최근이 먼저다. 누적은 과거부터 쌓아야 하므로 뒤집어서 계산한다.
  const chronological = [...rows].reverse();
  let running = 0;
  const points = chronological.map((r) => {
    running += Number(r.net_cash_generated_krw);
    return { month: r.month, value: running };
  });

  const peak = points.reduce((a, b) => (b.value >= a.value ? b : a), points[0]);
  const last = points[points.length - 1];
  const peakIndex = points.findIndex((p) => p.month === peak.month);
  // 고점이 마지막 달이면 "고점 이후 감소"라는 말이 성립하지 않는다.
  const declining = peakIndex < points.length - 1 && last.value < peak.value;
  const monthsSincePeak = points.length - 1 - peakIndex;

  const max = Math.max(...points.map((p) => Math.abs(p.value)), 1);

  return (
    <div className="space-y-2.5">
      {declining && (
        <p className="rounded-lg bg-ask-soft px-2.5 py-2 text-[11px] font-semibold leading-snug text-ask">
          {peak.month} 고점 {formatKrwSigned(String(peak.value))} 이후{" "}
          {monthsSincePeak}개월째 줄고 있습니다 — 최근 매매 비용이 배당보다 큽니다.
        </p>
      )}
      <div className="space-y-1">
        {[...points].reverse().map((p) => (
          <div key={p.month}>
            <div className="mb-0.5 flex items-baseline justify-between">
              <span className="text-[11px] font-bold text-ge-navy">{p.month}</span>
              <span
                className={cn(
                  "text-[11px] font-bold tabular-nums",
                  p.value >= 0 ? "text-bid" : "text-ask",
                )}
              >
                {formatKrwSigned(String(p.value))}
              </span>
            </div>
            <div className="h-1.5 w-full overflow-hidden rounded-full bg-canvas-soft">
              <div
                className={cn(
                  "h-full rounded-full",
                  p.value >= 0 ? "bg-bid" : "bg-ask",
                )}
                style={{ width: `${(Math.abs(p.value) / max) * 100}%` }}
              />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function MonthDetail({
  row,
  onExplain,
}: {
  row: MonthlyCashflowRow;
  onExplain: () => void;
}) {
  const covered = Number(row.net_cash_generated_krw) >= 0;
  return (
    <div className="space-y-3">
      <Layer
        title="계좌가 만든 현금"
        note={covered ? "배당이 비용을 덮었습니다" : "배당이 비용을 못 덮었습니다"}
        tone={covered ? "up" : "down"}
        lines={[
          ["배당", row.dividend_krw, "up"],
          ["수수료·세금", negated(row.cost_krw), "down"],
        ]}
        total={row.net_cash_generated_krw}
      />
      <Layer
        title="외부 흐름"
        note="내 지갑 ↔ 계좌 · 수익이 아님"
        lines={[
          ["입금", row.deposit_krw, undefined],
          ["출금", negated(row.withdrawal_krw), undefined],
        ]}
        total={row.net_flow_krw}
      />
      <Layer
        title="매매 회전"
        note="계좌 안에서 현금 ↔ 주식 · 손익이 아님"
        lines={[
          ["매수", row.buy_krw, undefined],
          ["매도", row.sell_krw, undefined],
        ]}
      />

      <div className="rounded-xl border border-hairline bg-canvas-soft px-3 py-2.5">
        <p className="mb-1.5 text-[11px] font-bold text-ge-navy">자산 잔액 대조</p>
        <Reconcile label="월초 자산" value={row.opening_assets_krw} />
        <Reconcile label="순납입" value={row.net_flow_krw} signed />
        <Reconcile label="손익 (증권사)" value={row.pnl_krw} signed />
        <Reconcile label="그 외" value={row.unexplained_krw} signed muted />
        <div className="mt-1 border-t border-ink pt-1">
          <Reconcile label="월말 자산" value={row.closing_assets_krw} strong />
        </div>
        <button
          type="button"
          onClick={onExplain}
          className="mt-2 text-[11px] font-bold text-ge-point underline-offset-2 hover:underline"
        >
          &apos;그 외&apos;가 무엇인가 →
        </button>
      </div>
    </div>
  );
}

/** 계좌에서 나가는 돈은 음수로 적는다. ⚠️0 에 "-"를 붙이면 "-₩0"이 된다. */
function negated(value: string): string {
  return Number(value) === 0 ? value : `-${value}`;
}

function Layer({
  title,
  note,
  lines,
  total,
  tone,
}: {
  title: string;
  note: string;
  lines: [string, string, "up" | "down" | undefined][];
  total?: string;
  tone?: "up" | "down";
}) {
  return (
    <div>
      <div className="mb-1 flex items-baseline justify-between gap-2">
        <span className="text-[11px] font-bold text-ge-navy">{title}</span>
        <span className="truncate text-[10px] font-medium text-ink-faint">{note}</span>
      </div>
      <div className="space-y-0.5">
        {lines.map(([label, value, lineTone]) => (
          <div key={label} className="flex items-baseline justify-between">
            <span className="text-[12px] text-ink-secondary">{label}</span>
            <span
              className={cn(
                "text-[12px] font-semibold tabular-nums",
                lineTone === "up" && "text-bid",
                lineTone === "down" && "text-ask",
                lineTone == null && "text-ink-secondary",
              )}
            >
              {formatKrwString(value)}
            </span>
          </div>
        ))}
        {total != null && (
          <div className="flex items-baseline justify-between border-t border-hairline pt-1">
            <span className="text-[12px] font-bold text-ink">합계</span>
            <span
              className={cn(
                "text-[13px] font-extrabold tabular-nums",
                tone === "up" && "text-bid",
                tone === "down" && "text-ask",
                tone == null && "text-ink",
              )}
            >
              {formatKrwSigned(total)}
            </span>
          </div>
        )}
      </div>
    </div>
  );
}

function Reconcile({
  label,
  value,
  signed,
  strong,
  muted,
}: {
  label: string;
  value: string | null;
  signed?: boolean;
  strong?: boolean;
  muted?: boolean;
}) {
  return (
    <div className="flex items-baseline justify-between">
      <span
        className={cn(
          "text-[12px]",
          strong ? "font-bold text-ink" : muted ? "text-ink-faint" : "text-ink-secondary",
        )}
      >
        {label}
      </span>
      <span
        className={cn(
          "tabular-nums",
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

function Empty({ text }: { text: string }) {
  return (
    <div className="flex h-full items-center justify-center px-4 text-center">
      <span className="text-[12px] font-semibold text-ink-faint">{text}</span>
    </div>
  );
}
