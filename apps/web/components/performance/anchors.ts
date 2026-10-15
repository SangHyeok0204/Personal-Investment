// 성과 분석 한 화면의 섹션 앵커.
//
// ★2026-10-15 옛 주소(/performance/*)는 next.config.mjs redirect 로 여기 #앵커 로 온다.
//   id 를 바꾸면 그 redirect 도 같이 바꿔야 한다.

export const PERFORMANCE_SECTIONS = [
  { id: "returns", label: "수익률 추이" },
  { id: "monthly", label: "월별" },
  { id: "periods", label: "기간별" },
  { id: "drawdown", label: "낙폭" },
  { id: "contribution", label: "종목 기여도" },
  { id: "report", label: "기간 리포트" },
  { id: "bridge", label: "숫자가 이어지는 법" },
] as const;

export type PerformanceSectionId = (typeof PERFORMANCE_SECTIONS)[number]["id"];

/**
 * 섹션으로 창을 스크롤한다.
 * ⚠️scrollIntoView 를 쓰지 않는다 — 앱 셸의 overflow 컨테이너까지 밀어 올려 사이드바·상단 바가
 *   화면 밖으로 밀려났다(산업 밸류체인 jumpTo 와 같은 이유). 창만 움직이고, 고정 상단 바 +
 *   섹션 목차 높이는 대상의 scroll-margin-top(scroll-mt-*)으로 뺀다.
 */
export function jumpTo(id: PerformanceSectionId | string, smooth = true) {
  if (typeof document === "undefined") return;
  const el = document.getElementById(id);
  if (!el) return;
  const reduce = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
  const margin = parseFloat(getComputedStyle(el).scrollMarginTop) || 0;
  const top = el.getBoundingClientRect().top + window.scrollY - margin;
  window.scrollTo({ top: Math.max(0, top), behavior: smooth && !reduce ? "smooth" : "auto" });
}
