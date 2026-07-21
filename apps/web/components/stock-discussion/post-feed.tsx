"use client";

import type { SdEtf, SdPost } from "@/lib/stock-discussion";
import { Skeleton } from "@/components/ui/skeleton";
import { PostCard } from "./post-card";
import { issuerColor } from "./brand";

interface PostFeedProps {
  posts: SdPost[];
  total: number;
  keyword: string;
  seenBaseline: number;
  spyIndex: Map<string, string[]>;
  etfByCode: Map<string, SdEtf>;
  loading: boolean;
  hasMore: boolean;
  onLoadMore: () => void;
}

export function PostFeed({
  posts,
  total,
  keyword,
  seenBaseline,
  spyIndex,
  etfByCode,
  loading,
  hasMore,
  onLoadMore,
}: PostFeedProps) {
  const kw = keyword.trim();

  if (loading) {
    return (
      <div className="flex flex-col gap-2.5">
        {Array.from({ length: 6 }).map((_, i) => (
          <Skeleton key={i} className="h-28 w-full rounded-xl" />
        ))}
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2.5">
      {kw && (
        <div className="rounded-lg border border-hairline bg-canvas-soft px-3 py-2 text-[12px] text-ink-muted">
          🔍 검색어 <span className="font-semibold text-ge-navy">{kw}</span> · 매칭{" "}
          <span className="font-semibold text-ge-navy tabular-nums">
            {total.toLocaleString("ko-KR")}
          </span>
          건 (DB 전체 검색)
        </div>
      )}

      {posts.length === 0 ? (
        <div className="rounded-xl border border-dashed border-hairline bg-canvas-soft px-6 py-16 text-center text-sm text-ink-muted">
          표시할 게시물이 없습니다
        </div>
      ) : (
        <>
          {posts.map((post) => {
            const meta = etfByCode.get(post.etf_code);
            return (
              <PostCard
                key={`${post.source}-${post.src_id}`}
                post={post}
                keyword={kw}
                isNew={post.src_id > seenBaseline}
                accent={issuerColor(meta?.issuer, meta?.name ?? post.etf_name)}
                spyLabels={spyIndex.get(`${post.source}|${post.author}`)}
              />
            );
          })}

          {hasMore && (
            <button
              type="button"
              onClick={onLoadMore}
              className="mt-1 self-center rounded-lg border border-hairline bg-canvas px-5 py-2 text-[13px] font-semibold text-ge-point shadow-card transition-colors hover:bg-ge-blue-bg"
            >
              더 보기
            </button>
          )}
        </>
      )}
    </div>
  );
}
