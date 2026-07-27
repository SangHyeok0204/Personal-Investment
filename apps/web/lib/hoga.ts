// CHECK 호가 5단 가격/잔량에서 뽑는 파생 지표 — iNAV 카드와 랜딩 알림이 공유한다.
// (2026-07-20 CHECK 에이전트가 askPrices/bidPrices 를 싣기 시작하면서 추가)

import type { HogaEtf } from "./api";

// KRX 국내 ETF 호가단위 — 2,000원 미만 1원, 2,000원 이상 5원.
// 모니터링 대상 ETF는 전부 2,000원 이상이라 실질 5원 단위 (2026-07-20 사용자 확인).
export function tickSize(price: number): number {
  return price < 2000 ? 1 : 5;
}

// 실제괴리 절대값이 이 % 이상이면 "괴리율 큼" 알림 (2026-07-21 사용자 요청).
export const DEV_ABS_ALERT_PCT = 1.0;

// 호가카드가 그리는 연속 틱 수 (매도·매수 각각).
export const LADDER_LEVELS = 5;

// "제대로 제출된 호가(인정호가)"로 볼 최소 잔량 — 이 잔량 이상 실린 틱만 인정한다.
// (2026-07-24 사용자 확정: 1,000주 이상)
export const RECOGNIZED_QTY_MIN = 1_000;

// 스프레드 알림 최소 틱 — 인정 스프레드가 이 틱 미만(1~2틱)이면 정상으로 보고 알리지
// 않는다 (2026-07-24 사용자 확정).
export const SPREAD_ALERT_MIN_TICKS = 3;

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
// 매도·매수 각각 최우선호가부터 처음 1,000주 이상 실린 틱을 "인정호가"로 잡고,
// (인정매도호가 − 인정매수호가) 를 틱단위로 나눈 값이 그 ETF의 스프레드 폭이다
// (2026-07-24 사용자 재정의). 얇은 호가만 앞에 깔려 있으면 인정호가가 뒤로 밀려
// 스프레드가 벌어진다. 5단 안에 한쪽이라도 인정호가가 없으면 판정 불가로 null.
export function recognizedSpreadTicks(etf: HogaEtf): number | null {
  const recAsk = recognizedQuotePrice(etf.askPrices, etf.askQtys);
  const recBid = recognizedQuotePrice(etf.bidPrices, etf.bidQtys);
  if (recAsk == null || recBid == null) return null;
  const tick = tickSize(recAsk);
  if (tick <= 0) return null;
  return Math.round((recAsk - recBid) / tick);
}

// LP가 매도·매수 한쪽이라도 물량을 아예 깔지 않았는가 — lpAskQtys/lpBidQtys 전 틱
// 합이 0이면 그 방향엔 LP 호가가 없다. 지금까진 인정 스프레드 판정이 null 로 떨어져
// 조용히 넘어갔는데(=인정호가 없음), 이 경우를 '물량X' 알림으로 드러낸다
// (2026-07-27 사용자 요청). 두 배열이 모두 없으면(LP 미탑재 구 피드) 판정 불가로
// false — "LP 데이터 없음"과 "LP 물량 없음"은 다르다.
export function lpQuoteMissing(etf: HogaEtf): boolean {
  const { lpAskQtys, lpBidQtys } = etf;
  if (lpAskQtys == null && lpBidQtys == null) return false;
  const sum = (arr: number[] | null | undefined): number =>
    (arr ?? []).reduce((acc: number, v) => acc + (toNum(v) ?? 0), 0);
  return sum(lpAskQtys) <= 0 || sum(lpBidQtys) <= 0;
}
