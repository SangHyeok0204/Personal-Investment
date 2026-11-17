// 투자 전략 › 타점 승률(/strategy/entry-odds) 전용 클라이언트 — `GET /api/v1/strategy/entry-odds…`.
//
// ⚠️`lib/api.ts` 의 `request()` 는 모듈 private 이라 `lib/api-video.ts` 와 같은 방식으로 에러 봉투를 처리한다.
import { API_BASE_URL, ApiError } from "@/lib/api";

export interface EntryOddsCell {
  /** 보유 개월 */
  h: number;
  /** 겹치는 창 수 */
  n: number;
  win_rate: number | null;
  median: number | null;
  worst: number | null;
  /** 보유 중 최악 낙폭(진입가 대비) */
  worst_dip: number | null;
  /** h 개월씩 건너뛴 독립 회차 */
  episodes: number;
  episode_wins: number;
  /** 독립 회차 기준 Wilson 95% 하한 */
  lower: number | null;
}

export interface EntryOddsRow {
  key: string;
  label: string;
  /** 지금 이 조건에 해당하나 */
  active: boolean;
  /** 이 기간부터 그 이상 모든 기간에서 승률 ≥ 목표(독립 회차가 충분한 기간만 판정) */
  min_months_rate: number | null;
  min_months_lower: number | null;
  cells: EntryOddsCell[];
}

export interface EntryOdds {
  kind: "series" | "ticker";
  key: string;
  label: string;
  basis: string;
  data_until?: string;
  /** 지수 — 이 달까지는 빈 달이 있어 버렸다(연속한 월만 센다) */
  dropped_before?: string | null;
  first_month: string;
  last_month: string;
  months: number;
  horizons: number[];
  target: number;
  min_episodes: number;
  now: {
    month: string | null;
    drawdown: number | null;
    below_ma10: boolean | null;
    active: string[];
    /** 마지막 달이 아직 안 끝남 — 과거 표에서는 뺐다 */
    partial: boolean;
  };
  rows: EntryOddsRow[];
}

export interface EntryOddsUniverse {
  series: { key: string; label: string; grp: string }[];
  ohlcv_available: boolean;
}

interface ErrorEnvelope {
  error: { code: string; message: string; details?: Record<string, unknown> };
}

async function call<T>(path: string): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE_URL}${path}`);
  } catch {
    throw new ApiError(0, "NETWORK_ERROR", "API unreachable");
  }
  const text = await res.text();
  const data = text ? (JSON.parse(text) as unknown) : null;
  if (!res.ok) {
    const env = data as ErrorEnvelope | null;
    throw new ApiError(
      res.status,
      env?.error?.code ?? "INTERNAL_ERROR",
      env?.error?.message ?? `Request failed (${res.status})`,
      env?.error?.details,
    );
  }
  return data as T;
}

export function getEntryOddsUniverse(): Promise<EntryOddsUniverse> {
  return call(`/api/v1/strategy/entry-odds/universe`);
}

export function getEntryOdds(target: { series: string } | { ticker: string }): Promise<EntryOdds> {
  const q = "series" in target ? `series=${encodeURIComponent(target.series)}` : `ticker=${encodeURIComponent(target.ticker)}`;
  return call(`/api/v1/strategy/entry-odds?${q}`);
}

// ── 연구실: 바스켓 괴리(전략1) · 웅덩이 매수(전략2) ──────────────────────────────

export interface LabBasket {
  key: string;
  name: string;
  tickers: string[];
  group: string;
}

export interface LabMeta {
  /** 야후에서 못 받은 종목(바스켓 평균에서 빠짐) */
  missing?: string[];
  start: string;
  as_of: string;
  baskets: LabBasket[];
  indicators: Record<string, string>;
  ns: number[];
  holds: number[];
  hit: number;
  pct: { window: number; lo: number; hi: number };
}

export interface LabStats {
  signals: number;
  hits: number;
  hit_ratio: number | null;
  avg_ret: number | null;
  baseline: number | null;
  edge: number | null;
}

export interface LabSignal {
  date: string;
  /** hi = A 가 비쌈 → B 매수, lo = A 가 쌈 → A 매수 */
  side: "hi" | "lo";
  bought: string;
  entry: string | null;
  ret: number | null;
  hit: boolean | null;
}

export interface LabSpread {
  a: string;
  b: string;
  ind: string;
  n: number;
  hold: number;
  dates: string[];
  spread: (number | null)[];
  lo: (number | null)[];
  hi: (number | null)[];
  level_a: (number | null)[];
  level_b: (number | null)[];
  signals: LabSignal[];
  stats: LabStats;
  now: { spread: number | null; lo: number | null; hi: number | null };
}

export interface LabRow extends LabStats {
  a: string;
  b: string;
  ind: string;
  n: number;
  /** 두 바스켓이 같은 묶음(섹터·밸류체인)인가 */
  same: boolean;
}

export interface LabPool {
  hit: number | null;
  signals: number;
  baseline: number | null;
}

export interface LabLeaderboard {
  hold: number;
  configs: number;
  eligible: number;
  min_signals: number;
  pooled_hit: number | null;
  pooled_signals: number;
  baseline_avg: number | null;
  scope: "all" | "same" | "cross";
  pooled: { all: LabPool; same: LabPool; cross: LabPool };
  /** 검증 기간(분석 기간 직전 1년)에 같은 규칙 */
  check?: { start: string; end: string; all: LabPool; same: LabPool; cross: LabPool };
  /** 같은 신호에서 뒤처진 쪽(reversion) vs 앞선 쪽(momentum)을 샀을 때, 두 기간 */
  direction?: { period: string; mode: "reversion" | "momentum"; signals: number; hit: number | null; baseline: number | null }[];
  top: LabRow[];
  live: { a: string; b: string; ind: string; n: number; date: string; bought: string; side: string; hit_ratio: number | null; signals: number }[];
}

export interface DipSumm {
  n: number;
  avg: number | null;
  med: number | null;
  win: number | null;
  hit: number | null;
}

export type DipRow = DipSumm & { cond: string; label: string; hold: number; base: DipSumm; stop?: DipSumm };

export interface DipStudy {
  as_of: string;
  stock: { table: DipRow[]; by_basket: Record<string, Record<string, DipSumm>> };
  basket: { table: DipRow[]; by_basket: Record<string, Record<string, DipSumm>> };
  /** 검증 기간(분석 기간 직전 1년) — 종목 기준, 같은 규칙 */
  check?: { start: string; end: string; table: DipRow[] };
  /** 시장 국면 필터(SPY 200일선 위일 때만) — 기준선도 같은 날들로 */
  regime?: (DipSumm & { period: string; filter: boolean; cond: string; label: string; base: DipSumm })[];
  recent: { ticker: string; basket: string | null; conds: string[]; chg5: number | null }[];
}

export function getLabMeta(): Promise<LabMeta> {
  return call(`/api/v1/strategy/lab/meta`);
}

export function getLabSpread(p: { a: string; b: string; ind: string; n: number; hold: number }): Promise<LabSpread> {
  const q = new URLSearchParams({ a: p.a, b: p.b, ind: p.ind, n: String(p.n), hold: String(p.hold) });
  return call(`/api/v1/strategy/lab/spread?${q}`);
}

export function getLabLeaderboard(hold: number, scope: "all" | "same" | "cross" = "all"): Promise<LabLeaderboard> {
  return call(`/api/v1/strategy/lab/leaderboard?hold=${hold}&scope=${scope}`);
}

export function getLabDip(): Promise<DipStudy> {
  return call(`/api/v1/strategy/lab/dip`);
}
