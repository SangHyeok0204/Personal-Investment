"use client";

import { memo, useState } from "react";
import { ExternalLink } from "lucide-react";
import type { SdPost } from "@/lib/stock-discussion";
import { formatDateTime, formatRelativeTime } from "@/lib/format";
import { SENTIMENT_STYLE, SOURCE_STYLE, escapeRegExp } from "./brand";
import { cn } from "@/lib/utils";

// keyword 하이라이트 — React 노드 분할만(D10, 원시 HTML 주입 금지 · 게시판 본문은 신뢰불가).
// 캡처 그룹 split 은 매칭 조각을 홀수 인덱스에 둔다 → lastIndex 상태 이슈 없음.
function highlight(text: string, keyword: string): React.ReactNode {
  const kw = keyword.trim();
  if (!kw) return text;
  const parts = text.split(new RegExp(`(${escapeRegExp(kw)})`, "gi"));
  if (parts.length === 1) return text;
  return parts.map((part, i) =>
    i % 2 === 1 ? (
      <mark
        key={i}
        className="rounded-[3px] bg-ge-blue-bg px-0.5 text-ge-navy"
      >
        {part}
      </mark>
    ) : (
      part
    ),
  );
}

function postTime(post: SdPost): string {
  if (post.post_date) return formatRelativeTime(post.post_date);
  // post_date_raw 는 파싱 불가 원문 → new Date() 금지, 그대로 노출(D7/C2).
  if (post.post_date_raw) return post.post_date_raw;
  return formatDateTime(post.crawled_at);
}

function PostCardImpl({
  post,
  keyword,
  isNew,
  accent,
  spyLabels,
}: {
  post: SdPost;
  keyword: string;
  isNew: boolean;
  accent: string;
  spyLabels: string[] | undefined;
}) {
  const [expanded, setExpanded] = useState(false);
  const overflowable = post.content.length > 120;
  const isSpy = !!spyLabels && spyLabels.length > 0;
  // 미등록 소스/감성 값이 와도 카드가 앱 전체를 죽이지 않게 muted 폴백.
  const src = SOURCE_STYLE[post.source] ?? {
    color: "#8a94a6",
    bg: "rgba(138,148,166,0.14)",
    label: post.source,
  };
  const sent = post.sentiment
    ? SENTIMENT_STYLE[post.sentiment] ?? {
        color: "#8a94a6",
        bg: "rgba(138,148,166,0.14)",
      }
    : null;

  return (
    <article
      className={cn(
        "rounded-xl border bg-canvas p-3.5 transition-shadow",
        isSpy
          ? "border-l-2 border-status-failed border-hairline shadow-[0_2px_10px_rgba(231,76,60,0.10)]"
          : "border-hairline shadow-card",
        isNew && "sd-new",
      )}
      style={isSpy ? { borderLeftColor: "#e74c3c" } : undefined}
    >
      {/* 헤더: ETF명(발행사색)+코드 · 소스 · 감성 */}
      <div className="mb-1.5 flex flex-wrap items-center gap-x-2 gap-y-1">
        <span
          className="text-[13px] font-bold"
          style={{ color: accent }}
        >
          {post.etf_name}
        </span>
        <span className="text-[10.5px] tabular-nums text-ink-muted">
          {post.etf_code}
        </span>
        <span className="flex-1" />
        <span
          className="rounded px-1.5 py-0.5 text-[10px] font-semibold"
          style={{ color: src.color, background: src.bg }}
        >
          {src.label}
        </span>
        {sent && (
          <span
            className="rounded px-1.5 py-0.5 text-[10px] font-semibold"
            style={{ color: sent.color, background: sent.bg }}
          >
            {post.sentiment}
            {post.sentiment_confidence != null &&
              ` ${Math.round(post.sentiment_confidence * 100)}%`}
          </span>
        )}
      </div>

      {/* 제목 */}
      <h3 className="text-[14px] font-semibold leading-snug text-ink">
        {highlight(post.title, keyword)}
      </h3>

      {/* 본문 — 클램프 + 하단 페이드, 클릭 확장 */}
      {post.content && (
        <div
          className={cn("relative mt-1.5", overflowable && "cursor-pointer")}
          onClick={overflowable ? () => setExpanded((v) => !v) : undefined}
        >
          <p
            className={cn(
              "whitespace-pre-wrap break-words text-[12.5px] leading-relaxed text-ink-secondary",
              !expanded && "max-h-[100px] overflow-hidden",
            )}
          >
            {highlight(post.content, keyword)}
          </p>
          {overflowable && !expanded && (
            <div className="pointer-events-none absolute inset-x-0 bottom-0 h-8 bg-gradient-to-t from-canvas to-transparent" />
          )}
        </div>
      )}

      {/* 메타 */}
      <div className="mt-2.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-ink-muted">
        <span className="font-medium text-ink-secondary">👤 {post.author}</span>
        {spyLabels?.map((l) => (
          <span key={l} className="font-semibold text-status-failed">
            🚨 {l}
          </span>
        ))}
        <span className="tabular-nums">👍 {post.likes}</span>
        <span className="tabular-nums">👎 {post.dislikes}</span>
        <span className="tabular-nums">💬 {post.comments}</span>
        <span className="flex-1" />
        <span className="text-ink-faint">{postTime(post)}</span>
        {post.source === "네이버" && (
          <a
            href={`https://finance.naver.com/item/board_read.naver?code=${post.etf_code}&nid=${post.post_id}`}
            target="_blank"
            rel="noopener noreferrer"
            onClick={(e) => e.stopPropagation()}
            className="inline-flex items-center gap-1 font-semibold text-ge-point hover:underline"
          >
            바로가기 <ExternalLink className="h-3 w-3" />
          </a>
        )}
      </div>
    </article>
  );
}

export const PostCard = memo(PostCardImpl);
