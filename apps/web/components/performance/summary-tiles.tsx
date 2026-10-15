"use client";

import { StatTile } from "@/components/stub";
import { formatKrwCompactString, formatKrwSigned } from "@/lib/format";
import { pctOrNull } from "./format";
import { useAccountReturn, usePerformanceSeries } from "./queries";

// 1. 요약 타일 — 옛 수익률 추이 화면의 상단 넷.
//
// ★2026-09-22: **한 화면에서 서로 반대되는 말을 하고 있었다.** 상단 타일은
//   '입출금 제외 증감 −₩722,749 (−1.86%)', 월별 표의 손익 합은 '+₩2,469,456'.
//   둘 다 맞고, 다른 것을 재고 있었을 뿐이다.
//     · 예탁자산은 **원화 환산액** — 환율이 빠지면 종목이 그대로여도 줄어든다.
//     · 증권사 일별 손익(pl_amt)은 **주가 손익** — 환율이 들어 있지 않다.
//   그래서 나란히 두지 않고 **타일 넷이 왼쪽에서 오른쪽으로 더해지게** 했다:
//   주가 손익 → 환율 등 → 원화 증감.
//
// ⚠️'환율 등'은 **잔차**다. 환율이 대부분인 것은 확인했지만 배당·수수료·원장 잡음도
//   여기로 들어온다. 재지 않은 것을 잰 것처럼 부르지 않는다.
//
// ★2026-10-05 사용자 지정("5/31 기준으로 통일"): 주가 손익 · 환율 등 · 원화 증감도 첫 칸과
//   **같은 출발점**(05-31 종가 = /account-return 의 A0)에서 센다. 원화 증감 ÷ 원금 = 첫 칸의
//   '원화 실질 %' 다. ⚠️그래서 타일은 **기간 칩을 따르지 않는다**(늘 시작일부터).
//   ⚠️주가 손익(키움 일별 손익 합)은 첫 칸 분자(실현 + 평가 − 시작 평가익)와 같은 값이
//   아니다 — 월별 막대·누적손익과 맞추려고 키움 일별 손익 합을 쓴다. 차이는 잔차로 간다.
//
// ★2026-10-15 한 화면 통합: 옛 벤치마크·성과 분석·기간 리포트 화면도 첫 칸에 같은
//   '내 계좌 (환율 제외)'(정본 /account-return)를 두고 있었다 — 같은 정의·같은 출처라
//   여기 한 칸으로 줄였다. 원화 실질(환차 포함)은 둘째 줄에 그대로 같이 적는다(둘 다 표시).
//   옛 팝업으로 열던 것은 이제 아래 섹션이다 — 누르면 그 섹션으로 내려간다.

export function SummaryTiles({
  onMonthList,
  onBridge,
}: {
  /** 주가 손익 칸 → 월별 섹션의 월별 표. */
  onMonthList: () => void;
  /** 환율 등 · 원화 증감 칸 → '이 숫자들이 어떻게 이어지나' 섹션. */
  onBridge: () => void;
}) {
  const perf = usePerformanceSeries();
  const account = useAccountReturn();
  const data = perf.data;
  const acct = account.data;
  const bridge = data?.bridge ?? null;
  const twrPct =
    bridge?.twr == null
      ? null
      : `${Number(bridge.twr) > 0 ? "+" : ""}${(Number(bridge.twr) * 100).toFixed(2)}%`;

  return (
    <div className="grid grid-cols-2 gap-2.5 lg:grid-cols-4">
      {/* ⚠️타일 넷은 **왼쪽에서 오른쪽으로 이어진다.**
          주가 손익 + 환율 등 = 원화 증감. 셋을 따로 읽지 말 것. */}
      {/* ★정본 — 시작일 이후 손익 ÷ 투입 원금(A0 + 순외부입금). */}
      <StatTile
        label="내 계좌 (환율 제외)"
        value={pctOrNull(acct?.return_ratio)}
        // ★2026-10-04 "둘 다 표시": 위 값은 환율 제외(키움 손익). 원화 실질(환차 포함,
        //   총자산 − 원금)을 보조로 같이 적는다.
        //   ★2026-10-05 한 줄이면 잘린다(1280px 실측) — 손익 ÷ 원금 / 기간·원화 실질 두 줄로.
        hint={
          acct?.pnl_since_start_krw != null && acct.invested_krw != null
            ? `${Number(acct.pnl_since_start_krw) > 0 ? "+" : ""}${formatKrwCompactString(acct.pnl_since_start_krw)} ÷ 원금 ${formatKrwCompactString(acct.invested_krw)}`
            : "시작일 이후 손익 ÷ 투입 원금"
        }
        subHint={
          [
            acct?.return_date ? `${acct.start.slice(5)} ~ ${acct.return_date.slice(5)}` : null,
            acct?.krw_return_ratio != null ? `원화 실질 ${pctOrNull(acct.krw_return_ratio)}` : null,
          ]
            .filter(Boolean)
            .join(" · ") || undefined
        }
        accent="auto"
        loading={account.isLoading}
      />
      <StatTile
        label="주가 손익"
        value={formatKrwSigned(bridge?.price_pnl_krw)}
        hint={
          twrPct == null
            ? "환율 제외 · 증권사 일별 손익 합"
            : `환율 제외 · 참고: 시간가중(TWR) ${twrPct}`
        }
        actionHint="눌러서 월별 표 보기"
        onClick={onMonthList}
        accent="auto"
        loading={perf.isLoading}
      />
      <StatTile
        label="환율 등"
        value={formatKrwSigned(bridge?.fx_effect_krw)}
        hint="잔차"
        actionHint="눌러서 상세 보기"
        onClick={onBridge}
        accent="auto"
        loading={perf.isLoading}
      />
      <StatTile
        label="원화 증감 (합)"
        value={formatKrwSigned(data?.gain_krw)}
        // ★2026-10-05 시작자산 = 05-31 종가(첫 칸의 A0). 이 값 ÷ 원금 = 첫 칸 '원화 실질'.
        hint={`끝자산 − 시작자산(${data?.start_base_date?.slice(5) ?? "—"} 종가) − 순입금`}
        actionHint="눌러서 이어지는 법 보기"
        onClick={onBridge}
        accent="auto"
        loading={perf.isLoading}
      />
    </div>
  );
}
