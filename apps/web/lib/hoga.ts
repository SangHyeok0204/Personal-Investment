// CHECK 호가 가격/잔량에서 뽑는 파생 지표 — iNAV 카드와 랜딩 알림이 공유한다.
// (2026-07-20 CHECK 에이전트가 askPrices/bidPrices 를 싣기 시작하면서 추가)
// 단수는 피드가 주는 대로 따른다 — 현재 가격 5단/LP잔량 10단, CHECK 가 가격을 10단으로
// 늘리면 판정이 자동으로 넓어진다 (아래 recognizedSpread 주석 참고).

import type { HogaEtf } from "./api";

// KRX 국내 ETF 호가단위 — 2,000원 미만 1원, 2,000원 이상 5원.
// 모니터링 대상 ETF는 전부 2,000원 이상이라 실질 5원 단위 (2026-07-20 사용자 확인).
export function tickSize(price: number): number {
  return price < 2000 ? 1 : 5;
}

/* ── 심각도 밴드 ────────────────────────────────────────────────────────
   2026-07-30 사용자 지시로 조건부 알림을 폐기하고 **상시 요약**으로 바꿨다. 이제
   "발화할지"가 아니라 "얼마나 심각한지"를 색으로 나타낸다 — 전 ACE 종목의 값을
   항상 띄우고, 아래 밴드로 옅은 회색 / 오렌지 / 빨강을 고른다.
   구 임계값(SPREAD_ALERT_MIN_BP=15bp 발화 하한, DEV_ABS_ALERT_PCT=1% 발화,
   SPREAD_MISSING_MAX_TICKS=20틱 초과 물량X)은 발화 개념과 함께 폐기됐다. */
export type Severity = "calm" | "warn" | "crit";

// 호가 스프레드(bp) — 0~20 회색 · 20~40 오렌지 · 40↑ 빨강.
export const SPREAD_WARN_BP = 20;
export const SPREAD_CRIT_BP = 40;

export function spreadSeverity(bp: number): Severity {
  if (bp >= SPREAD_CRIT_BP) return "crit";
  if (bp >= SPREAD_WARN_BP) return "warn";
  return "calm";
}

// 괴리(%) — 절댓값 0~1 회색 · 1~2 오렌지 · 2↑ 빨강. 실제·장중 동일 기준.
export const DEV_WARN_PCT = 1;
export const DEV_CRIT_PCT = 2;

export function devSeverity(pct: number): Severity {
  const abs = Math.abs(pct);
  if (abs >= DEV_CRIT_PCT) return "crit";
  if (abs >= DEV_WARN_PCT) return "warn";
  return "calm";
}

// 호가카드가 그리는 연속 틱 수 (매도·매수 각각).
export const LADDER_LEVELS = 5;

// "제대로 제출된 호가(인정호가)"로 볼 최소 잔량 — 이 잔량 이상 실린 틱만 인정한다.
// (2026-07-24 사용자 확정: 1,000주 이상)
export const RECOGNIZED_QTY_MIN = 1_000;


export function toNum(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

// 최우선호가에서 시작하는 연속 LADDER_LEVELS 틱 창. 각 틱에 그 가격의 잔량을
// 채우고, 호가가 없는 틱은 0 으로 남긴다. CHECK 피드는 "잔량이 있는 상위 5호가"를
// 주기 때문에 빈 틱을 건너뛰어 멀리 있는 호가가 5단 안에 섞여 들어오는데, 이 창은
// 그걸 실제 틱 위치대로 펴서 보여준다 (2026-07-23 사용자 확정: 기준=최우선호가,
// 창 밖 잔량은 표시하지 않음). 가격 배열이 없는 구 피드에서는 null.
export function tickLadder(
  prices: number[] | null | undefined,
  qtys: number[] | null | undefined,
  tick: number,
  side: "ask" | "bid",
): { price: number; qty: number }[] | null {
  const best = toNum(prices?.[0]);
  if (best == null || best <= 0 || tick <= 0) return null;
  const qtyByPrice = new Map<number, number>();
  for (let i = 0; i < (prices?.length ?? 0); i += 1) {
    const price = toNum(prices?.[i]);
    if (price == null || price <= 0) continue;
    qtyByPrice.set(price, (qtyByPrice.get(price) ?? 0) + (toNum(qtys?.[i]) ?? 0));
  }
  return Array.from({ length: LADDER_LEVELS }, (_, i) => {
    const price = side === "ask" ? best + tick * i : best - tick * i;
    return { price, qty: qtyByPrice.get(price) ?? 0 };
  });
}

// 판정에 쓸 가격 사다리 — 10단(askPrices10/bidPrices10)이 오면 그걸, 없으면 기존 5단.
// lpAskQtys/lpBidQtys 와 같은 인덱스 격자이고, 10단의 앞 5개가 기존 5단과 일치함을
// 실측 확인했다 (2026-07-29, 14/14).
//
// ★단조성이 깨지는 지점에서 자른다. 호가장 가격은 매도 오름차순·매수 내림차순이
// 반드시 성립하는데, CHECK 10단 도입 직후 매수 10번째 칸이 매도 값으로 오염되는
// 종목이 있었다(2026-07-29 실측 2/14 — 매수 호가가 성겨 10번째 단계가 소스의 가격
// 창을 벗어난 경우). 오염된 가격을 그대로 쓰면 스프레드가 음수·과대로 뒤집혀
// 조용히 틀린 알림이 나가므로, 깨진 뒤는 신뢰하지 않고 버린다. 피드가 정상이면
// 아무것도 자르지 않으므로 고쳐진 뒤에도 그대로 둬도 된다.
function ladderPrices(
  wide: number[] | null | undefined,
  narrow: number[] | null | undefined,
  side: "ask" | "bid",
): number[] {
  const src = wide?.length ? wide : (narrow ?? []);
  const out: number[] = [];
  for (const raw of src) {
    const price = toNum(raw);
    if (price == null || price <= 0) break;
    const prev = out[out.length - 1];
    if (prev != null && (side === "ask" ? price <= prev : price >= prev)) break;
    out.push(price);
  }
  return out;
}

// 최우선호가에서 바깥으로 훑어 처음으로 잔량 ≥ RECOGNIZED_QTY_MIN 인 호가의 가격.
// (askPrices/bidPrices 는 둘 다 인덱스 0 = 최우선. CHECK 피드가 빈 틱을 건너뛰어
// 주므로 인덱스가 아니라 실제 가격을 쓴다.) 5단 안에 인정호가가 없으면 null.
function recognizedQuotePrice(
  prices: number[] | null | undefined,
  qtys: number[] | null | undefined,
): number | null {
  if (!prices?.length || !qtys?.length) return null;
  for (let i = 0; i < prices.length; i += 1) {
    const p = toNum(prices[i]);
    const q = toNum(qtys[i]);
    if (p != null && p > 0 && q != null && q >= RECOGNIZED_QTY_MIN) return p;
  }
  return null;
}

// 인정 스프레드를 틱 수로 환산한다 — 카드 현재가와 무관한 순수 호가 스프레드.
// 인정 스프레드 — 매도·매수 각각 최우선호가부터 바깥으로 훑어 처음 1,000주 이상 실린
// 호가를 "인정호가"로 잡고, (인정매도호가 − 인정매수호가) 가 스프레드다. 카드 현재가와
// 무관한 순수 호가 스프레드로, 얇은 호가만 앞에 깔려 있으면 인정호가가 뒤로 밀려
// 벌어진다 (2026-07-24 사용자 정의). 한쪽이라도 인정호가가 없으면 null.
//
// ★기준 잔량 = LP 호가(lpAskQtys/lpBidQtys). 예전엔 총호가(askQtys/bidQtys)를 썼는데,
// 2026-07-27 카드 표시가 LP 로 넘어간 뒤로 "화면은 LP, 알림은 총호가"로 갈라져 있었다
// (2026-07-29 사용자 지시로 LP 통일). 총호가는 리테일이 섞여 LP 성실도를 못 잰다.
//
// ★원·틱 둘 다 낸다 — 화면 칩은 bp(원 ÷ 체결가), 임계 판정(3틱·20틱)은 틱이라 둘 다
// 필요하다 (2026-07-29). 스캔 범위는 ladderPrices 가 주는 길이를 따른다 — 10단 피드가
// 붙은 뒤로는 10단계, 구 피드에서는 5단계.
export function recognizedSpread(
  etf: HogaEtf,
): { won: number; ticks: number } | null {
  const recAsk = recognizedQuotePrice(
    ladderPrices(etf.askPrices10, etf.askPrices, "ask"),
    etf.lpAskQtys,
  );
  const recBid = recognizedQuotePrice(
    ladderPrices(etf.bidPrices10, etf.bidPrices, "bid"),
    etf.lpBidQtys,
  );
  if (recAsk == null || recBid == null) return null;
  const tick = tickSize(recAsk);
  if (tick <= 0) return null;
  const won = recAsk - recBid;
  return { won, ticks: Math.round(won / tick) };
}

// 스프레드를 bp 로 — 실시간 체결가 대비 몇 bp 벌어졌는가 (2026-07-29 사용자 지정).
// 체결가가 없으면 null (호출부가 틱 표시로 폴백한다).
export function spreadBp(won: number, price: number | null | undefined): number | null {
  const p = toNum(price);
  if (p == null || p <= 0) return null;
  return (won / p) * 10_000;
}

// LP가 매도·매수 한쪽이라도 물량을 아예 깔지 않았는가 — 이 경우를 '물량X' 알림으로
// 드러낸다 (2026-07-27 사용자 요청). 두 배열이 모두 없으면(LP 미탑재 구 피드) 판정
// 불가로 false — "LP 데이터 없음"과 "LP 물량 없음"은 다르다.
//
// ★물량X = "한쪽 또는 양쪽에 LP 인정호가(1,000주 이상)가 아예 없어 스프레드를 낼 수
// 없다" 하나뿐이다. 구 ②'20틱 초과'는 2026-07-30 사용자 지시로 빠졌다 — 상시 요약으로
// 바뀐 뒤로는 아무리 벌어져도 숫자가 나오므로 그 bp 를 빨강으로 보여주는 편이
// '물량X'보다 많은 것을 말해준다(실측 309bp 사례).
//
// 구 '상위 5틱 창(tickLadder) LP 잔량 합 ≤ 0' 규칙(2026-07-28)은 삭제했다 — ①에
// 완전히 흡수된다: 창 합이 0이면 그 안에 1,000주 이상인 틱도 없으므로 인정호가가
// 없고, 이미 null 로 잡힌다. 창을 버린 덕에 판정 범위가 '연속 5틱'에서 '수신된
// 호가단계 전부'로 넓어졌다(빈 틱을 건너뛴 피드에선 5단계가 15틱까지 뻗는다).
//
// ※ 2026-07-29 CHECK 10단 확장으로 6~10단계도 가격이 붙어 판정에 들어온다
// (ladderPrices 참고). 격자 구조는 api.ts 의 lpAskQtys 주석 참고.
export function lpQuoteMissing(etf: HogaEtf): boolean {
  const { lpAskQtys, lpBidQtys } = etf;
  if (lpAskQtys == null && lpBidQtys == null) return false;
  return recognizedSpread(etf) == null;
}
