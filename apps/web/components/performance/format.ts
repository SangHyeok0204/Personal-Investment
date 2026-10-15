// 성과 분석 섹션들이 같이 쓰는 숫자 표기.
//
// ★2026-10-15 성과 분석 네 화면(수익률 추이·벤치마크 비교·성과 분석·기간 리포트)을
//   /portfolio/performance 한 화면으로 합치면서, 화면마다 따로 복사돼 있던 pct·tone 류를
//   여기로 모았다. 표기 규칙은 옛 화면 그대로다 — 모르면 "—", 부호 있는 비율에는 +.

/** 비율 문자열(0.0711) → "+7.11%". null·빈 문자열·NaN 은 "—". */
export function pct(value: string | null | undefined, digits = 2): string {
  if (value == null || value === "") return "—";
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  return `${n > 0 ? "+" : ""}${(n * 100).toFixed(digits)}%`;
}

/** 지수 이름 → 짧은 표기. 이름마다 따로 정한다 — 길이로 자르면 서로 겹친다. */
const SHORT_NAME: Record<string, string> = { "S&P 500": "S&P 500" };
export const shortName = (name: string) => SHORT_NAME[name] ?? name;

/** 모르면 null — StatTile 이 '—' 로 그린다. */
export function pctOrNull(value: string | null | undefined): string | null {
  return value == null ? null : pct(value);
}

/** 부호 없는 비율(변동성 등). 음수가 나올 수 없는 값에 + 를 붙이지 않는다. */
export function pctPlain(value: string | null | undefined, digits = 2): string {
  if (value == null || value === "") return "—";
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  return `${(n * 100).toFixed(digits)}%`;
}

/** "+5.18%p" — 초과수익은 퍼센트가 아니라 **퍼센트포인트**다. */
export function pp(value: string | null | undefined): string {
  if (value == null) return "—";
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  return `${n > 0 ? "+" : ""}${(n * 100).toFixed(2)}%p`;
}

export function num(value: string | null | undefined, digits = 2): string {
  if (value == null || value === "") return "—";
  const n = Number(value);
  return Number.isFinite(n) ? n.toFixed(digits) : "—";
}

export function toneOfRatio(value: string | null | undefined): "up" | "down" | undefined {
  if (value == null || value === "") return undefined;
  const n = Number(value);
  if (!Number.isFinite(n) || n === 0) return undefined;
  return n > 0 ? "up" : "down";
}
