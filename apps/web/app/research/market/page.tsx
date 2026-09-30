import {
  MarketResearchTabs,
  type MarketTabKey,
} from "@/components/market-research/market-research-tabs";

// 시장 리서치 — 관심종목 · 시장지표 · 계절성 · AI Key Data · 국내 ETF 신규상장 탭.
//
// ★2026-09-27 계획 S2: 구 `/watchlist` · `/market` · `/market/seasonality` ·
//   `/ai-key-data` 는 next.config.mjs 의 redirect 로 여기 `?tab=` 으로 온다.
// ⚠️Next 15 에서 searchParams 는 Promise 다. 서버에서 읽어 넘기므로 클라이언트는
//   useSearchParams(→ Suspense 경계 필요)를 쓰지 않는다.
// ⚠️탭 목록 검사는 여기 따로 둔다 — "use client" 모듈의 함수는 서버에서 부를 수 없다.

const TAB_KEYS: MarketTabKey[] = ["watchlist", "market", "seasonality", "ai", "etf"];

export default async function MarketResearchPage({
  searchParams,
}: {
  searchParams: Promise<{ tab?: string | string[] }>;
}) {
  const { tab } = await searchParams;
  const value = Array.isArray(tab) ? tab[0] : tab;
  const initialTab = TAB_KEYS.find((k) => k === value) ?? "watchlist";
  return <MarketResearchTabs initialTab={initialTab} />;
}
