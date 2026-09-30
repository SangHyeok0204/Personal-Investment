// 밸류체인 화면 공용 계산·이동 도우미 — 섹터 불문(분류 코드 체계를 가정하지 않는다).
import type { CSSProperties } from "react";
import type { VcCategory, VcCompany, VcSectorDetail } from "@/lib/api-valuechain";

export interface VcIndex {
  /** 코드 → 분류 노드(모든 레벨). */
  byCode: Map<string, VcCategory>;
  /** 코드 → 그 코드가 속한 최상위 분류 코드. */
  topOf: Map<string, string>;
  /** 최상위 분류 코드 → 그 하위 어디에든 소속된 기업 수(중복 제거). */
  companyCount: Map<string, number>;
  /** 최상위 분류끼리의 흐름만 — 단계 스트립 화살표. */
  topFlows: [string, string][];
  /** 그 밖의 흐름(중분류 ↔ 중분류 등) — 해당 섹션 안에서만 보인다. */
  innerFlows: [string, string][];
}

export function buildIndex(d: VcSectorDetail): VcIndex {
  const byCode = new Map<string, VcCategory>();
  const topOf = new Map<string, string>();
  const walk = (c: VcCategory, top: string) => {
    byCode.set(c.code, c);
    topOf.set(c.code, top);
    c.children.forEach((x) => walk(x, top));
  };
  d.categories.forEach((c) => walk(c, c.code));

  const members = new Map<string, Set<string>>();
  for (const [id, co] of Object.entries(d.companies)) {
    for (const code of co.categories) {
      const top = topOf.get(code);
      if (!top) continue;
      if (!members.has(top)) members.set(top, new Set());
      members.get(top)!.add(id);
    }
  }
  const companyCount = new Map<string, number>();
  d.categories.forEach((c) => companyCount.set(c.code, members.get(c.code)?.size ?? 0));

  const isTop = new Set(d.categories.map((c) => c.code));
  const topFlows: [string, string][] = [];
  const innerFlows: [string, string][] = [];
  for (const f of d.flows) (isTop.has(f[0]) && isTop.has(f[1]) ? topFlows : innerFlows).push(f);

  return { byCode, topOf, companyCount, topFlows, innerFlows };
}

/**
 * 최상위 분류를 흐름 기준 단계(열)로 나눈다 — 가장 긴 선행 경로 길이가 곧 열 번호.
 * 흐름이 없거나 순환이면 모두 한 단계(0)로 둔다.
 */
export function stageLevels(cats: VcCategory[], flows: [string, string][]): VcCategory[][] {
  const level = new Map<string, number>(cats.map((c) => [c.code, 0]));
  // 벨만-포드식 완화 — 노드 수만큼만 돌려 순환에서도 멈춘다.
  for (let i = 0; i < cats.length; i++) {
    let changed = false;
    for (const [a, b] of flows) {
      const next = (level.get(a) ?? 0) + 1;
      if (next > (level.get(b) ?? 0) && next < cats.length) {
        level.set(b, next);
        changed = true;
      }
    }
    if (!changed) break;
  }
  const cols: VcCategory[][] = [];
  [...cats]
    .sort((x, y) => x.order - y.order)
    .forEach((c) => {
      const l = level.get(c.code) ?? 0;
      (cols[l] ??= []).push(c);
    });
  return cols.filter(Boolean);
}

export const catAnchor = (code: string) => `vc-cat-${code}`;
export const subAnchor = (code: string) => `vc-sub-${code}`;

/** 분류 색을 CSS 변수 `--c` 로 넘긴다(색이 없으면 잉크 회색). */
export function catStyle(color: string | null | undefined): CSSProperties {
  return { "--c": color ?? "#7F7F7F" } as CSSProperties;
}

/**
 * 앵커로 부드럽게 스크롤하고 잠깐 강조한다.
 * ★상태로 들고 있지 않고 DOM `data-flash` 만 잠깐 켠다 — 카드 140장이 다시 그려지지 않게.
 */
export function jumpTo(id: string, flash = true) {
  if (typeof document === "undefined") return;
  const el = document.getElementById(id);
  if (!el) return;
  const reduce = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
  // ⚠️scrollIntoView 를 쓰지 않는다 — 앱 셸의 overflow 컨테이너까지 밀어 올려 사이드바·상단 바가
  //   화면 밖으로 밀려났다(실측). 창 스크롤만 움직이고, 고정 상단 바+도구줄 높이는
  //   대상의 scroll-margin-top(scroll-mt-*)으로 뺀다.
  // ⚠️도구줄은 칩 수·화면 폭에 따라 1~3줄로 접힌다(분류 섹터 20칩 → 130px, 실측) — 고정값만 믿으면
  //   헤더가 도구줄 밑에 숨는다. 붙었을 때의 도구줄 바닥(top + 높이) + 8px 과 큰 쪽을 쓴다.
  const bar = document.querySelector<HTMLElement>("[data-vc-toolbar]");
  const barBottom = bar ? (parseFloat(getComputedStyle(bar).top) || 0) + bar.offsetHeight + 8 : 0;
  const margin = Math.max(parseFloat(getComputedStyle(el).scrollMarginTop) || 0, barBottom);
  const top = el.getBoundingClientRect().top + window.scrollY - margin;
  window.scrollTo({ top: Math.max(0, top), behavior: reduce ? "auto" : "smooth" });
  if (!flash) return;
  el.dataset.flash = "true";
  window.setTimeout(() => {
    delete el.dataset.flash;
  }, 1600);
}

/** 원본 설명에 섞인 마크다운 백틱(`지역은행`)을 화면용으로 걷어낸다. */
export const plainText = (s: string) => s.replace(/`/g, "");

/**
 * 큰 섹터 접기 상한(계획 §1 e) — 섹터 기업 > 200 일 때만 대분류당 `clamp(floor(240/n), 8, 24)` 장.
 * n = 보이는 대분류 섹션 수. 좁혀 보는 중(검색·보유/관심·칩 1개)에는 접지 않는다(null).
 */
export function foldCap(sectorCompanies: number, sections: number, narrowing: boolean): number | null {
  if (narrowing || sectorCompanies <= 200 || sections === 0) return null;
  return Math.min(24, Math.max(8, Math.floor(240 / sections)));
}

export function matchesQuery(co: VcCompany, q: string): boolean {
  if (!q) return true;
  // ★role 포함 — 분류 섹터는 L3(후보·확정) 문자열이 role 에 들어 있어 "소매은행" 같은 세부 업종으로도 찾는다.
  const hay = [co.name, co.en, co.ticker, co.role].filter(Boolean).join(" ").toLowerCase();
  return hay.includes(q);
}
