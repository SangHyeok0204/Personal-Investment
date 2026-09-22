"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { PageContainer } from "@/components/layout/page-header";
import { Topbar } from "@/components/layout/topbar";
import { useAccount } from "@/components/layout/account-context";
import { Modal } from "@/components/ui/modal";
import { Cell, DataTable, NotConnectedBanner, StatTile, StubCard } from "@/components/stub";
import { getFxExposure, type FxExposure } from "@/lib/api";
import { formatKrwSigned, formatKrwString } from "@/lib/format";
import { cn } from "@/lib/utils";

// 환노출 — 원화로 살아가며 달러 자산을 들고 있을 때의 위험.
//
// ★이 화면이 답하는 것: **내 손익 중 얼마가 종목이고 얼마가 환율인가.**
//   실현 쪽에 좋은 예가 있다 — NVDA 는 주가로 +₩50,182 벌었는데 환율이
//   1,524 → 1,380 으로 빠져 환차 -₩121,201, 합치면 -₩71,019 였다.
//
// ⚠️**매입 환율을 증권사가 주지 않는다.** trades.amount_krw 는 82건 전부 비어
//   있고 일별성과의 환율 칸도 530행 전부 비어 있다. 그래서 보유 종목의
//   "얼마에 샀나"는 매수 체결일의 일별 종가 환율로 **추정**한다.
//   추정과 실측을 화면에서 **섞지 않는다** — 평가 환차는 추정, 실현 환차는 실측이다.
//
// ★2026-09-23: **외화 예수금도 노출에 넣는다.** 달러로 남아 있는 돈은 환율이
//   움직이면 그대로 원화 가치가 바뀐다. 예전에는 주식만 세서 민감도 표가 그만큼
//   작게 나왔다(실측 $982.92 = ₩1,320,356 이 빠져 있었다). 분모도 총자산으로
//   맞췄다 — 배분 화면의 통화 축과 같은 기준이다.
//   ⚠️다만 예수금에는 '얼마에 샀나'가 없다. 그래서 **평가 환차손익 추정에는
//     넣지 않는다** — 없는 매입 환율을 지어내지 않는다.

function rate(value: string | null): string {
  if (value == null) return "—";
  const n = Number(value);
  return Number.isFinite(n) ? n.toLocaleString("ko-KR", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : "—";
}

function pct(value: string | null, digits = 2): string {
  if (value == null) return "—";
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  return `${n > 0 ? "+" : ""}${(n * 100).toFixed(digits)}%`;
}

function tone(value: string | null): "up" | "down" | undefined {
  if (value == null) return undefined;
  const n = Number(value);
  if (!Number.isFinite(n) || n === 0) return undefined;
  return n > 0 ? "up" : "down";
}

export default function FxExposurePage() {
  const { accountId, connected } = useAccount();
  const [noteOpen, setNoteOpen] = useState(false);

  const fx = useQuery({
    queryKey: ["fxExposure", accountId],
    queryFn: () => getFxExposure(accountId),
    staleTime: 60_000,
  });

  const data = fx.data;
  const positions = data?.positions ?? [];

  return (
    <>
      <Topbar title="환노출" subtitle="USD/KRW 노출 · 환차손익 · 민감도" />
      <PageContainer fit>
        {!connected && !fx.isLoading && <NotConnectedBanner what="보유 종목" />}

        <div className="grid shrink-0 grid-cols-2 gap-2.5 lg:grid-cols-4">
          <StatTile
            label="환노출 비중"
            value={data?.exposure_ratio ? pct(data.exposure_ratio, 0).replace("+", "") : null}
            hint={
              data?.exposed_value_krw
                ? `${formatKrwString(data.exposed_value_krw)} 가 ${data.exposed_currency} 자산` +
                  (data.foreign_cash_krw
                    ? ` (예수금 ${formatKrwString(data.foreign_cash_krw)} 포함)`
                    : "")
                : "총자산 중 외화 (예수금 포함)"
            }
            loading={fx.isLoading}
          />
          <StatTile
            label="현재 환율"
            value={data?.current_rate ? rate(data.current_rate) : null}
            hint={
              data?.estimated_entry_rate
                ? `추정 매입 ${rate(data.estimated_entry_rate)} · ${pct(data.rate_change_ratio)}`
                : "USD/KRW"
            }
            accent="auto"
            loading={fx.isLoading}
          />
          <StatTile
            label="평가 환차손익"
            value={formatKrwSigned(data?.unrealized_fx_krw)}
            hint="추정 · 눌러서 설명"
            actionHint="눌러서 읽는 법 보기"
            onClick={() => setNoteOpen(true)}
            accent="auto"
            loading={fx.isLoading}
          />
          <StatTile
            label="실현 환차손익"
            value={formatKrwSigned(data?.realized_fx_krw)}
            hint="증권사 실측 · 청산분"
            accent="auto"
            loading={fx.isLoading}
          />
        </div>

        <div
          className={cn(
            "grid min-h-0 flex-1 gap-3",
            "grid-cols-1 auto-rows-[minmax(0,1fr)]",
            "md:grid-cols-2 lg:auto-rows-auto",
            "lg:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]",
          )}
        >
          <StubCard
            title="종목별 환노출"
            subtitle={`${positions.length}종목 + 예수금 · 매입 환율은 추정`}
            scrollBody
            action={
              <button
                type="button"
                onClick={() => setNoteOpen(true)}
                className="rounded-full bg-white/15 px-2.5 py-1 text-[11px] font-bold text-white transition-colors hover:bg-white/25"
              >
                읽는 법
              </button>
            }
          >
            <DataTable
              columns={["종목", "평가액", "추정 매입환율", "환차(추정)"]}
              align={["left", "right", "right", "right"]}
              empty={
                fx.isLoading
                  ? "불러오는 중…"
                  : connected
                    ? "외화 보유 종목이 없습니다"
                    : "계좌를 연동하면 환노출이 표시됩니다"
              }
            >
              {/* ⚠️예수금 줄이 없으면 **줄의 합이 위 '환노출 비중' 과 안 맞는다.**
                  분모에만 더하고 줄에서 빼는 것은 이 프로젝트에서 이미 한 번
                  버그로 겪은 모양이다. 매입 환율은 비워 둔다 — 예수금에는
                  '얼마에 샀나'가 없고, 0 으로 두면 '환차 없음'으로 읽힌다. */}
              {data?.foreign_cash_krw && (
                <tr className="border-b border-hairline bg-canvas-soft/40">
                  <Cell left strong>
                    <span className="flex items-center gap-1.5">
                      <span>예수금</span>
                      <span className="shrink-0 text-[10px] font-bold text-ink-faint">
                        {data.exposed_currency}
                      </span>
                    </span>
                  </Cell>
                  <Cell>{formatKrwString(data.foreign_cash_krw)}</Cell>
                  <Cell tone="muted">—</Cell>
                  <Cell tone="muted">—</Cell>
                </tr>
              )}
              {positions.map((p) => (
                <tr key={p.ticker} className="border-b border-hairline">
                  <Cell left strong>
                    <span className="flex items-center gap-1.5">
                      <span className="max-w-[140px] truncate">{p.name ?? p.ticker}</span>
                      <span className="shrink-0 text-[10px] font-bold text-ink-faint">
                        {p.ticker}
                      </span>
                    </span>
                  </Cell>
                  <Cell>{formatKrwString(p.market_value_krw)}</Cell>
                  <Cell tone={p.estimated_entry_rate == null ? "muted" : undefined}>
                    {rate(p.estimated_entry_rate)}
                  </Cell>
                  <Cell strong tone={tone(p.estimated_fx_pnl_krw)}>
                    {formatKrwSigned(p.estimated_fx_pnl_krw)}
                  </Cell>
                </tr>
              ))}
            </DataTable>
          </StubCard>

          <StubCard title="환율 민감도" subtitle="환율이 움직이면" scrollBody>
            {fx.isLoading ? (
              <Empty text="불러오는 중…" />
            ) : (data?.shocks.length ?? 0) === 0 ? (
              <Empty text="계산할 노출이 없습니다" />
            ) : (
              <>
                <p className="mb-2 text-[11px] leading-snug text-ink-muted">
                  종목 가격이 그대로일 때 환율만 움직이면 평가액이 이렇게 바뀝니다.
                </p>
                <DataTable columns={["환율 변동", "평가액", "증감"]} align={["left", "right", "right"]}>
                  {(data?.shocks ?? []).map((s) => (
                    <tr key={s.move} className="border-b border-hairline">
                      <Cell left strong>
                        {pct(s.move, 0)}
                      </Cell>
                      <Cell>{formatKrwString(s.value_krw)}</Cell>
                      <Cell strong tone={tone(s.delta_krw)}>
                        {formatKrwSigned(s.delta_krw)}
                      </Cell>
                    </tr>
                  ))}
                </DataTable>
                {data?.current_rate && (
                  <p className="mt-2 text-[11px] leading-relaxed text-ink-muted">
                    현재 {rate(data.current_rate)} 기준
                    {data.rate_as_of && ` (${data.rate_as_of})`}. 헤지는 하지 않은
                    상태이므로 노출 전액이 환율을 그대로 받습니다.
                  </p>
                )}
              </>
            )}
          </StubCard>
        </div>
      </PageContainer>

      <Modal
        open={noteOpen}
        onClose={() => setNoteOpen(false)}
        title="이 화면 읽는 법"
        subtitle="추정과 실측을 섞지 않는다"
      >
        <ul className="space-y-2.5 text-[12px] leading-relaxed text-ink-secondary">
          <li>
            <strong>매입 환율은 추정입니다.</strong> {data?.note}
          </li>
          <li>
            <strong>평가 환차손익</strong>은 &quot;지금 전부 원화로 바꾸면 환율
            때문에 얼마를 잃거나 벌었나&quot;입니다 — 평가액 × (1 − 매입환율 ÷
            현재환율). 매입 환율을 모르는 종목은 비워 둡니다(0 으로 두면 &quot;환차
            없음&quot;으로 읽힙니다).
          </li>
          <li>
            <strong>외화 예수금도 노출에 넣었습니다.</strong> 달러로 남아 있는
            돈은 환율이 움직이면 그대로 원화 가치가 바뀝니다. 다만 예수금에는
            &quot;얼마에 샀나&quot;가 없어 <strong>평가 환차손익 추정에는 넣지
            않았습니다</strong> — 없는 매입 환율을 지어내지 않습니다. 아래 민감도
            표에는 들어갑니다.
          </li>
          <li>
            <strong>실현 환차손익</strong>은 추정이 아닙니다. 이미 판 종목은
            증권사가 매수·매도 환율을 함께 주므로 그 값을 그대로 씁니다. 성격이
            달라 평가분과 합치지 않았습니다.
          </li>
          <li>
            <strong>종목 손익과 환 손익은 다른 사건입니다.</strong> 체결·실현손익 화면의
            NVDA 가 좋은 예입니다 — 주가로 +₩50,182 벌었는데 환율이 1,524 → 1,380
            으로 빠져 환차 -₩121,201, 합치면 -₩71,019 였습니다. 종목 선택이
            좋았는지는 주가 쪽만 봐야 합니다.
          </li>
        </ul>
      </Modal>
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
