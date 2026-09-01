// [국내상장 ETF] 표기 헬퍼. 페이지와 카드 넷이 같이 쓴다.
//
// ★원천(워크북)의 금액 단위는 **억원**이다 — 종목 모니터의 fmtWon(원 단위)과 짝이
//   맞지 않으니 섞어 쓰지 말 것. 여기 함수들은 전부 "값이 이미 억"이라고 가정한다.

export const EMDASH = "−";

/** 억 단위 숫자 → "1.2조" / "3,450억". 부호는 항상 붙인다(순매수/순매도 구분). */
export function fmtEok(v: number | null | undefined, signed = true): string {
  if (v == null || !Number.isFinite(v)) return EMDASH;
  const s = signed && v > 0 ? "+" : v < 0 ? "-" : "";
  const a = Math.abs(v);
  if (a >= 10000) return `${s}${(a / 10000).toFixed(1)}조`;
  if (a >= 1) return `${s}${Math.round(a).toLocaleString("en-US")}억`;
  return `${s}${a.toFixed(1)}억`;
}

/** 소수 수익률(0.0153) → "+1.53%". */
export function fmtPct(v: number | null | undefined, digits = 2): string {
  if (v == null || !Number.isFinite(v)) return EMDASH;
  return `${v > 0 ? "+" : ""}${(v * 100).toFixed(digits)}%`;
}

/** 이미 % 단위인 값(시총 대비 강도) → "+7.73%". */
export function fmtRatio(v: number | null | undefined, digits = 2): string {
  if (v == null || !Number.isFinite(v)) return EMDASH;
  return `${v > 0 ? "+" : ""}${v.toFixed(digits)}%`;
}

/** 한국 관례 — 순매수·상승 빨강 / 순매도·하락 파랑. 종목 모니터와 같은 규약. */
export function tone(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v) || v === 0) return "text-ink-muted";
  return v > 0 ? "text-rose-600" : "text-blue-600";
}

/** 막대·점 채우기용 원색(SVG fill). tone() 의 CSS 색과 같은 계열. */
export function toneHex(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v) || v === 0) return "#c3cad4";
  return v > 0 ? "#e11d48" : "#2563eb";
}

/** 날짜 'YYYY-MM-DD' → 'MM/DD'. 축 라벨이 길면 겹친다. */
export function mmdd(d: string): string {
  return d.length >= 10 ? `${d.slice(5, 7)}/${d.slice(8, 10)}` : d;
}
