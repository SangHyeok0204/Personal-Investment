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
import { getTax, type TaxYear } from "@/lib/api";
import { formatKrwSigned, formatKrwString } from "@/lib/format";
import { cn } from "@/lib/utils";

// 세금 — 해외주식 양도소득세 · 배당소득.
//
// ⚠️**신고 자료가 아니다.** 화면 어디에서도 "세금이 없습니다"로 끝내지 않는다 —
//   세액이 0 이어도 기본공제는 신고를 통해 적용되는 것이고, 이 화면은 세무 판단을
//   할 수 있는 자리가 아니다.
//
// ★이 화면에서만 **환차를 양도차익에 더한다.** 다른 화면에서는 주가 손익과 환차를
//   섞지 말라고 해 놓고 여기서만 합치는 게 모순처럼 보이지만, 질문이 다르다 —
//   "종목 선택이 좋았나"는 주가만 봐야 하고, "세금을 얼마 내나"는 원화 기준
//   차익이라 환율이 과세 대상 그 자체다.
//   실측 NVDA: 주가로 +₩50,182 벌었는데 양도차익은 **−₩70,420** 이다.
//
// ★취득가액을 realized_pnl.buy_amount_krw 로 잡지 않는다 — 그 칸은 매수·매도를
//   같은 환율로 환산한 값이라 세법상 취득가액이 아니다. 체결일 환율을 직접 쓴다.

function tone(value: string | null | undefined): "up" | "down" | undefined {
  if (value == null) return undefined;
  const n = Number(value);
  if (!Number.isFinite(n) || n === 0) return undefined;
  return n > 0 ? "up" : "down";
}

export default function TaxPage() {
  const { accountId, connected } = useAccount();
  const [year, setYear] = useState<number | null>(null);
  const [notesOpen, setNotesOpen] = useState(false);

  const tax = useQuery({
    queryKey: ["tax", accountId, year],
    queryFn: () => getTax(accountId, year),
    staleTime: 5 * 60_000,
  });

  const data = tax.data;
  const current = data?.current ?? null;
  const sales = current?.sales ?? [];

  return (
    <>
      <Topbar title="세금" subtitle="해외주식 양도소득 · 배당소득 (추정)" />
      <PageContainer fit>
        {!connected && !tax.isLoading && <NotConnectedBanner what="실현손익" />}

        {/* ⚠️맨 위에 둔다. 아래 숫자를 보기 전에 무엇인지 알아야 한다. */}
        <div className="flex shrink-0 items-center gap-2 rounded-xl border border-ge-point/25 bg-ge-point/5 px-3 py-2">
          <span className="rounded bg-ge-point/15 px-1.5 py-0.5 text-[10px] font-extrabold text-ge-point">
            추정
          </span>
          <span className="text-[11px] font-semibold leading-snug text-ink-secondary">
            신고 자료가 아닙니다. 기준환율·해외납부세액공제를 반영하지 않았고, 배당이
            세전인지 세후인지도 확인할 수 없습니다.
          </span>
          <button
            type="button"
            onClick={() => setNotesOpen(true)}
            className="ml-auto shrink-0 rounded-full bg-ge-point/10 px-2.5 py-1 text-[11px] font-bold text-ge-point transition-colors hover:bg-ge-point/20"
          >
            한계 7가지
          </button>
        </div>

        <div className="grid shrink-0 grid-cols-2 gap-2.5 lg:grid-cols-4">
          <StatTile
            label="양도차익"
            value={formatKrwSigned(current?.gain_krw)}
            hint={
              current
                ? `${current.sale_count}건 · 환차 포함 · 눌러서 설명`
                : "환차 포함"
            }
            accent="auto"
            actionHint="눌러서 읽는 법 보기"
            onClick={() => setNotesOpen(true)}
            loading={tax.isLoading}
          />
          <StatTile
            label="예상 세액"
            value={current ? formatKrwString(current.tax_krw) : null}
            hint={
              current
                ? `과세표준 ${formatKrwString(current.taxable_base_krw)} × ${(Number(current.tax_rate) * 100).toFixed(0)}%`
                : "양도소득세 + 지방소득세"
            }
            loading={tax.isLoading}
          />
          <StatTile
            label="기본공제 여유"
            value={formatKrwSigned(current?.headroom_krw)}
            hint={
              current
                ? `공제 ${formatKrwString(current.deduction_krw)} 중 남은 금액`
                : "연 250만원 · 이월 없음"
            }
            accent="auto"
            loading={tax.isLoading}
          />
          <StatTile
            label="배당소득"
            value={current ? formatKrwString(current.dividend_krw) : null}
            hint={
              current
                ? `${current.dividend_count}건 · 종합과세 기준 ${formatKrwString(current.comprehensive_threshold_krw)}`
                : "수령 배당"
            }
            loading={tax.isLoading}
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
            title="매도 건별 양도차익"
            subtitle={`${sales.length}건 · 손실이 위 · 체결일 환율`}
            scrollBody
            action={
              (data?.years.length ?? 0) > 1 ? (
                <div className="flex shrink-0 gap-1">
                  {(data?.years ?? []).map((y) => (
                    <button
                      key={y}
                      type="button"
                      onClick={() => setYear(y)}
                      className={cn(
                        "rounded-full px-2.5 py-1 text-[11px] font-bold transition-colors",
                        (current?.year ?? 0) === y
                          ? "bg-white text-ge-navy"
                          : "bg-white/15 text-white hover:bg-white/25",
                      )}
                    >
                      {y}
                    </button>
                  ))}
                </div>
              ) : undefined
            }
          >
            <DataTable
              columns={["종목", "매도일", "양도가액", "취득가액", "양도차익"]}
              align={["left", "left", "right", "right", "right"]}
              empty={
                tax.isLoading
                  ? "불러오는 중…"
                  : connected
                    ? "이 해에 매도한 내역이 없습니다"
                    : "계좌를 연동하면 양도차익이 표시됩니다"
              }
            >
              {sales.map((s) => (
                <tr
                  key={`${s.ticker}-${s.sell_date}-${s.proceeds_krw}`}
                  className="border-b border-hairline"
                >
                  <Cell left strong>
                    <span className="flex items-center gap-1.5">
                      <span className="max-w-[120px] truncate">
                        {s.name ?? s.ticker}
                      </span>
                      <span className="shrink-0 text-[10px] font-bold text-ink-faint">
                        {s.ticker}
                      </span>
                    </span>
                  </Cell>
                  <Cell left tone="muted">
                    {s.sell_date.slice(5)}
                  </Cell>
                  <Cell>{formatKrwString(s.proceeds_krw)}</Cell>
                  <Cell tone="muted">{formatKrwString(s.cost_basis_krw)}</Cell>
                  <Cell strong tone={tone(s.gain_krw)}>
                    {formatKrwSigned(s.gain_krw)}
                  </Cell>
                </tr>
              ))}
            </DataTable>
          </StubCard>

          <StubCard title="계산 과정" subtitle="어떻게 이 숫자가 나왔나" scrollBody>
            {tax.isLoading ? (
              <Empty text="불러오는 중…" />
            ) : current == null ? (
              <Empty text="계산할 내역이 없습니다" />
            ) : (
              <Breakdown year={current} onExplain={() => setNotesOpen(true)} />
            )}
          </StubCard>
        </div>
      </PageContainer>

      <Modal
        open={notesOpen}
        onClose={() => setNotesOpen(false)}
        title="이 화면의 한계"
        subtitle="무엇을 믿고 무엇을 믿으면 안 되나"
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
        {current && Number(current.method_diff_krw) !== 0 && (
          <p className="mt-3 rounded-lg bg-canvas-soft px-3 py-2 text-[11px] leading-relaxed text-ink-secondary">
            <strong className="text-ink">두 방식의 차이</strong> — 체결일 환율로
            계산하면 {formatKrwSigned(current.gain_krw)}, 증권사가 준 값(주가손익 +
            환차손익)은 {formatKrwSigned(current.gain_krw_broker)} 입니다. 차이{" "}
            {formatKrwSigned(current.method_diff_krw)}.{" "}
            {Math.abs(Number(current.headroom_krw)) >
            Math.abs(Number(current.method_diff_krw)) ? (
              <>
                다만 기본공제까지 여유가 {formatKrwString(current.headroom_krw)} 라
                이 차이로 세액이 달라지지는 않습니다.
              </>
            ) : (
              <>
                이 차이가 과세표준을 바꿀 수 있는 크기입니다 — 증권사 원장으로
                확인하세요.
              </>
            )}
          </p>
        )}
      </Modal>
    </>
  );
}

/**
 * 서버 문구의 `**강조**` 만 굵게 그린다.
 *
 * ⚠️dangerouslySetInnerHTML 을 쓰지 않는다. 지금은 서버 상수라 안전하지만,
 *   나중에 이 목록에 증권사 메시지나 사용자 입력이 섞이면 그때는 늦는다.
 */
function Emphasized({ text }: { text: string }) {
  return (
    <>
      {text.split(/\*\*(.+?)\*\*/g).map((part, i) =>
        // split 의 홀수 인덱스가 캡처 그룹(강조 대상)이다.
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

function Breakdown({
  year,
  onExplain,
}: {
  year: TaxYear;
  onExplain: () => void;
}) {
  const overDeduction = Number(year.taxable_base_krw) > 0;
  const comprehensive =
    Number(year.dividend_krw) > Number(year.comprehensive_threshold_krw);

  return (
    <div className="space-y-3">
      <div>
        <p className="mb-1.5 text-[11px] font-bold text-ge-navy">
          양도소득 ({year.year})
        </p>
        <Line label="양도가액" value={year.proceeds_krw} />
        <Line label="취득가액" value={year.cost_basis_krw} negate />
        <Line label="필요경비 (수수료·세금)" value={year.expense_krw} negate />
        <div className="my-1 border-t border-hairline" />
        <Line label="양도차익" value={year.gain_krw} signed strong />
        <Line label="기본공제" value={year.deduction_krw} negate />
        <div className="my-1 border-t border-ink" />
        <Line label="과세표준" value={year.taxable_base_krw} strong />
        <Line
          label={`세율 (양도 20% + 지방 2%)`}
          value={`${(Number(year.tax_rate) * 100).toFixed(0)}%`}
          raw
        />
        <div className="mt-1.5 flex items-baseline justify-between rounded-lg bg-canvas-soft px-2.5 py-2">
          <span className="text-[12px] font-bold text-ink">예상 세액</span>
          <span className="text-[16px] font-extrabold tabular-nums text-ink">
            {formatKrwString(year.tax_krw)}
          </span>
        </div>
      </div>

      {/* ⚠️"세금 없음"으로 끝내지 않는다 — 세액 0 과 신고 불필요는 다른 말이다. */}
      <p
        className={cn(
          "rounded-lg px-2.5 py-2 text-[11px] font-semibold leading-snug",
          overDeduction ? "bg-ask-soft text-ask" : "bg-canvas-soft text-ink-secondary",
        )}
      >
        {overDeduction ? (
          <>
            양도차익이 기본공제 {formatKrwString(year.deduction_krw)} 를 넘었습니다.
            세액이 발생하는 구간입니다.
          </>
        ) : (
          <>
            양도차익이 기본공제 아래라 <strong>계산상 세액은 0</strong> 입니다.
            다만 기본공제는 신고를 통해 적용되는 것이라{" "}
            <strong>세액 0 과 신고 불필요는 다른 말</strong>입니다 — 신고 의무는
            세무 전문가에게 확인하세요.
          </>
        )}
      </p>

      <div>
        <p className="mb-1.5 text-[11px] font-bold text-ge-navy">
          배당소득 ({year.year})
        </p>
        <Line label={`수령 배당 (${year.dividend_count}건)`} value={year.dividend_krw} />
        <Line
          label="금융소득종합과세 기준"
          value={year.comprehensive_threshold_krw}
        />
        <p className="mt-1.5 text-[11px] leading-relaxed text-ink-muted">
          {comprehensive ? (
            <>
              기준을 넘었습니다 — 분리과세로 끝나지 않고 종합과세 대상이 될 수
              있습니다.
            </>
          ) : (
            <>
              기준 아래라 통상 분리과세로 끝납니다. 다만 이 금액이 원천징수 전인지
              후인지 확인할 수 없어 <strong>세액은 계산하지 않았습니다</strong>.
            </>
          )}
        </p>
      </div>

      <button
        type="button"
        onClick={onExplain}
        className="text-[11px] font-bold text-ge-point underline-offset-2 hover:underline"
      >
        이 화면의 한계 →
      </button>
    </div>
  );
}

function Line({
  label,
  value,
  negate,
  signed,
  strong,
  raw,
}: {
  label: string;
  value: string;
  negate?: boolean;
  signed?: boolean;
  strong?: boolean;
  raw?: boolean;
}) {
  const shown = raw
    ? value
    : negate
      ? `-${formatKrwString(value)}`
      : signed
        ? formatKrwSigned(value)
        : formatKrwString(value);
  return (
    <div className="flex items-baseline justify-between">
      <span
        className={cn(
          "text-[12px]",
          strong ? "font-bold text-ink" : "text-ink-secondary",
        )}
      >
        {label}
      </span>
      <span
        className={cn(
          "tabular-nums",
          strong
            ? "text-[13px] font-extrabold text-ink"
            : "text-[12px] font-semibold text-ink-secondary",
        )}
      >
        {shown}
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
