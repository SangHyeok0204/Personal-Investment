// 공용 표기 헬퍼 — 숫자 포맷과 등락 색 관례를 화면마다 다시 정하지 않기 위한 자리.
// [종목 모니터] 화면의 `stock-monitor/format` 이 원본이고, 그 화면이 없어지면서
// 남은 사용처([AI Key Data] · [종목 모니터링 · 미국])를 따라 여기로 올라왔다.

export const EMDASH = "−";

export function fmtInt(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return EMDASH;
  return Math.round(v).toLocaleString("en-US");
}

// 억/조 단위 — 토스 화면 표기(225억원 · 1,749.4조원)를 따른다.
export function fmtWon(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return EMDASH;
  if (v >= 1e12) return `${(v / 1e12).toLocaleString("en-US", { maximumFractionDigits: 1 })}조원`;
  if (v >= 1e8) return `${Math.round(v / 1e8).toLocaleString("en-US")}억원`;
  return `${Math.round(v).toLocaleString("en-US")}원`;
}

// 미장 현재가 — 달러 소수 2자리 ($488.69). 원화 fmtInt+"원" 의 미장 짝.
export function fmtUsd(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return EMDASH;
  return `$${v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

// 미장 거래대금 — $1.2B / $12.3M / $45K 축약. fmtWon(억/조)의 미장 짝.
export function fmtUsdValue(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return EMDASH;
  if (v >= 1e9) return `$${(v / 1e9).toLocaleString("en-US", { maximumFractionDigits: 1 })}B`;
  if (v >= 1e6) return `$${(v / 1e6).toLocaleString("en-US", { maximumFractionDigits: 1 })}M`;
  if (v >= 1e3) return `$${Math.round(v / 1e3).toLocaleString("en-US")}K`;
  return `$${Math.round(v).toLocaleString("en-US")}`;
}

export function fmtPct(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return EMDASH;
  return `${v > 0 ? "+" : ""}${v.toFixed(2)}%`;
}

export function fmtSigma(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return EMDASH;
  return `${v > 0 ? "+" : ""}${v.toFixed(2)}σ`;
}

// 등락 색 — 한국 관례(상승 빨강 / 하락 파랑). 토스 화면과 같다.
export function moveColor(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v) || v === 0) return "text-ink-muted";
  return v > 0 ? "text-rose-600" : "text-blue-600";
}

// σ 강조 — |σ|≥2 는 그 종목 기준 드문 움직임이다. 고정 임계값(±5%)으로는 못 가르는 자리.
export function sigmaTone(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "text-ink-muted";
  const a = Math.abs(v);
  if (a >= 3) return "font-extrabold text-rose-700";
  if (a >= 2) return "font-bold text-amber-600";
  return "text-ink-muted";
}
