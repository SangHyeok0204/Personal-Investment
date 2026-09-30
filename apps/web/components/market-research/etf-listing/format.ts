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
  // ★표기 자릿수까지 내려오면 0 인 값은 부호를 떼어 "0" 으로 쓴다. `+0.0억` 은
  //   "0 인데 들어왔다"는 모순된 인상을 주고, 축 눈금에서는 그냥 읽을 게 없다.
  if (a < 0.05) return "0";
  return `${s}${a.toFixed(1)}억`;
}

/** 소수 수익률(0.0153) → "+1.53%".
 *  ★반올림 결과가 0 이면 부호를 떼어 낸다 — `-0.0%` 는 읽는 사람을 멈칫하게 하는데
 *    그 멈칫에 값어치가 없다(원래 값이 -0.0001 인지 -0.04 인지 어차피 안 보인다). */
export function fmtPct(v: number | null | undefined, digits = 2): string {
  if (v == null || !Number.isFinite(v)) return EMDASH;
  const p = v * 100;
  const txt = p.toFixed(digits);
  if (Number(txt) === 0) return `${(0).toFixed(digits)}%`;
  return `${p > 0 ? "+" : ""}${txt}%`;
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
