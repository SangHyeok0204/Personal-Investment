"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  useEtfs,
  useRecentPosts,
  useSpies,
  useStats,
  type RecentFilters,
  type SdSentiment,
  type SdSource,
} from "@/lib/stock-discussion";
import { Topbar } from "@/components/layout/topbar";
import { PageContainer } from "@/components/layout/page-header";
import { ApiErrorBanner } from "@/components/states";
import { HealthPanel } from "@/components/stock-discussion/health-panel";
import { FilterRail, type FilterState } from "@/components/stock-discussion/filter-rail";
import { SpyPanel } from "@/components/stock-discussion/spy-panel";
import { FeedHeader } from "@/components/stock-discussion/feed-header";
import { PostFeed } from "@/components/stock-discussion/post-feed";
import { buildSpyIndex } from "@/components/stock-discussion/brand";

const PAGE_SIZE = 100;
const RENDER_MAX = 500;

const EMPTY_FILTER: FilterState = {
  issuer: null,
  category: null,
  etfCode: null,
  source: null,
  sentiment: null,
};

export default function StockDiscussionPage() {
  const queryClient = useQueryClient();

  const [filter, setFilter] = useState<FilterState>(EMPTY_FILTER);
  const [searchInput, setSearchInput] = useState("");
  const [keyword, setKeyword] = useState("");
  const [limit, setLimit] = useState(PAGE_SIZE);
  const [seenBaseline, setSeenBaseline] = useState(0);
  const initedRef = useRef(false);

  const etfs = useEtfs();
  const stats = useStats();
  const spies = useSpies();

  // 검색 300ms 디바운스 → keyword (settle 당 1회 요청). limit 도 초기화.
  useEffect(() => {
    const id = setTimeout(() => {
      setKeyword(searchInput.trim());
      setLimit(PAGE_SIZE);
    }, 300);
    return () => clearTimeout(id);
  }, [searchInput]);

  // 서버 필터 해석: ETF 선택 우선(etf_code), 아니면 발행사/분류 → etf_codes.
  const effectiveFilters: RecentFilters = useMemo(() => {
    if (filter.etfCode) {
      return { etf_code: filter.etfCode, source: filter.source, keyword };
    }
    if (filter.issuer || filter.category) {
      const codes = (etfs.data ?? [])
        .filter(
          (e) =>
            (!filter.issuer || e.issuer === filter.issuer) &&
            (!filter.category || e.category === filter.category),
        )
        .map((e) => e.code);
      return { etf_codes: codes, source: filter.source, keyword };
    }
    return { source: filter.source, keyword };
  }, [filter.etfCode, filter.issuer, filter.category, filter.source, keyword, etfs.data]);

  const recent = useRecentPosts(effectiveFilters, { limit });

  // 최초 로드 시 baseline = 현재 max src_id (초기엔 신규 0).
  useEffect(() => {
    const items = recent.data?.items;
    if (!items || items.length === 0) return;
    if (!initedRef.current) {
      initedRef.current = true;
      setSeenBaseline(items.reduce((m, p) => Math.max(m, p.src_id), 0));
    }
  }, [recent.data]);

  // 감성 칩 = 로드된 윈도우 클라 필터(서버 감성 파라미터 없음).
  const posts = useMemo(() => {
    const items = recent.data?.items ?? [];
    if (!filter.sentiment) return items;
    return items.filter((p) => p.sentiment === filter.sentiment);
  }, [recent.data, filter.sentiment]);

  const newCount = useMemo(
    () =>
      (recent.data?.items ?? []).filter((p) => p.src_id > seenBaseline).length,
    [recent.data, seenBaseline],
  );

  const spyIndex = useMemo(() => buildSpyIndex(spies.data), [spies.data]);
  const etfByCode = useMemo(
    () => new Map((etfs.data ?? []).map((e) => [e.code, e] as const)),
    [etfs.data],
  );

  const loadedCount = recent.data?.items.length ?? 0;
  const total = recent.data?.total ?? 0;
  const hasMore = limit < RENDER_MAX && loadedCount >= limit && total > loadedCount;

  // ── 핸들러 ──
  const resetLimit = () => setLimit(PAGE_SIZE);
  const setIssuer = (v: string | null) => {
    setFilter((f) => ({ ...f, issuer: v, etfCode: null }));
    resetLimit();
  };
  const setCategory = (v: string | null) => {
    setFilter((f) => ({ ...f, category: v, etfCode: null }));
    resetLimit();
  };
  const setEtf = (v: string | null) => {
    setFilter((f) => ({ ...f, etfCode: v }));
    resetLimit();
  };
  const setSource = (v: SdSource | null) => {
    setFilter((f) => ({ ...f, source: v }));
    resetLimit();
  };
  const setSentiment = (v: SdSentiment | null) =>
    setFilter((f) => ({ ...f, sentiment: v }));

  const resetNew = () => {
    const max = (recent.data?.items ?? []).reduce(
      (m, p) => Math.max(m, p.src_id),
      seenBaseline,
    );
    setSeenBaseline(max);
  };

  const onRefresh = () => {
    queryClient.invalidateQueries({ queryKey: ["sd"] });
    resetNew();
  };

  const onSpyClick = (author: string) => {
    setSearchInput(author);
    setKeyword(author); // 즉시 반영(디바운스 우회) — 인라인 검색, 드로어 없음
    resetLimit();
    if (typeof window !== "undefined") {
      window.scrollTo({ top: 0, behavior: "smooth" });
    }
  };

  return (
    <>
      {/* 신규 카드 슬라이드인 — src_id 키 diff 로만 발동(D7) */}
      <style>{`@keyframes sdSlideIn{from{opacity:0;transform:translateY(-6px)}to{opacity:1;transform:translateY(0)}}.sd-new{animation:sdSlideIn .35s ease-out}`}</style>

      <Topbar
        title="종토방"
        subtitle="기타 · 네이버·토스 종목토론방 실시간 모니터링"
      />
      <PageContainer wide>
        {recent.isError && (
          <div className="mb-4">
            <ApiErrorBanner error={recent.error} />
          </div>
        )}

        <div className="flex flex-col gap-5 lg:flex-row">
          <aside className="flex w-full shrink-0 flex-col gap-3 lg:sticky lg:top-4 lg:max-h-[calc(100vh-2rem)] lg:w-[300px] lg:self-start lg:overflow-y-auto lg:pr-1">
            <HealthPanel stats={stats.data} />
            <FilterRail
              etfs={etfs.data ?? []}
              stats={stats.data}
              filter={filter}
              onIssuer={setIssuer}
              onCategory={setCategory}
              onEtf={setEtf}
              onSource={setSource}
              onSentiment={setSentiment}
            />
            <SpyPanel spies={spies.data} onSpyClick={onSpyClick} />
          </aside>

          <div className="min-w-0 flex-1">
            <FeedHeader
              stats={stats.data}
              newCount={newCount}
              onResetNew={resetNew}
              onRefresh={onRefresh}
              isFetching={recent.isFetching || stats.isFetching}
              searchInput={searchInput}
              onSearchInput={setSearchInput}
            />
            <PostFeed
              posts={posts}
              total={total}
              keyword={keyword}
              seenBaseline={seenBaseline}
              spyIndex={spyIndex}
              etfByCode={etfByCode}
              loading={recent.isLoading}
              hasMore={hasMore}
              onLoadMore={() => setLimit((l) => Math.min(RENDER_MAX, l + PAGE_SIZE))}
            />
          </div>
        </div>
      </PageContainer>
    </>
  );
}
