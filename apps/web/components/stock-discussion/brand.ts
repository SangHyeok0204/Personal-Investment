// 종토방 카드/필터 공통 상수 — 발행사·소스·감성의 아이덴티티 색만 유지하고
// 나머지는 GE 토큰(§3). 라이트 캔버스에서 가독한 채도로 고정.
import type { SdSentiment, SdSource, SdSpy } from "@/lib/stock-discussion";

// 발행사 브랜드 색 — 흰 배경 위 텍스트/좌측 라인용(가독 우선 상수).
const ISSUER_COLOR: Record<string, string> = {
  ACE: "#7c3aed", // 보라
  TIGER: "#ea580c", // 주황
  KODEX: "#2563eb", // 파랑
  "1Q": "#16a34a", // 초록
  WON: "#dc2626", // 빨강
  SOL: "#0d9488", // 청록 (원본 미지정 — 데이터에 존재하여 보강)
};
const ISSUER_FALLBACK = "#64748b"; // slate — 미지정 발행사

// etf_name 프리픽스(공백 앞 토큰)로 발행사 추정 — meta 에 issuer 가 비었을 때 폴백.
export function issuerColor(
  issuer: string | null | undefined,
  etfName?: string | null,
): string {
  const key = (issuer || etfName?.split(" ")[0] || "").toUpperCase();
  return ISSUER_COLOR[key] ?? ISSUER_FALLBACK;
}

// 소스 pill — 네이버 초록 / 토스 파랑(원본 브랜드색). 옅은 tint 배경 + 브랜드 텍스트.
export const SOURCE_STYLE: Record<
  SdSource,
  { color: string; bg: string; label: string }
> = {
  네이버: { color: "#03c75a", bg: "rgba(3,199,90,0.12)", label: "네이버" },
  토스증권: { color: "#3182f6", bg: "rgba(49,130,246,0.12)", label: "토스증권" },
};

// 감성 pill — 긍정 success / 부정 failed / 중립 muted (GE 상태색).
export const SENTIMENT_STYLE: Record<
  SdSentiment,
  { color: string; bg: string }
> = {
  긍정: { color: "#27ae60", bg: "rgba(39,174,96,0.12)" },
  부정: { color: "#e74c3c", bg: "rgba(231,76,60,0.12)" },
  중립: { color: "#8a94a6", bg: "rgba(138,148,166,0.14)" },
};

// 스파이 인덱스: `${source}|${author}` → 라벨 배열. 카드 메타의 🚨 태그에 사용.
export function buildSpyIndex(spies: SdSpy[] | undefined): Map<string, string[]> {
  const idx = new Map<string, string[]>();
  if (!spies) return idx;
  for (const s of spies) {
    const key = `${s.source}|${s.author}`;
    const arr = idx.get(key);
    if (arr) {
      if (!arr.includes(s.label)) arr.push(s.label);
    } else {
      idx.set(key, [s.label]);
    }
  }
  return idx;
}

// 정규식 특수문자 이스케이프 — keyword 하이라이트 매처가 깨지지 않게(D10).
export function escapeRegExp(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}
