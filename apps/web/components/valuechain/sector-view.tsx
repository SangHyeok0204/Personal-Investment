"use client";

import { useDeferredValue, useMemo, useState } from "react";
import { ChevronRight, Search, X } from "lucide-react";
import { ApiErrorBanner, EmptyState } from "@/components/states";
import { Cell, DataTable } from "@/components/stub";
import { ApiError } from "@/lib/api";
import {
  useValueChainCatalog,
  useValueChainSector,
  type VcCategory,
  type VcSectorDetail,
} from "@/lib/api-valuechain";
import { cn } from "@/lib/utils";
import { CategorySection } from "./category-section";
import { StageStrip } from "./stage-strip";
import { buildIndex, catStyle, foldCap, matchesQuery } from "./model";

// 산업 밸류체인 섹터 상세 — 단계 스트립 → 도구줄 → 대분류 섹션들 → 투자 논지·출처.
// ★섹터 불문: 분류 코드·단계 수·깊이를 가정하지 않는다. 섹터 고르기는 허브(sector-hub.tsx)가 한다.
// ★그래프 뷰는 만들지 않는다 — 카드 리포트로만(계획 §5.3).

/** 대분류 아래 모든 하위 분류(깊이 우선, order 순). 3단 이상이어도 평평하게 편다. */
function descendants(c: VcCategory): VcCategory[] {
  return [...c.children]
    .sort((a, b) => a.order - b.order)
    .flatMap((x) => [x, ...descendants(x)]);
}

function Chip({
  active,
  onClick,
  children,
  color,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
  color?: string | null;
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      style={color ? catStyle(color) : undefined}
      className={cn(
        "inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-full border px-2.5 py-1 text-[12px] font-bold transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-blue",
        active
          ? "border-brand bg-brand text-white"
          : "border-hairline bg-canvas text-ink-secondary hover:border-ink-muted/40",
      )}
    >
      {color && (
        <span
          aria-hidden
          className={cn("h-2 w-2 rounded-full bg-[color:var(--c)]", active && "ring-1 ring-white/70")}
        />
      )}
      {children}
    </button>
  );
}

function Collapsible({
  title,
  count,
  children,
}: {
  title: string;
  count: number;
  children: React.ReactNode;
}) {
  return (
    <details className="group rounded-2xl border border-hairline bg-canvas shadow-card [&_summary::-webkit-details-marker]:hidden">
      <summary className="flex cursor-pointer select-none items-center gap-2 px-4 py-2.5 text-[13px] font-extrabold text-ink">
        <ChevronRight className="h-4 w-4 text-ink-muted transition-transform group-open:rotate-90" />
        {title}
        <span className="text-[11.5px] font-semibold tabular-nums text-ink-faint">{count}</span>
      </summary>
      <div className="border-t border-hairline px-4 pb-4 pt-3">{children}</div>
    </details>
  );
}

function SectorBody({ d }: { d: VcSectorDetail }) {
  const idx = useMemo(() => buildIndex(d), [d]);
  const tops = useMemo(() => [...d.categories].sort((a, b) => a.order - b.order), [d]);

  const [query, setQuery] = useState("");
  const [active, setActive] = useState<Set<string>>(new Set());
  const [mineOnly, setMineOnly] = useState(false);
  const q = useDeferredValue(query.trim().toLowerCase());

  const allIds = Object.keys(d.companies);
  const mineCount = allIds.filter((id) => d.companies[id].held || d.companies[id].watch).length;

  // 필터 적용 후 보일 섹션·중분류·기업.
  const view = useMemo(() => {
    const ok = (id: string) => {
      const co = d.companies[id];
      if (!co) return false;
      if (mineOnly && !co.held && !co.watch) return false;
      return matchesQuery(co, q);
    };
    // ★대분류 칩이 정확히 1개면 그 분류를 "보려는" 것이다 — 접기를 풀어 전부 보인다(예금·대출 은행 171장).
    const narrowing = q !== "" || mineOnly || active.size === 1;
    let shown = 0;
    const sections = tops
      .filter((c) => active.size === 0 || active.has(c.code))
      .map((cat) => {
        const ownIds = cat.companies.filter(ok);
        const subs = descendants(cat)
          .map((sub) => ({ sub, ids: sub.companies.filter(ok) }))
          // 좁혀 보는 중에는 빈 중분류를 숨긴다. 평소에는 빈 칸도 지형이므로 둔다.
          .filter((s) => !narrowing || s.ids.length > 0);
        shown += ownIds.length + subs.reduce((n, s) => n + s.ids.length, 0);
        return { cat, subs, ownIds };
      })
      .filter((s) => !narrowing || s.ownIds.length > 0 || s.subs.length > 0);
    // 큰 섹터 접기 상한 — 보이는 섹션 수 n 으로 계산해 섹션마다 같은 값을 넘긴다.
    const cap = foldCap(Object.keys(d.companies).length, sections.length, narrowing);
    return { sections, shown, cap };
  }, [d, tops, active, mineOnly, q]);

  const toggle = (code: string) =>
    setActive((prev) => {
      const next = new Set(prev);
      if (next.has(code)) next.delete(code);
      else next.add(code);
      return next.size === tops.length ? new Set() : next;
    });

  const filtered = query !== "" || active.size > 0 || mineOnly;

  return (
    <>
      {d.sector.problems.length > 0 && (
        <div className="mb-3 rounded-xl border border-amber-200 bg-amber-50 px-3.5 py-2.5 text-[12px] font-semibold text-amber-900">
          분류 원본 검증 경고 {d.sector.problems.length}건 — {d.sector.problems.slice(0, 3).join(" · ")}
          {d.sector.problems.length > 3 && " …"}
        </div>
      )}

      <StageStrip categories={tops} idx={idx} active={active} />

      {/* 도구줄 — 상단 바(h-16) 바로 아래에 붙는다. */}
      <div data-vc-toolbar className="sticky top-16 z-10 -mx-6 mt-5 border-b border-hairline bg-canvas-soft/90 px-6 py-2.5 backdrop-blur supports-[backdrop-filter]:bg-canvas-soft/75">
        <div className="flex flex-wrap items-center gap-2">
          <label className="relative flex min-w-[200px] flex-1 items-center sm:max-w-[260px] sm:flex-none">
            <Search className="pointer-events-none absolute left-2.5 h-3.5 w-3.5 text-ink-muted" />
            <span className="sr-only">기업 검색</span>
            <input
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="기업명 · 영문명 · 티커"
              className="w-full rounded-lg border border-hairline bg-canvas py-1.5 pl-8 pr-7 text-[12.5px] font-semibold text-ink placeholder:font-medium placeholder:text-ink-faint focus:border-brand-blue focus:outline-none focus:ring-2 focus:ring-brand-blue/25 [&::-webkit-search-cancel-button]:hidden"
            />
            {query && (
              <button
                type="button"
                onClick={() => setQuery("")}
                aria-label="검색어 지우기"
                className="absolute right-1.5 rounded p-0.5 text-ink-muted hover:bg-canvas-soft hover:text-ink"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            )}
          </label>

          <div className="-mx-1 flex max-w-full items-center gap-1.5 overflow-x-auto px-1 py-0.5">
            <Chip active={active.size === 0} onClick={() => setActive(new Set())}>
              전체
            </Chip>
            {tops.map((c) => (
              <Chip key={c.code} active={active.has(c.code)} onClick={() => toggle(c.code)} color={c.color}>
                <span className="font-mono">{c.code}</span>
                {c.short ?? c.name}
              </Chip>
            ))}
          </div>

          <span aria-hidden className="hidden h-5 w-px bg-ink-muted/20 sm:block" />

          <Chip active={mineOnly} onClick={() => setMineOnly((v) => !v)}>
            보유/관심만
            <span className={cn("tabular-nums", mineOnly ? "text-white/70" : "text-ink-faint")}>{mineCount}</span>
          </Chip>

          <span className="ml-auto whitespace-nowrap text-[11.5px] font-semibold tabular-nums text-ink-muted">
            {filtered ? (
              <>
                카드 <b className="text-ink">{view.shown}</b> / {allIds.length}
                <button
                  type="button"
                  onClick={() => {
                    setQuery("");
                    setActive(new Set());
                    setMineOnly(false);
                  }}
                  className="ml-2 font-bold text-brand-point underline-offset-2 hover:underline"
                >
                  초기화
                </button>
              </>
            ) : (
              <>기업 {allIds.length}</>
            )}
          </span>
        </div>
      </div>

      <div className="mt-5 space-y-10">
        {view.sections.length === 0 ? (
          <EmptyState message="조건에 맞는 기업이 없습니다." />
        ) : (
          view.sections.map(({ cat, subs, ownIds }) => (
            <CategorySection
              key={cat.code}
              cat={cat}
              subs={subs}
              ownIds={ownIds}
              companies={d.companies}
              byCode={idx.byCode}
              innerFlows={idx.innerFlows}
              totalCompanies={idx.companyCount.get(cat.code) ?? 0}
              cap={view.cap}
            />
          ))
        )}
      </div>

      <div className="mt-12 grid gap-3">
        {d.theses.length > 0 && (
          <Collapsible title="투자 논지" count={d.theses.length}>
            <ul className="grid gap-2 [grid-template-columns:repeat(auto-fill,minmax(min(340px,100%),1fr))]">
              {d.theses.map((t, i) => (
                <li key={i} className="rounded-xl bg-canvas-soft px-3 py-2.5">
                  <div className="text-[11px] font-bold text-ink-muted">{t.src}</div>
                  <p className="mt-0.5 text-[12.5px] leading-relaxed text-ink-secondary">{t.text}</p>
                </li>
              ))}
            </ul>
          </Collapsible>
        )}
        {d.sources.length > 0 && (
          <Collapsible title="출처" count={d.sources.length}>
            <DataTable columns={["태그", "자료", "비고"]} align={["left", "left", "left"]}>
              {d.sources.map((s, i) => (
                <tr key={i} className="border-t border-hairline align-top">
                  <Cell left strong>
                    {s.tag}
                  </Cell>
                  <Cell left className="whitespace-normal">
                    {s.file}
                  </Cell>
                  <Cell left className="whitespace-normal text-ink-muted">
                    {s.note ?? "—"}
                  </Cell>
                </tr>
              ))}
            </DataTable>
          </Collapsible>
        )}
      </div>
    </>
  );
}

/** 섹터 하나의 상세 — 페이지가 상단 바 부제에도 쓰므로 훅으로 뺐다. */
export function useSectorDetail(code: string) {
  return useValueChainSector(code);
}

export function SectorView({
  code,
  detail,
}: {
  code: string;
  detail: ReturnType<typeof useSectorDetail>;
}) {
  const catalog = useValueChainCatalog();

  if (detail.error) {
    // 카탈로그에만 있고 섹터 파일이 아직 없는 자리 — 오류가 아니라 "미작성"이다.
    if (detail.error instanceof ApiError && detail.error.status === 404) {
      const card = catalog.data?.flatMap((g) => g.sectors).find((s) => s.code === code);
      return (
        <EmptyState
          message={
            card
              ? `${card.name} 밸류체인 미작성 (storage/valuechain/${code}.ttl 추가 시 생성)`
              : `섹터 "${code}" 가 없습니다.`
          }
        />
      );
    }
    return <ApiErrorBanner error={detail.error} />;
  }
  if (!detail.data || detail.data.sector.code !== code)
    return (
      <div className="grid animate-pulse gap-2.5 [grid-template-columns:repeat(auto-fit,minmax(180px,1fr))]">
        {Array.from({ length: 5 }).map((_, i) => (
          <div key={i} className="h-32 rounded-xl border border-hairline bg-canvas" />
        ))}
      </div>
    );
  // 섹터가 바뀌면 필터 상태를 새로 시작한다.
  return <SectorBody key={code} d={detail.data} />;
}
