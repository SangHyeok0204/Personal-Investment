"use client";

import { memo } from "react";
import type { VcCategory, VcCompany } from "@/lib/api-valuechain";
import { cn } from "@/lib/utils";
import { catStyle, jumpTo, plainText, subAnchor } from "./model";

// 기업 카드 — 원본 리포트(`article.card`)의 정보 순서를 그대로 따른다:
//   이름 / 티커·국가 → 영문명 → role → points → ＋다른 소속 · 출처 태그.
// 비상장은 점선 테두리·옅은 바탕으로 한 단계 물러나 보이게 한다(투자 대상이 아니라 지형 정보).
// ★분류 섹터: role 이 L3 원문("후보: …")이면 "후보" 칩을 붙이고, points(근거 문장)는 3줄로 자른다(title 에 전문).
//   url 이 있으면 출처 태그 대신 새 탭 "근거 ↗" 링크.
// ★`fan` (카드 부채, card-fan.tsx): 고정 크기 + 왼쪽 "등"(분류 색 띠)에 티커·이름을 세로로 — 겹쳐 등만 보여도
//   어떤 카드인지 읽힌다(트럼프 모서리의 숫자·무늬 자리). 내용은 줄 수를 잘라 카드 안에 가둔다.

const CANDIDATE = /^후보\s*[:：]\s*/;

function tickerLine(co: VcCompany): string {
  const country = [co.country, ...co.other_countries].filter(Boolean).join("/");
  if (!co.listed || !co.ticker) return country ? `비상장 · ${country}` : "비상장";
  // 거래소가 국가 코드와 같으면(US·US) 한 번만 쓴다.
  const venue = co.exchange && co.exchange !== co.country ? `${co.exchange} · ` : "";
  return `${co.ticker} · ${venue}${country}`;
}

/** 카드 등 — 분류 색 띠 위에 티커(가로)와 이름(세로). 겹친 부채에서 보이는 유일한 부분. */
function Spine({ co }: { co: VcCompany }) {
  return (
    <div
      aria-hidden
      className={cn(
        "flex w-[34px] shrink-0 flex-col items-center gap-1.5 bg-[color:var(--c)] px-0.5 pb-2 pt-2 text-white",
        !co.listed && "opacity-55",
      )}
    >
      <span className="max-w-full break-all text-center font-mono text-[10.5px] font-extrabold leading-[1.05] tracking-tight">
        {co.ticker ?? "—"}
      </span>
      <span className="min-h-0 flex-1 overflow-hidden text-ellipsis whitespace-nowrap text-[11px] font-bold leading-none opacity-90 [writing-mode:vertical-rl]">
        {co.name}
      </span>
      {(co.held || co.watch) && (
        <span className="flex flex-col gap-1">
          {co.held && <span title="보유" className="h-2 w-2 rounded-full bg-white ring-2 ring-bid" />}
          {co.watch && <span title="관심" className="h-2 w-2 rounded-full bg-white ring-2 ring-ask" />}
        </span>
      )}
    </div>
  );
}

export const CompanyCard = memo(function CompanyCard({
  id,
  co,
  byCode,
  fan = false,
}: {
  id: string;
  co: VcCompany;
  byCode: Map<string, VcCategory>;
  /** 카드 부채 안 — 고정 크기·등 띠·줄 수 제한. */
  fan?: boolean;
}) {
  const also = co.categories.filter((c) => c !== co.primary);
  const body = (
    <>
      <div className="flex items-baseline justify-between gap-2">
        <h5
          className={cn(
            "min-w-0 text-[14.5px] font-extrabold leading-snug tracking-tight",
            fan && "line-clamp-2",
            co.listed ? "text-ink" : "text-ink-secondary",
          )}
        >
          {co.name}
          {co.held && (
            <span className="ml-1.5 inline-block translate-y-[-1px] rounded bg-bid-soft px-1.5 py-px align-middle text-[10px] font-bold text-bid">
              보유
            </span>
          )}
          {co.watch && (
            <span className="ml-1 inline-block translate-y-[-1px] rounded bg-ask-soft px-1.5 py-px align-middle text-[10px] font-bold text-ask">
              관심
            </span>
          )}
        </h5>
        <span
          className="shrink-0 whitespace-nowrap font-mono text-[11px] tabular-nums text-ink-faint"
          title={co.exchange ?? undefined}
        >
          {tickerLine(co)}
        </span>
      </div>

      {co.en && co.en !== co.name && (
        <div className="mt-0.5 truncate text-[11.5px] font-medium text-ink-muted">{co.en}</div>
      )}

      {co.role && (
        <p className={cn("mt-1.5 text-[12.5px] font-semibold leading-snug text-ink-secondary", fan && "line-clamp-2")}>
          {CANDIDATE.test(co.role) ? (
            <>
              <span
                title="L3 후보 — 검증 전"
                className="mr-1 inline-block translate-y-[-1px] rounded bg-canvas-soft px-1.5 py-px align-middle text-[10px] font-bold text-ink-muted ring-1 ring-inset ring-hairline"
              >
                후보
              </span>
              {co.role.replace(CANDIDATE, "")}
            </>
          ) : (
            co.role
          )}
        </p>
      )}

      {co.points.length > 0 && (
        <ul className="mt-1.5 space-y-0.5 pl-4 text-[12.5px] leading-relaxed text-ink-secondary marker:text-ink-faint [list-style:disc]">
          {(fan ? co.points.slice(0, 1) : co.points).map((p, i) => (
            <li key={i} title={plainText(p)}>
              {/* ⚠️clamp 는 li 가 아니라 안쪽 span 에 — li 에 -webkit-box 를 주면 disc 표식이 사라진다. */}
              <span className="line-clamp-3">{plainText(p)}</span>
            </li>
          ))}
        </ul>
      )}

      {(also.length > 0 || co.src.length > 0 || co.url) && (
        <div className="mt-auto flex flex-wrap gap-1 pt-2.5">
          {also.map((code) => {
            const c = byCode.get(code);
            return (
              <button
                key={code}
                type="button"
                style={catStyle(c?.color)}
                onClick={() => jumpTo(subAnchor(code))}
                title={`${code} ${c?.name ?? ""} 로 이동`}
                className="inline-flex items-baseline gap-1 rounded border-l-2 border-[color:var(--c)] bg-canvas-soft px-1.5 py-px text-[11px] font-semibold text-ink transition-colors hover:bg-brand-blue-soft/60 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-blue"
              >
                <span className="text-ink-faint">＋</span>
                <span className="whitespace-nowrap font-bold text-[color:var(--c)]">{code}</span>
                {c?.name}
              </button>
            );
          })}
          {co.url ? (
            <a
              href={co.url}
              target="_blank"
              rel="noopener noreferrer"
              title={[co.src.join(" · "), co.url].filter(Boolean).join(" — ")}
              className="rounded bg-canvas-soft px-1.5 py-px text-[11px] font-bold text-brand-point transition-colors hover:bg-brand-blue-soft/60 hover:underline focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-blue"
            >
              근거 ↗
            </a>
          ) : (
            co.src.map((s) => (
              <span
                key={s}
                className="rounded bg-canvas-soft px-1.5 py-px text-[11px] font-medium text-ink-muted"
              >
                {s}
              </span>
            ))
          )}
        </div>
      )}
    </>
  );

  if (fan)
    return (
      <article
        id={`vc-co-${id}`}
        tabIndex={0}
        aria-label={`${co.name}${co.ticker ? ` (${co.ticker})` : ""}`}
        className={cn(
          "flex h-full w-full scroll-mt-56 overflow-hidden rounded-xl border bg-canvas shadow-card transition-shadow duration-200 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-blue group-hover/slot:shadow-panel",
          co.listed ? "border-[color:color-mix(in_srgb,var(--c)_35%,transparent)]" : "border-dashed border-ink-muted/40",
        )}
      >
        <Spine co={co} />
        <div className="flex min-w-0 flex-1 flex-col overflow-hidden px-3 py-2.5">{body}</div>
      </article>
    );

  return (
    <article
      id={`vc-co-${id}`}
      className={cn(
        "flex scroll-mt-56 sm:scroll-mt-40 flex-col rounded-xl border px-3.5 py-3 transition-shadow",
        co.listed
          ? "border-hairline bg-canvas shadow-card hover:shadow-panel"
          : "border-dashed border-ink-muted/30 bg-canvas/60",
      )}
    >
      {body}
    </article>
  );
});
