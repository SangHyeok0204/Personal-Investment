"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { ChevronRight } from "lucide-react";
import { ApiErrorBanner, EmptyState } from "@/components/states";
import { useValueChainCatalog, type VcCatalogCard, type VcCatalogGroup } from "@/lib/api-valuechain";
import { cn } from "@/lib/utils";
import { Fan } from "./card-fan";
import { catStyle } from "./model";

// 산업 밸류체인 허브 — L1 카드 부채 → 고른 L1 의 섹터 덱. 카드를 누르면 `/research/valuechain/{code}`.
// ★목록은 storage/valuechain/catalog.ttl 이 정한다. 섹터 파일이 생기면 그 카드가 저절로 열린다 —
//   화면 코드는 섹터 수·이름을 모른다.

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <span className="whitespace-nowrap">
      {label} <b className="font-extrabold tabular-nums text-ink">{value}</b>
    </span>
  );
}

/** 섹터 종류 배지 — 손으로 쓴 테마 vs 종목 분류체계에서 자동 생성된 분류(계획 Step 5). */
function KindBadge({ kind, onColor = false }: { kind: VcCatalogCard["kind"]; onColor?: boolean }) {
  const auto = kind === "taxonomy";
  return (
    <span
      title={auto ? "종목 분류체계에서 자동 생성 — 흐름 없음, L2 대분류만" : "직접 작성한 테마 밸류체인"}
      className={cn(
        "shrink-0 whitespace-nowrap rounded-full px-2 py-0.5 text-[10.5px] font-bold",
        onColor
          ? "bg-white/15 text-white ring-1 ring-inset ring-white/35"
          : "bg-[color:color-mix(in_srgb,var(--c)_12%,white)] text-[color:var(--c)]",
      )}
    >
      {auto ? "분류 (자동 생성)" : "테마"}
    </span>
  );
}

// ★2026-09-28: 섹터 카드 = 카드 덱 상자(참고 이미지의 덱 박스). L1 기준색(묶음 색)으로 칠하고, 뒤에 카드 두 장이
//   비껴 쌓인 층을 둔다. hover 하면 상자가 살짝 들리고 뒤 카드가 부채처럼 벌어진다.
//   분류 섹터 = 색을 채운 상자(흰 글씨·안쪽 테두리), 테마 섹터(bio) = 흰 상자 + 색 띠.
function BuiltCard({ s }: { s: VcCatalogCard }) {
  const deck = s.kind === "taxonomy";
  return (
    <Link
      href={`/research/valuechain/${encodeURIComponent(s.code)}`}
      style={s.color ? catStyle(s.color) : undefined}
      className="group relative block focus:outline-none"
    >
      {/* 뒤에 쌓인 카드 두 장 — hover 시 벌어진다. */}
      <span
        aria-hidden
        className="absolute inset-0 rounded-2xl bg-[color:color-mix(in_srgb,var(--c)_22%,white)] transition-transform duration-200 ease-out group-hover:-translate-y-1 group-hover:rotate-[4deg] motion-reduce:transition-none"
      />
      <span
        aria-hidden
        className="absolute inset-0 rounded-2xl bg-[color:color-mix(in_srgb,var(--c)_40%,white)] transition-transform duration-200 ease-out group-hover:-translate-y-0.5 group-hover:-rotate-[3deg] motion-reduce:transition-none"
      />
      <span
        className={cn(
          "relative flex h-full flex-col rounded-2xl px-4 pb-3.5 pt-3 shadow-card transition-[transform,box-shadow] duration-200 ease-out group-hover:-translate-y-2 group-hover:shadow-panel group-focus-visible:-translate-y-2 group-focus-visible:ring-2 group-focus-visible:ring-brand-blue motion-reduce:transition-none",
          deck
            ? "bg-[color:var(--c)] text-white"
            : "border border-hairline border-l-[6px] border-l-[color:var(--c)] bg-canvas",
        )}
      >
        {deck && (
          <span aria-hidden className="pointer-events-none absolute inset-[5px] rounded-[12px] ring-1 ring-inset ring-white/35" />
        )}
        <span className="flex flex-wrap items-start justify-between gap-2">
          <span className="min-w-0">
            <span className={cn("block text-[15px] font-extrabold", deck ? "text-white" : "text-ge-navy")}>
              {s.name}
            </span>
            {s.en && (
              <span className={cn("block text-[11px] font-semibold", deck ? "text-white/70" : "text-ink-faint")}>
                {s.en}
              </span>
            )}
          </span>
          <span className="flex shrink-0 items-center gap-1.5">
            <KindBadge kind={s.kind} onColor={deck} />
            <ChevronRight
              className={cn(
                "h-4 w-4 shrink-0 transition-transform group-hover:translate-x-0.5",
                deck ? "text-white" : "text-[color:var(--c)]",
              )}
            />
          </span>
        </span>
        {s.desc && (
          <span
            className={cn(
              "mt-2 block text-[12px] font-medium leading-relaxed",
              deck ? "text-white/85" : "text-ink-secondary",
            )}
          >
            {s.desc}
          </span>
        )}
        <span
          className={cn(
            "mt-auto flex flex-wrap gap-x-3 gap-y-1 pt-3 text-[11.5px] font-semibold",
            deck ? "text-white/75 [&_b]:text-white" : "text-ink-muted",
          )}
        >
          <Stat label="분류" value={s.categories} />
          <Stat label="기업" value={s.companies} />
          {s.mine > 0 && <Stat label="보유·관심" value={s.mine} />}
          {s.problems > 0 && <span className={deck ? "text-amber-200" : "text-amber-700"}>검증 경고 {s.problems}</span>}
        </span>
      </span>
    </Link>
  );
}

function PlannedCard({ s }: { s: VcCatalogCard }) {
  return (
    <div
      title={`storage/valuechain/${s.code}.ttl 을 추가하면 열립니다`}
      className="flex h-full flex-col rounded-2xl border border-dashed border-ink-muted/30 bg-canvas-soft px-4 pb-3.5 pt-3"
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="text-[15px] font-extrabold text-ink-muted">{s.name}</div>
          {s.en && <div className="text-[11px] font-semibold text-ink-faint">{s.en}</div>}
        </div>
        <span className="shrink-0 rounded-full bg-canvas px-2 py-0.5 text-[10.5px] font-bold text-ink-faint ring-1 ring-hairline">
          미작성
        </span>
      </div>
      {s.desc && (
        <p className="mt-2 text-[12px] font-medium leading-relaxed text-ink-faint">{s.desc}</p>
      )}
    </div>
  );
}

/** 허브 L1 카드(트럼프 한 장) — 묶음 기준색 바탕, 모서리 인덱스(이름 첫 글자)는 좌상·우하. */
function GroupCard({
  g,
  active,
  onPick,
}: {
  g: VcCatalogGroup;
  active: boolean;
  onPick: () => void;
}) {
  const tx = g.sectors.find((c) => c.kind === "taxonomy" && c.built);
  const themes = g.sectors.filter((c) => c.kind !== "taxonomy");
  const themesBuilt = themes.filter((c) => c.built).length;
  const mine = tx?.mine ?? 0;
  const mark = g.name.slice(0, 1);
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onPick}
      style={catStyle(g.color ?? "#7F7F7F")}
      className={cn(
        "relative flex h-full w-full overflow-hidden rounded-2xl bg-[color:var(--c)] text-left text-white shadow-card transition-shadow duration-200 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-blue focus-visible:ring-offset-2 group-hover/slot:shadow-panel",
        active && "shadow-panel ring-2 ring-white ring-offset-2 ring-offset-[color:var(--c)]",
      )}
    >
      <span aria-hidden className="pointer-events-none absolute inset-[6px] rounded-[12px] ring-1 ring-inset ring-white/35" />
      {/* 왼쪽 인덱스 — 겹쳐 이 띠만 보여도 어떤 L1 인지 읽힌다. */}
      <span className="flex w-[46px] shrink-0 flex-col items-center gap-2 pb-3 pt-3.5">
        <span className="text-[22px] font-black leading-none">{mark}</span>
        <span className="min-h-0 flex-1 overflow-hidden whitespace-nowrap text-[13px] font-extrabold tracking-wide [writing-mode:vertical-rl]">
          {g.name}
        </span>
      </span>
      <span className="flex min-w-0 flex-1 flex-col py-4 pr-4">
        <span className="text-[19px] font-black leading-tight tracking-tight">{g.name}</span>
        {tx?.en && <span className="mt-0.5 text-[11px] font-semibold text-white/70">{tx.en}</span>}
        {tx?.desc && (
          <span className="mt-3 line-clamp-4 text-[12px] font-medium leading-relaxed text-white/85">
            {tx.desc.replace(/^미국 상장사? 분류 지도 — /, "")}
          </span>
        )}
        <span className="mt-auto space-y-1 pb-5 text-[12px] font-semibold text-white/80">
          {tx && (
            <span className="block">
              기업 <b className="font-extrabold tabular-nums text-white">{tx.companies}</b> · 분류{" "}
              <b className="font-extrabold tabular-nums text-white">{tx.categories}</b>
            </span>
          )}
          <span className="block">
            테마 <b className="font-extrabold tabular-nums text-white">{themesBuilt}</b>/{themes.length}
            {mine > 0 && (
              <>
                {" "}
                · 보유·관심 <b className="font-extrabold tabular-nums text-white">{mine}</b>
              </>
            )}
          </span>
        </span>
      </span>
      {/* 오른쪽 아래 인덱스 — 트럼프처럼 한 번 더. ⚠️한글은 180° 뒤집으면 다른 글자로 읽혀("기"→"lc") 똑바로 둔다. */}
      <span aria-hidden className="absolute bottom-3 right-3.5 text-[18px] font-black leading-none text-white/55">
        {mark}
      </span>
    </button>
  );
}

// ★2026-09-28: 허브 첫 화면 = L1 카드 부채(손에 쥔 카드). 카드를 고르면 그 L1 의 덱(분류·테마 섹터)이 아래에 펼쳐진다.
//   선택은 URL `?g=<묶음 id>` 에 남겨 새로고침·공유에도 유지한다(history.replaceState — 라우팅 없이).
export function SectorHub() {
  const catalog = useValueChainCatalog();
  const [picked, setPicked] = useState<string | null>(null);
  const panelRef = useRef<HTMLElement>(null);

  useEffect(() => {
    const g = new URLSearchParams(window.location.search).get("g");
    if (g) setPicked(g);
  }, []);

  const pick = (id: string) => {
    const next = picked === id ? null : id;
    setPicked(next);
    const url = new URL(window.location.href);
    if (next) url.searchParams.set("g", next);
    else url.searchParams.delete("g");
    window.history.replaceState(null, "", url);
    if (next) requestAnimationFrame(() => panelRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" }));
  };

  if (catalog.error) return <ApiErrorBanner error={catalog.error} />;
  if (!catalog.data)
    return (
      <div className="grid animate-pulse gap-3 [grid-template-columns:repeat(auto-fill,minmax(min(260px,100%),1fr))]">
        {Array.from({ length: 6 }).map((_, i) => (
          <div key={i} className="h-32 rounded-2xl border border-hairline bg-canvas" />
        ))}
      </div>
    );
  if (catalog.data.length === 0)
    return <EmptyState message="등록된 섹터 없음 (storage/valuechain 에 섹터 TTL 추가)" />;

  const groups = catalog.data;
  const sel = groups.find((g) => g.id === picked) ?? null;

  return (
    <div>
      <Fan
        keys={groups.map((g) => g.id)}
        cardW={210}
        cardH={292}
        minStep={52 /* 인덱스 띠(46px) + 여유 */}
        maxStep={132}
        active={sel?.id}
        renderCard={(id) => {
          const g = groups.find((x) => x.id === id)!;
          return <GroupCard g={g} active={g.id === sel?.id} onPick={() => pick(g.id)} />;
        }}
      />

      {sel ? (
        <section
          ref={panelRef}
          aria-labelledby="vc-group-picked"
          style={sel.color ? catStyle(sel.color) : undefined}
          className="mt-6 scroll-mt-24"
        >
          <div className="mb-4 flex items-baseline gap-2 border-b-2 border-[color:var(--c,#F2F2F2)] pb-1.5">
            <h2 id="vc-group-picked" className="text-[18px] font-extrabold text-[color:var(--c,#4C2C19)]">
              {sel.name}
            </h2>
            <span className="text-[11.5px] font-semibold tabular-nums text-ink-faint">
              섹터 {sel.sectors.filter((s) => s.built).length}/{sel.sectors.length}
            </span>
            <button
              type="button"
              onClick={() => pick(sel.id)}
              className="ml-auto text-[12px] font-bold text-ink-muted hover:text-ink"
            >
              닫기
            </button>
          </div>
          <div className="grid gap-5 [grid-template-columns:repeat(auto-fill,minmax(min(280px,100%),1fr))]">
            {sel.sectors.map((s) =>
              s.built ? <BuiltCard key={s.code} s={s} /> : <PlannedCard key={s.code} s={s} />,
            )}
          </div>
        </section>
      ) : null}
    </div>
  );
}
