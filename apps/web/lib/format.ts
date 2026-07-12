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

export function formatKrw(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "—";
  return `₩${KRW_FMT.format(value)}`;
}

export function formatUsd(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "—";
  return `$${USD_FMT.format(value)}`;
}

export function formatMoney(
  value: number | null | undefined,
  currency: string | null | undefined,
): string {
  return currency === "USD" ? formatUsd(value) : formatKrw(value);
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
