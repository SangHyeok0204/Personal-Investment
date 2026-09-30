"use client";

import { useQuery } from "@tanstack/react-query";
import { StubCard } from "@/components/stub";
import { getEtfNewListing } from "@/lib/api";
import { ListingView, ReportView } from "./new-listing-views";

// 국내 ETF 신규상장 탭 — 성적표(최근 상장일) · 금일 상장 + 상장 예정(DART).
// ★서버가 30분마다 KRX·DART 를 따라잡아 메모리에 들고 있다. 여기선 그 캐시만 읽는다.

export function EtfTab() {
  const q = useQuery({
    queryKey: ["etf-new-listing"],
    queryFn: getEtfNewListing,
    staleTime: 5 * 60_000,
    refetchInterval: 10 * 60_000,
  });
  return (
    <div className="grid min-h-0 flex-1 gap-3 lg:grid-cols-2">
      <StubCard title="신규 상장 ETF 성적표" subtitle="KRX · 상장일 하루치" className="min-h-[420px]" scrollBody>
        <ReportView data={q.data} error={q.error} />
      </StubCard>
      <StubCard title="금일 상장 · 상장 예정" subtitle="KRX 상장 목록 · DART 펀드공시" className="min-h-[420px]" scrollBody>
        <ListingView data={q.data} error={q.error} />
      </StubCard>
    </div>
  );
}
