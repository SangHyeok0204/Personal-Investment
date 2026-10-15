"use client";

import { useState } from "react";
import { Modal } from "@/components/ui/modal";
import { CardEmpty, Cell, DataTable, StubCard } from "@/components/stub";
import type { Contribution } from "@/lib/api";
import { formatKrwSigned, formatKrwString } from "@/lib/format";
import { pct, pctPlain, toneOfRatio } from "./format";
import { useAnalytics } from "./queries";

// 6. 종목별 기여도 — 옛 성과 분석의 '종목 기여도 합계' 칸 → 팝업 표를 본문으로.
//
// 양식(ETF성과분석_양식_v2)에는 BM/Peer 대비 상대 기여도가 있지만 **뺐다**. 개인 계좌에는
// 비교 기준이 정의돼 있지 않아서, 아무 지수나 골라 "초과수익 +3%" 라고 쓰면 그 숫자에
// 근거가 없다. 절대 기여도만 낸다.
//
// ⚠️2026-09-22: **기준이 다른 숫자가 섞여 있었다.** 상단은 '전체 수익률 −1.98%', 이 표는
//   '합계 +8.64%'. 부호가 반대라 "종목은 다 잘했는데 왜 전체는 마이너스냐"로 읽힌다. 셋이 다르다:
//     · 기간    기간수익률은 조회 구간, 기여도는 **매입 시점 이후**
//     · 범위    기간수익률은 계좌 전체(판 것·배당·예수금 포함), 기여도는 **지금 들고 있는 종목만**
//     · 통화    기간수익률은 예탁자산 기반이라 **원화 기준**(환율 포함), 기여도는 원가·평가액
//               모두 오늘 환율로 환산해 **주가 기준**
//   숫자를 고치는 게 아니라 **기준을 화면에 적는다.** 위 섹션들과 더하거나 견주지 않는다.

export function ContributionSection() {
  const analytics = useAnalytics();
  const data = analytics.data;
  const [detail, setDetail] = useState<Contribution | null>(null);
  const items = data?.contributions ?? [];

  return (
    <section id="contribution" className="scroll-mt-28">
      <StubCard
        title="종목별 기여도"
        subtitle={
          data?.total_return
            ? `합계 ${pct(data.total_return)} · 보유분 · 매입 이후 · 주가 기준 · ${items.length}종목 · 행을 누르면 상세`
            : "보유분 · 매입 이후 · 주가 기준"
        }
      >
        {analytics.isLoading ? (
          <div className="h-[200px]">
            <CardEmpty text="불러오는 중…" />
          </div>
        ) : (
          <div className="max-h-[420px] overflow-y-auto">
            <DataTable columns={["종목", "비중", "손익", "기여도"]} empty="보유 종목이 없습니다">
              {items.map((c) => (
                <tr
                  key={c.asset_id}
                  onClick={() => setDetail(c)}
                  className="cursor-pointer border-b border-hairline transition-colors hover:bg-canvas-soft"
                >
                  <Cell left strong>
                    <span className="flex items-center gap-1.5">
                      <span className="max-w-[240px] truncate">{c.name ?? c.ticker}</span>
                      <span className="shrink-0 text-[10px] font-bold text-ink-faint">{c.ticker}</span>
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
        )}
      </StubCard>

      <Modal
        open={detail != null}
        onClose={() => setDetail(null)}
        title={detail?.name ?? detail?.ticker ?? ""}
        subtitle={detail?.ticker}
      >
        {detail && <ContributionDetail item={detail} />}
      </Modal>
    </section>
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
    <dl className="grid grid-cols-2 gap-x-5 gap-y-0">
      {rows.map(([label, value]) => (
        <div key={label} className="flex items-baseline justify-between border-b border-hairline py-2">
          <dt className="text-[12px] text-ink-secondary">{label}</dt>
          <dd className="text-[13px] font-bold tabular-nums text-ink">{value}</dd>
        </div>
      ))}
    </dl>
  );
}
