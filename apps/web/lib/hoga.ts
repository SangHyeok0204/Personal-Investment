// CHECK 호가 5단 가격/잔량에서 뽑는 파생 지표 — iNAV 카드와 랜딩 알림이 공유한다.
// (2026-07-20 CHECK 에이전트가 askPrices/bidPrices 를 싣기 시작하면서 추가)

import type { HogaEtf } from "./api";

// KRX 국내 ETF 호가단위 — 2,000원 미만 1원, 2,000원 이상 5원.
// 모니터링 대상 ETF는 전부 2,000원 이상이라 실질 5원 단위 (2026-07-20 사용자 확인).
export function tickSize(price: number): number {
  return price < 2000 ? 1 : 5;
}

// 유효호가 범위 — 최우선호가에서 이 틱 수 이내의 잔량만 "체결가 근처 물량"으로 인정한다.
// 5틱 = 사다리가 촘촘하면 5단 호가 전량. 벌어진 종목에서 멀리 있는 잔량이 제외된다.
export const DEPTH_TICKS = 5;

// 최우선 매도(매수) 호가가 시장가(현재가)에서 이 틱 수 "이상" 벌어지면 멀다고 본다.
// 매수·매도가 둘 다 멀면 [호가 없음], 한쪽이라도 이 안이면 물량만 본다 (2026-07-21 사용자 확정).
export const PROXIMITY_TICKS = 4;

// 5틱 합산 잔량이 이 수치 미만이면 [물량 부족]. 피드의 obThreshold 가 없을 때만 쓰는 폴백.
export const DEPTH_QTY_MIN = 10_000;

// 실제괴리 절대값이 이 % 이상이면 "괴리율 큼" 알림 (2026-07-21 사용자 요청).
export const DEV_ABS_ALERT_PCT = 1.0;

export interface HogaMetrics {
  bestBid: number | null;
  bestAsk: number | null;
  tick: number;
  mid: number | null;
  spread: number | null;
  spreadTicks: number | null;
  askDepth: number;
  bidDepth: number;
  askGap: boolean;
  bidGap: boolean;
  // 중간값 기준 장중괴리(%) — 체결 공백으로 마지막 체결가가 굳었을 때의 왜곡을 뺀 값.
  midPremiumPct: number | null;
}

export function toNum(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function sumAll(qtys: number[] | null | undefined): number {
  return (qtys ?? []).reduce((s, v) => s + (toNum(v) ?? 0), 0);
}

// 최우선호가에서 DEPTH_TICKS 이내 레벨의 잔량만 합산.
// 가격 배열이 없는 구 피드에서는 전량 합산으로 되돌아간다.
function nearTouchDepth(
  prices: number[] | null | undefined,
  qtys: number[] | null | undefined,
  best: number | null,
  tick: number,
): number {
  if (!prices?.length || !qtys?.length || best == null) return sumAll(qtys);
  const limit = tick * DEPTH_TICKS;
  let total = 0;
  for (let i = 0; i < prices.length; i += 1) {
    const price = toNum(prices[i]);
    if (price == null || price <= 0) continue;
    if (Math.abs(price - best) <= limit) total += toNum(qtys[i]) ?? 0;
  }
  return total;
}

// 호가 사다리가 1틱 간격으로 이어지지 않으면(중간 틱이 비면) true.
function hasGap(prices: number[] | null | undefined, tick: number): boolean {
  const valid = (prices ?? [])
    .map(toNum)
    .filter((p): p is number => p != null && p > 0);
  for (let i = 1; i < valid.length; i += 1) {
    if (Math.abs(valid[i] - valid[i - 1]) > tick) return true;
  }
  return false;
}

export function hogaMetrics(etf: HogaEtf): HogaMetrics {
  const bestBid = toNum(etf.bestBid);
  const bestAsk = toNum(etf.bestAsk);
  const tick = tickSize(bestAsk ?? bestBid ?? toNum(etf.price) ?? 0);
  const paired = bestBid != null && bestAsk != null && bestBid > 0 && bestAsk > 0;
  const spread = paired ? (bestAsk as number) - (bestBid as number) : null;
  const mid = paired ? ((bestBid as number) + (bestAsk as number)) / 2 : null;
  const nav = toNum(etf.nav);

  // 잔량 폴백: askQtys 가 없으면 구 asks(매도5→매도1)를 뒤집어 매도1 기준으로 맞춘다.
  const askQtys = etf.askQtys?.length ? etf.askQtys : [...(etf.asks ?? [])].reverse();
  const bidQtys = etf.bidQtys?.length ? etf.bidQtys : (etf.bids ?? []);

  return {
    bestBid,
    bestAsk,
    tick,
    mid,
    spread,
    spreadTicks: spread != null && tick > 0 ? spread / tick : null,
    askDepth: nearTouchDepth(etf.askPrices, askQtys, bestAsk, tick),
    bidDepth: nearTouchDepth(etf.bidPrices, bidQtys, bestBid, tick),
    askGap: hasGap(etf.askPrices, tick),
    bidGap: hasGap(etf.bidPrices, tick),
    midPremiumPct:
      mid != null && nav != null && nav > 0 ? (mid / nav - 1) * 100 : null,
  };
}
