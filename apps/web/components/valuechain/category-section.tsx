"use client";

import { useState } from "react";
import { ArrowRight, ChevronDown } from "lucide-react";
import type { VcCategory, VcCompany } from "@/lib/api-valuechain";
import { CardFan } from "./card-fan";
import { catAnchor, catStyle, jumpTo, plainText, subAnchor } from "./model";

// 대분류 섹션(`section.cat`) → 중분류(`.subsec`) → 카드 부채.
// 대분류에 하위가 없으면 그 분류 자신의 카드를 바로 깐다.
// ★큰 섹터(기업 > 200)는 섹션당 `cap` 장까지만 먼저 깐다 — "나머지 N개 더 보기"로 편다.
//   content-visibility 는 쓰지 않는다(jumpTo 의 위치 계산이 자리표시 높이로 빗나감, 계획 §1 e).

const FLASH =
  "rounded-2xl transition-[background-color,box-shadow] duration-300 data-[flash=true]:bg-brand-blue-soft/40 data-[flash=true]:ring-2 data-[flash=true]:ring-brand-blue/70";

// ★2026-09-28: 카드 격자 대신 카드 부채(card-fan.tsx) — 손에 쥔 카드처럼 겹쳐 펼친다.
function CardGrid({
  ids,
  companies,
  byCode,
}: {
  ids: string[];
  companies: Record<string, VcCompany>;
  byCode: Map<string, VcCategory>;
}) {
  return <CardFan ids={ids} companies={companies} byCode={byCode} />;
}

function SubSection({
  sub,
  ids,
  companies,
  byCode,
  flowsOut,
}: {
  sub: VcCategory;
  ids: string[];
  companies: Record<string, VcCompany>;
  byCode: Map<string, VcCategory>;
  flowsOut: string[];
}) {
  return (
    <div id={subAnchor(sub.code)} className={`-mx-3 scroll-mt-52 sm:scroll-mt-36 px-3 py-3 ${FLASH}`}>
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
        <span className="font-mono text-[12.5px] font-bold text-[color:var(--c)]">{sub.code}</span>
        <h3 className="text-[16px] font-extrabold tracking-tight text-ink">{sub.name}</h3>
        <span className="text-[11.5px] font-semibold tabular-nums text-ink-faint">{ids.length}</span>
        {flowsOut.map((to) => (
          <button
            key={to}
            type="button"
            onClick={() => jumpTo(subAnchor(to))}
            className="inline-flex items-center gap-1 rounded-full border border-hairline bg-canvas px-2 py-px text-[11px] font-bold text-ink-secondary transition-colors hover:border-[color:var(--c)]"
          >
            <ArrowRight className="h-3 w-3 text-[color:var(--c)]" strokeWidth={2.5} />
            {to} {byCode.get(to)?.name}
          </button>
        ))}
      </div>
      {sub.desc && (
        <p className="mt-1 max-w-[90ch] text-[13px] leading-relaxed text-ink-muted">{plainText(sub.desc)}</p>
      )}
      {sub.market && (
        <p className="mt-1 flex items-baseline gap-1.5 text-[12px] font-semibold tabular-nums text-ink-secondary">
          <span className="rounded bg-canvas px-1.5 py-px text-[10px] font-bold text-ink-muted ring-1 ring-inset ring-hairline">
            시장
          </span>
          {sub.market}
        </p>
      )}
      <div className="mt-2.5">
        {ids.length > 0 ? (
          <CardGrid ids={ids} companies={companies} byCode={byCode} />
        ) : (
          <p className="text-[12px] font-semibold text-ink-faint">등록된 기업이 없습니다.</p>
        )}
      </div>
    </div>
  );
}

export function CategorySection({
  cat,
  subs,
  ownIds,
  companies,
  byCode,
  innerFlows,
  totalCompanies,
  cap,
}: {
  cat: VcCategory;
  /** 보일 중분류와 그 안의 보일 기업 id(필터 적용 후). */
  subs: { sub: VcCategory; ids: string[] }[];
  /** 하위 분류가 없는 대분류일 때 자기 카드. */
  ownIds: string[];
  companies: Record<string, VcCompany>;
  byCode: Map<string, VcCategory>;
  innerFlows: [string, string][];
  totalCompanies: number;
  /** 섹션당 첫 렌더 카드 상한(sector-view 가 계산). null 이면 접지 않는다. */
  cap: number | null;
}) {
  const [expanded, setExpanded] = useState(false);
  const total = ownIds.length + subs.reduce((n, s) => n + s.ids.length, 0);
  const folded = cap != null && total > cap && !expanded;
  const collapsible = cap != null && total > cap && expanded;
  // 상한을 앞에서부터 채운다 — 자기 카드 → 중분류 순. 접힌 동안 카드가 0장인 중분류는 머리도 뺀다.
  let left = folded ? cap : Infinity;
  const take = (ids: string[]) => {
    const out = ids.slice(0, Math.max(0, left));
    left -= out.length;
    return out;
  };
  const shownOwn = take(ownIds);
  const shownSubs = subs
    .map(({ sub, ids }) => ({ sub, ids: take(ids) }))
    .filter((s) => !folded || s.ids.length > 0);

  return (
    <section id={catAnchor(cat.code)} style={catStyle(cat.color)} className="scroll-mt-52 sm:scroll-mt-36 pt-2">
      <header className="flex flex-wrap items-baseline gap-x-2.5 gap-y-1 border-b-2 border-[color:var(--c)] pb-1.5">
        <span className="font-mono text-[14px] font-extrabold text-[color:var(--c)]">{cat.code}</span>
        <h2 className="text-[21px] font-extrabold tracking-tight text-ink">{cat.name}</h2>
        <span className="ml-auto text-[11.5px] font-semibold tabular-nums text-ink-faint">
          {cat.children.length > 0 && `중분류 ${cat.children.length} · `}기업 {totalCompanies}
        </span>
      </header>
      {cat.desc && (
        <p className="mt-2 max-w-[80ch] text-[13px] leading-relaxed text-ink-muted">{plainText(cat.desc)}</p>
      )}

      {cat.children.length === 0 ? (
        <div className="mt-3">
          <CardGrid ids={shownOwn} companies={companies} byCode={byCode} />
        </div>
      ) : (
        <div className="mt-1 space-y-1">
          {shownSubs.map(({ sub, ids }) => (
            <SubSection
              key={sub.code}
              sub={sub}
              ids={ids}
              companies={companies}
              byCode={byCode}
              flowsOut={innerFlows.filter(([a]) => a === sub.code).map(([, b]) => b)}
            />
          ))}
        </div>
      )}

      {(folded || collapsible) && (
        <button
          type="button"
          aria-expanded={expanded}
          onClick={() => {
            setExpanded((v) => !v);
            // 접을 때는 섹션 머리로 돌아간다 — 펼친 긴 목록 한가운데 남지 않게.
            if (expanded) jumpTo(catAnchor(cat.code), false);
          }}
          className="mt-3 flex w-full items-center justify-center gap-1.5 rounded-xl border border-dashed border-hairline bg-canvas px-3 py-2 text-[12.5px] font-bold text-ink-secondary transition-colors hover:border-[color:var(--c)] hover:text-ink focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-blue"
        >
          <ChevronDown
            className={`h-4 w-4 text-[color:var(--c)] transition-transform ${expanded ? "rotate-180" : ""}`}
            strokeWidth={2.5}
          />
          {folded ? (
            <>
              나머지 <b className="tabular-nums">{total - (cap ?? 0)}</b>개 더 보기
            </>
          ) : (
            "접기"
          )}
        </button>
      )}
    </section>
  );
}
