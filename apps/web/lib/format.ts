export function formatDateTime(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

export function shortId(id: string): string {
  return id.length > 8 ? id.slice(0, 8) : id;
}

export function prettyJson(value: unknown): string {
  if (value == null) return "—";
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

const KRW_FMT = new Intl.NumberFormat("ko-KR", { maximumFractionDigits: 0 });
const USD_FMT = new Intl.NumberFormat("ko-KR", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});
const QTY_FMT = new Intl.NumberFormat("ko-KR", { maximumFractionDigits: 6 });

// Negative amounts read as -₩379,148 (sign ahead of the symbol), not ₩-379,148.
export function formatKrw(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "—";
  const sign = value < 0 ? "-" : "";
  return `${sign}₩${KRW_FMT.format(Math.abs(value))}`;
}

export function formatUsd(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "—";
  const sign = value < 0 ? "-" : "";
  return `${sign}$${USD_FMT.format(Math.abs(value))}`;
}

export function formatMoney(
  value: number | null | undefined,
  currency: string | null | undefined,
): string {
  return currency === "USD" ? formatUsd(value) : formatKrw(value);
}

// 45,275,026 → "4,528만원"; 145,275,026 → "1.45억원". For headline totals only —
// tables keep the exact formatKrw value.
export function formatKrwCompact(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "—";
  const sign = value < 0 ? "-" : "";
  const abs = Math.abs(value);
  if (abs >= 100_000_000) {
    return `${sign}${(abs / 100_000_000).toFixed(2)}억원`;
  }
  if (abs >= 10_000) {
    return `${sign}${KRW_FMT.format(Math.round(abs / 10_000))}만원`;
  }
  return formatKrw(value);
}

// FX rate exactly as Kiwoom reports it (e.g. 1484.1 → "1,484.10"). Never derived.
export function formatRate(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "—";
  return USD_FMT.format(value);
}

export function formatQuantity(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "—";
  return QTY_FMT.format(value);
}

// Takes an already-percent value (e.g. 3.21 → "+3.21%").
export function formatPercent(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "—";
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(2)}%`;
}

export function formatRelativeTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "—";
  const diffSec = Math.round((Date.now() - then) / 1000);
  if (diffSec < 60) return "방금 전";
  const min = Math.floor(diffSec / 60);
  if (min < 60) return `${min}분 전`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr}시간 전`;
  const day = Math.floor(hr / 24);
  if (day < 7) return `${day}일 전`;
  return formatDateTime(iso);
}

// ── Decimal 문자열 포맷 ───────────────────────────────────────────────────────
// 포트폴리오 API 는 금액을 **문자열**로 내보낸다(서버 Decimal). Number 로 바꿔서
// 표시하면 원 단위에서 IEEE754 반올림이 드러나 합계와 종목별 수치가 어긋나 보인다.
// 아래 함수들은 소수점을 **문자열 수준에서** 잘라내고 정수부에만 자리 구분을 넣는다.

/** "2480000.00" → "₩2,480,000". null·빈값·비수치는 "—". */
export function formatKrwString(value: string | null | undefined): string {
  const parts = splitDecimal(value);
  if (!parts) return "—";
  const sign = roundsToZero(parts) ? "" : parts.sign;
  return `${sign}₩${groupDigits(roundedInt(parts))}`;
}

/** 부호를 살려 표시(손익용). "+"를 붙여 준다. */
export function formatKrwSigned(value: string | null | undefined): string {
  const parts = splitDecimal(value);
  if (!parts) return "—";
  const zero = roundsToZero(parts);
  const sign = zero ? "" : parts.sign === "-" ? "-" : "+";
  return `${sign}₩${groupDigits(roundedInt(parts))}`;
}

/** "0.1810" → "+18.10%". 수익률용. */
export function formatPercentString(
  value: string | null | undefined,
  digits = 2,
): string {
  if (value == null || value === "") return "—";
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  const pct = n * 100;
  const sign = pct > 0 ? "+" : "";
  return `${sign}${pct.toFixed(digits)}%`;
}

/** 수량처럼 소수가 의미 있는 값 — 뒤의 0 은 지운다. "10.000000" → "10". */
export function formatQuantityString(value: string | null | undefined): string {
  const parts = splitDecimal(value);
  if (!parts) return "—";
  const frac = parts.frac.replace(/0+$/, "");
  return `${parts.sign}${groupDigits(parts.int)}${frac ? `.${frac}` : ""}`;
}

/** 단가 — 통화에 따라 소수 자리수가 다르다(KRW 0, 그 외 2). */
export function formatPriceString(
  value: string | null | undefined,
  currency: string | null | undefined,
): string {
  const parts = splitDecimal(value);
  if (!parts) return "—";
  if (currency === "KRW" || currency == null) {
    return `${parts.sign}${groupDigits(roundedInt(parts))}`;
  }
  const frac = (parts.frac + "00").slice(0, 2);
  return `${parts.sign}${groupDigits(parts.int)}.${frac}`;
}

/** 큰 금액 한 줄 요약 — "₩2.48억". 헤드라인 전용이고 표에는 쓰지 않는다. */
export function formatKrwCompactString(
  value: string | null | undefined,
): string {
  const parts = splitDecimal(value);
  if (!parts) return "—";
  const int = roundedInt(parts);
  const sign = roundsToZero(parts) ? "" : parts.sign;
  const digits = int.length;
  if (digits > 8) {
    // 억 단위 — 억으로 줄이면 원 단위 반올림은 표시에 드러나지 않는다.
    const eok = Number(int) / 100_000_000;
    return `${sign}₩${eok.toFixed(2)}억`;
  }
  if (digits > 4) {
    const man = Math.round(Number(int) / 10_000);
    return `${sign}₩${groupDigits(String(man))}만`;
  }
  return `${sign}₩${groupDigits(int)}`;
}

function splitDecimal(
  value: string | null | undefined,
): { sign: string; int: string; frac: string; isZero: boolean } | null {
  if (value == null) return null;
  const raw = String(value).trim();
  if (raw === "" || !/^-?\d+(\.\d+)?$/.test(raw)) return null;
  const negative = raw.startsWith("-");
  const body = negative ? raw.slice(1) : raw;
  const [int, frac = ""] = body.split(".");
  const isZero = /^0*$/.test(int) && /^0*$/.test(frac);
  return { sign: negative ? "-" : "", int, frac, isZero };
}

/** 소수점을 버리는 표시에 쓸 **반올림한** 정수부.
 *
 * ⚠️예전에는 잘라 버렸다(₩174,261.89 → "₩174,261"). 한 줄만 보면 1원이라 눈에
 *   안 띄지만 **더해지는 칸끼리 합이 안 맞는다** — 보유 종목 화면에서
 *   매입 + 평가손익 + 제비용이 평가금액보다 1원 모자랐다. 금액을 더해 보는
 *   사람에게 그 1원은 "이 화면은 못 믿겠다"가 된다.
 *
 * ⚠️**소수를 살려 쓰는 곳에서 부르면 안 된다**(수량·외화 단가). 정수부만 올리면
 *   139.90 이 "140.90" 이 된다 — 실제로 한 번 그렇게 만들었다가 되돌렸다.
 *
 * ⚠️자릿수가 큰 값이 올 수 있어 Number 가 아니라 BigInt 로 올린다.
 */
function roundedInt(parts: { int: string; frac: string }): string {
  return parts.frac.charCodeAt(0) >= 53
    ? (BigInt(parts.int) + 1n).toString()
    : parts.int;
}

/** 반올림한 뒤에도 0 인가. "+₩0" 같은 표시를 막는다. */
function roundsToZero(parts: { int: string; frac: string }): boolean {
  return /^0*$/.test(roundedInt(parts));
}

function groupDigits(int: string): string {
  return int.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
}
