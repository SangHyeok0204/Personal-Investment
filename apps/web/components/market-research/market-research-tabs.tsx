"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { PageContainer } from "@/components/layout/page-header";
import { Topbar } from "@/components/layout/topbar";
import { TabChips } from "@/components/ai-key-data/tab-chips";
import { AiKeyDataTab } from "./ai-key-data-tab";
import { EtfTab } from "./etf-listing/etf-tab";
import { MarketTab } from "./market-tab";
import { SeasonalityTab } from "./seasonality-tab";
import { WatchlistTab } from "./watchlist-tab";

// 시장 리서치 — 관심종목 · 시장지표 · 계절성 · AI Key Data · 국내 ETF 신규상장을 한 화면(탭)으로.
//
// ★2026-09-27 계획 S2: 탭은 `?tab=` 로 딥링크된다(구 경로 redirect 대상).
//   ⚠️탭 값은 page.tsx 가 `searchParams` 로 읽어 넘긴다 — 여기서 useSearchParams
//   를 쓰면 빌드가 Suspense 경계를 요구한다. 전환은 router.replace 로 URL 만 고친다.

export const MARKET_TABS = [
  { key: "watchlist", label: "관심종목" },
  { key: "market", label: "시장지표" },
  { key: "seasonality", label: "계절성" },
  { key: "ai", label: "AI Key Data" },
  { key: "etf", label: "국내 ETF 신규상장" },
] as const;

export type MarketTabKey = (typeof MARKET_TABS)[number]["key"];

export function MarketResearchTabs({ initialTab }: { initialTab: MarketTabKey }) {
  const router = useRouter();
  const [tab, setTab] = useState<MarketTabKey>(initialTab);

  // 뒤로/앞으로·링크로 ?tab= 이 바뀌면 따라간다.
  useEffect(() => setTab(initialTab), [initialTab]);

  const change = (next: MarketTabKey) => {
    setTab(next);
    router.replace(`?tab=${next}`, { scroll: false });
  };

  return (
    <>
      <Topbar
        title="시장 리서치"
        subtitle="관심종목 · 시장지표 · 계절성 · AI Key Data · 국내 ETF 신규상장"
        showAccountContext={false}
      />
      <PageContainer fit>
        <div className="flex shrink-0 items-center rounded-xl bg-ge-header px-2 py-1.5 shadow-card">
          <TabChips tabs={[...MARKET_TABS]} value={tab} onChange={change} />
        </div>
        <div className="flex min-h-0 flex-1 flex-col gap-3">
          {tab === "watchlist" && <WatchlistTab />}
          {tab === "market" && <MarketTab />}
          {tab === "seasonality" && <SeasonalityTab />}
          {tab === "ai" && <AiKeyDataTab />}
          {tab === "etf" && <EtfTab />}
        </div>
      </PageContainer>
    </>
  );
}
