"use client";

import { Fragment } from "react";
import { ArrowRight } from "lucide-react";
import type { VcCategory } from "@/lib/api-valuechain";
import { cn } from "@/lib/utils";
import { catAnchor, catStyle, jumpTo, plainText, stageLevels, type VcIndex } from "./model";

// 단계 스트립(원본 `.chain`/`.stage`) — 대분류 한 장씩.
// ★화살표는 **최상위 분류끼리의 흐름(feedsInto)만** 그린다(계획 §12-5). 흐름으로 단계(열)를
//   나누므로 병렬 단계(신약·진단·기기)는 한 열에 쌓이고, 어디로 흘러가는지는 카드 아래 "→"
//   줄에 코드로 적는다 — 인접 열이 아닌 흐름(A→B-3)도 빠짐없이 읽힌다.

function StageCard({
  cat,
  idx,
  dimmed,
  compact = false,
  dense = false,
}: {
  cat: VcCategory;
  idx: VcIndex;
  dimmed: boolean;
  /** 한 열에 여러 장이 쌓일 때 — 설명을 두 줄로 줄여 열 높이를 맞춘다. */
  compact?: boolean;
  /** 흐름 없는 큰 분류 섹터(대분류 > 8) — 설명 1줄로 줄여 스트립이 화면을 덮지 않게. */
  dense?: boolean;
}) {
  const outs = idx.topFlows.filter(([a]) => a === cat.code).map(([, b]) => b);
  return (
    <button
      type="button"
      style={catStyle(cat.color)}
      onClick={() => jumpTo(catAnchor(cat.code), false)}
      className={cn(
        "group flex w-full flex-col rounded-xl border border-hairline border-t-[3px] border-t-[color:var(--c)] bg-canvas text-left shadow-card transition-all hover:-translate-y-px hover:shadow-panel focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-blue",
        dense ? "px-3 py-2.5" : "px-3.5 py-3",
        dimmed && "opacity-45",
      )}
    >
      <span className="font-mono text-[11.5px] font-bold text-[color:var(--c)]">{cat.code}</span>
      <span className={cn("mt-0.5 font-extrabold tracking-tight text-ink", dense ? "text-[14px] leading-snug" : "text-[15px]")}>
        {cat.name}
      </span>
      {cat.desc && (
        <span
          title={dense ? plainText(cat.desc) : undefined}
          className={cn(
            "mt-1 text-[12px] leading-relaxed text-ink-muted",
            dense ? "line-clamp-1" : compact ? "line-clamp-2" : "line-clamp-3",
          )}
        >
          {plainText(cat.desc)}
        </span>
      )}
      <span
        className={cn(
          "mt-auto flex flex-wrap items-center gap-x-2 gap-y-1 text-[11.5px] font-semibold tabular-nums text-ink-faint",
          dense ? "pt-1.5" : "pt-2.5",
        )}
      >
        <span>
          {cat.children.length > 0 && `중분류 ${cat.children.length} · `}기업{" "}
          {idx.companyCount.get(cat.code) ?? 0}
        </span>
        {outs.length > 0 && (
          <span className="inline-flex items-center gap-1 text-ink-secondary">
            <ArrowRight className="h-3 w-3" strokeWidth={2.5} />
            {outs.map((o) => (
              <span
                key={o}
                style={catStyle(idx.byCode.get(o)?.color)}
                className="font-mono font-bold text-[color:var(--c)]"
              >
                {o}
              </span>
            ))}
          </span>
        )}
      </span>
    </button>
  );
}

export function StageStrip({
  categories,
  idx,
  active,
}: {
  categories: VcCategory[];
  idx: VcIndex;
  /** 필터로 켜진 대분류(비어 있으면 전부). */
  active: Set<string>;
}) {
  const cols = stageLevels(categories, idx.topFlows);
  const dim = (c: VcCategory) => active.size > 0 && !active.has(c.code);

  // 흐름이 없는 섹터 — 단계 구분 없이 한 줄로 깐다(화살표 없음).
  //   대분류가 8장을 넘으면(분류 섹터 산업재 20장 등) 좁은 칸·설명 1줄의 조밀한 격자로.
  if (cols.length <= 1) {
    const dense = categories.length > 8;
    return (
      <nav
        aria-label="밸류체인 단계"
        className={cn(
          "grid",
          dense
            ? "gap-2 [grid-template-columns:repeat(auto-fill,minmax(160px,1fr))]"
            : "gap-2.5 [grid-template-columns:repeat(auto-fit,minmax(180px,1fr))]",
        )}
      >
        {categories.map((c) => (
          <StageCard key={c.code} cat={c} idx={idx} dimmed={dim(c)} dense={dense} />
        ))}
      </nav>
    );
  }

  return (
    <nav aria-label="밸류체인 단계" className="flex flex-col gap-1.5 md:flex-row md:items-stretch md:gap-0">
      {cols.map((col, i) => (
        <Fragment key={i}>
          {i > 0 && (
            <div aria-hidden className="flex items-center justify-center text-ink-faint md:w-8 md:shrink-0">
              <ArrowRight className="h-4 w-4 rotate-90 md:rotate-0" strokeWidth={2.25} />
            </div>
          )}
          {/* 한 장짜리 열은 늘리지 않고 세로 가운데 — 흐름도로 읽히게. */}
          <div className="grid min-w-0 flex-1 content-center gap-2 sm:grid-cols-2 md:grid-cols-1">
            {col.map((c) => (
              <StageCard key={c.code} cat={c} idx={idx} dimmed={dim(c)} compact={col.length > 1} />
            ))}
          </div>
        </Fragment>
      ))}
    </nav>
  );
}
