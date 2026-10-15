"use client";

import { StubCard, toneOf } from "@/components/stub";
import { formatKrwSigned, formatKrwString } from "@/lib/format";
import { cn } from "@/lib/utils";
import { usePerformanceSeries } from "./queries";

// 8. 이 숫자들이 어떻게 이어지나 — 주가 손익 + 환율 등 = 원화 증감.
//
// ★2026-10-15 한 화면 통합: 옛 수익률 추이 화면에서 '환율 등'·'원화 증감' 칸을 눌러 열던
//   팝업을 맨 아래 섹션으로 꺼냈다. 요약 칸을 누르면 여기로 내려온다.
//
// ★2026-09-22: 예탁자산(원화 환산액)과 증권사 일별 손익(주가 손익, 환율 없음)이 서로
//   반대되는 말을 하는 것처럼 보였다. 실측: USD/KRW 1,530.11 → 1,384.86 (−9.49%) 구간에서
//   두 숫자 차이 ₩3,203,574 ÷ 9.49% ≈ ₩33,757,366 으로 구간 평균 주식평가액과 거의 같다.
//   ⚠️'환율 등'은 **잔차**다 — 배당·수수료·원장 잡음도 여기로 들어온다.
// ★2026-10-05 출발점·끝점을 적는다 — 맨 위 첫 칸(내 계좌)과 같은 05-31 종가에서 센다.

export function BridgeSection() {
  const perf = usePerformanceSeries();
  const data = perf.data;
  const bridge = data?.bridge ?? null;

  return (
    <section id="bridge" className="scroll-mt-28">
      <StubCard title="이 숫자들이 어떻게 이어지나" subtitle="주가 손익 + 환율 등 = 원화 증감">
        <div className="max-w-2xl">
          <div className="mb-3 rounded-xl border border-hairline bg-canvas-soft/60 p-3">
            <BridgeRow label="주가 손익" value={bridge?.price_pnl_krw} note="증권사 일별 손익 합" />
            <BridgeRow label="환율 등 (잔차)" value={bridge?.fx_effect_krw} note="남는 차이" />
            <div className="mt-1.5 border-t border-hairline pt-1.5">
              <BridgeRow
                label="원화 증감"
                value={bridge?.asset_change_krw}
                note="끝자산 − 시작자산 − 순입금"
                strong
              />
            </div>
          </div>
          {data?.start_base_date && (
            <p className="text-[11px] font-medium leading-snug text-ink-muted">
              시작자산 {data.start_base_date} 종가 {formatKrwString(data.start_assets_krw)} → 끝자산{" "}
              {data.last_date} {formatKrwString(data.end_assets_krw)} · 순입금{" "}
              {formatKrwSigned(data.net_deposit_krw)}. 맨 위 첫 칸 &apos;원화 실질&apos;과 같은
              출발점이다.
            </p>
          )}
        </div>
      </StubCard>
    </section>
  );
}

function BridgeRow({
  label,
  value,
  note,
  strong,
}: {
  label: string;
  value: string | null | undefined;
  note: string;
  strong?: boolean;
}) {
  return (
    <div className="flex items-baseline justify-between py-0.5">
      <span
        className={cn(
          "text-[12px]",
          strong ? "font-extrabold text-ink" : "font-semibold text-ink-secondary",
        )}
      >
        {label}
        <span className="ml-1.5 text-[10px] font-medium text-ink-faint">{note}</span>
      </span>
      <span
        className={cn(
          "tabular-nums",
          strong ? "text-[15px] font-extrabold" : "text-[13px] font-bold",
          toneOf(value ?? null) === "up"
            ? "text-bid"
            : toneOf(value ?? null) === "down"
              ? "text-ask"
              : "text-ink",
        )}
      >
        {formatKrwSigned(value)}
      </span>
    </div>
  );
}
