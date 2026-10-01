// Typed client for the FastAPI backend. Shapes mirror docs/architecture/contract.md §5.

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export const APP_VERSION = "0.1.0";

export type JobStatus = "PENDING" | "RUNNING" | "SUCCESS" | "FAILED";

export interface Job {
  id: string;
  job_type: string;
  status: JobStatus;
  payload: unknown | null;
  result: unknown | null;
  error_message: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  updated_at: string;
}

export interface JobListResponse {
  items: Job[];
  total: number;
  limit: number;
  offset: number;
}

interface ApiErrorEnvelope {
  error: {
    code: string;
    message: string;
    details?: Record<string, unknown>;
  };
}

export class ApiError extends Error {
  status: number;
  code: string;
  details?: Record<string, unknown>;

  constructor(
    status: number,
    code: string,
    message: string,
    details?: Record<string, unknown>,
  ) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE_URL}${path}`, init);
  } catch {
    // Network failure / API unreachable — no HTTP response at all.
    throw new ApiError(0, "NETWORK_ERROR", "API unreachable");
  }

  let data: unknown = null;
  const text = await res.text();
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = null;
    }
  }

  if (!res.ok) {
    const env = data as ApiErrorEnvelope | null;
    const code = env?.error?.code ?? "INTERNAL_ERROR";
    const message = env?.error?.message ?? `Request failed (${res.status})`;
    throw new ApiError(res.status, code, message, env?.error?.details);
  }

  return data as T;
}

export function getJobs(
  params: { limit?: number; offset?: number; status?: JobStatus } = {},
): Promise<JobListResponse> {
  const q = new URLSearchParams();
  if (params.limit != null) q.set("limit", String(params.limit));
  if (params.offset != null) q.set("offset", String(params.offset));
  if (params.status) q.set("status", params.status);
  const qs = q.toString();
  return request<JobListResponse>(`/api/v1/jobs${qs ? `?${qs}` : ""}`);
}

const JSON_HEADERS = { "Content-Type": "application/json" };
/* ── [국내 ETF 신규상장] `core/etf_listing_sync` (KRX·OpenDART, 개인 무료 키) ──────────
   ★DART 는 확정 상장일을 주지 않는다. 그래서 확정(`listing`, KRX LIST_DD)과
     예정(`upcoming`, DART 펀드공시)이 따로 온다. 섞으면 "오늘 상장"이라 써 놓고
     다음 주에 상장하는 일이 생긴다. ⚠️실시간 시세 필드는 없다(원천이 회사 PC 였다). */
export interface EtfListingHolding {
  name: string;
  /** % — KRX 비중이 '-' 면 평가금액 비중. 둘 다 없으면 null. */
  weight: number | null;
}
/** 성적표 한 줄 — 상장일 하루치 KRX 값. 금액 단위는 **억원**, `ret` 는 소수(0.0153 = 1.53%). */
export interface EtfListingReportRow {
  rank: number;
  name: string;
  ticker: string;
  fee: number | null;
  trade_value: number | null;
  /** 개인 순매수(억원, KRX MDCSTAT04901). 못 받으면 null — 0 이 아니다. */
  net_buy: number | null;
  ret: number | null;
}
export interface EtfListingRow {
  name: string;
  ticker: string;
  isin: string;
  company: string;
  /** 총보수(%) — KRX ETF_TOT_FEE. */
  fee: number | null;
  benchmark: string;
  asset_class: string;
  holdings: EtfListingHolding[];
}
export interface EtfUpcomingRow {
  rcept_no: string;
  name: string;
  company: string;
  /** 마지막 공시일(YYYY-MM-DD). */
  filed: string | null;
  /** 예상 상장 범위. DART 표지에 없으면 null → 화면은 '미정'. */
  est_from: string | null;
  est_to: string | null;
  is_amend: boolean;
}
export interface EtfNewListingPayload {
  generated_at: string;
  today: string;
  /** 캐시가 비었거나(기동 직후) 원천 오류일 때의 설명. 정상이면 null. */
  note: string | null;
  report: { date: string | null; is_today: boolean; rows: EtfListingReportRow[] };
  listing: { date: string | null; is_today: boolean; rows: EtfListingRow[] };
  upcoming: EtfUpcomingRow[];
}
export function getEtfNewListing(): Promise<EtfNewListingPayload> {
  return request<EtfNewListingPayload>("/api/v1/etf/new-listing");
}

// ── 개인 계좌 포트폴리오 ──────────────────────────────────────────────────────
// 금액은 서버가 **문자열**로 내보낸다(Decimal). 숫자로 파싱하지 말 것 —
// IEEE754 반올림이 원 단위에서 드러나 합계와 종목별 수치가 어긋나 보인다.
// 표시할 때만 formatKrwString 류로 자릿수를 넣는다.

export interface PortfolioAccount {
  id: string;
  broker_code: string;
  broker_name: string;
  account_name: string | null;
  account_number_masked: string | null;
  account_type: string | null;
  base_currency: string;
  is_active: boolean;
  last_synced_at: string | null;
}

export interface PortfolioAccountList {
  items: PortfolioAccount[];
  // false = 계좌가 하나도 없음. 0원이 아니라 "미연동"으로 그려야 한다.
  connected: boolean;
}

export interface PortfolioConnection {
  id: string;
  broker_code: string;
  broker_name: string;
  connection_name: string;
  environment: string;
  status: string;
  last_connected_at: string | null;
  last_synced_at: string | null;
  last_error: string | null;
}

export interface CashByCurrency {
  currency: string;
  cash_balance: string;
  available_cash: string | null;
  // null = 환율이 없어 KRW 합계에서 빠진 금액. 0 이 아니다.
  krw_value: string | null;
}

export interface PortfolioSummary {
  as_of: string | null;
  account_count: number;
  position_count: number;
  total_assets_krw: string | null;
  securities_value_krw: string | null;
  cash_krw: string | null;
  available_cash_krw: string | null;
  purchase_amount_krw: string | null;
  unrealized_pnl_krw: string | null;
  unrealized_return: string | null;
  /** 증권사가 평가손익에서 미리 빼 둔 제비용(실측). 매입 + 손익 + 이것 = 평가액. */
  fee_reserve_krw: string | null;
  /** 같은 값의 모형 추정(0.25% × (매입 + 평가)). 설명용이지 칸에 적는 값이 아니다. */
  fee_reserve_modelled_krw: string | null;
  cash_by_currency: CashByCurrency[];
}

export interface PortfolioHolding {
  account_id: string;
  account_name: string | null;
  broker_code: string;
  asset_id: string;
  ticker: string;
  name: string | null;
  market: string;
  country: string;
  currency: string;
  asset_type: string | null;
  sector: string | null;
  industry: string | null;
  // "MANUAL" = 사람이 지정한 값. 자동 분류가 덮지 않는다.
  sector_source: string | null;
  // AI/Tech 밸류체인 3단계 — 전통 섹터와 다른 축이다.
  tech_l1: string | null;
  tech_l2: string | null;
  tech_l3: string | null;
  // 배분 '섹터' 축(exposure)의 조각 키 — 서버가 ETF 대표 노출을 적용한 값.
  exposure: string | null;
  quantity: string;
  average_purchase_price: string | null;
  current_price: string | null;
  purchase_amount_local: string | null;
  market_value_local: string | null;
  market_value_krw: string | null;
  unrealized_pnl_local: string | null;
  unrealized_pnl_krw: string | null;
  unrealized_return: string | null;
  exchange_rate: string | null;
  as_of: string;
}

export interface PortfolioHoldingList {
  items: PortfolioHolding[];
  total_market_value_krw: string | null;
  as_of: string | null;
}

function accountQuery(accountId?: string | null): string {
  // "all"(전체 합산)은 서버에 보내지 않는다 — 파라미터가 없으면 전체가 기본이다.
  return accountId && accountId !== "all"
    ? `?account_id=${encodeURIComponent(accountId)}`
    : "";
}

export function getPortfolioAccounts(): Promise<PortfolioAccountList> {
  return request<PortfolioAccountList>("/api/v1/portfolio/accounts");
}

export function getPortfolioConnections(): Promise<PortfolioConnection[]> {
  return request<PortfolioConnection[]>("/api/v1/portfolio/connections");
}

export function getPortfolioSummary(
  accountId?: string | null,
): Promise<PortfolioSummary> {
  return request<PortfolioSummary>(
    `/api/v1/portfolio/summary${accountQuery(accountId)}`,
  );
}

export function getPortfolioHoldings(
  accountId?: string | null,
): Promise<PortfolioHoldingList> {
  return request<PortfolioHoldingList>(
    `/api/v1/portfolio/holdings${accountQuery(accountId)}`,
  );
}

// ── 비중(allocation) ─────────────────────────────────────────────────────────
// 비중 계산은 서버가 한다. 화면마다 따로 계산하면 반올림이 갈려 같은 숫자가
// 화면마다 다르게 보인다.

export type AllocationDimension =
  // ETF 를 대표 노출로 치환한 L1 축. tech_l1 은 ETF 가 전부 "ETF" 한 덩어리라
  // (평가금액의 61%) 섹터 비중으로 읽히지 않는다.
  | "exposure"
  | "tech_l1"
  | "tech_l2"
  | "tech_l3"
  | "sector"
  | "industry"
  | "asset_type"
  | "country"
  | "currency"
  | "market";

export interface AllocationSlice {
  // null = 미분류. 라벨은 서버가 이미 "미분류"로 채워 보낸다.
  key: string | null;
  label: string;
  market_value_krw: string;
  weight: string;
  position_count: number;
}

export interface Allocation {
  dimension: string;
  items: AllocationSlice[];
  total_market_value_krw: string | null;
  unclassified_market_value_krw: string | null;
  as_of: string | null;
}

export function getPortfolioAllocation(
  dimension: AllocationDimension,
  accountId?: string | null,
): Promise<Allocation> {
  const q = accountQuery(accountId);
  return request<Allocation>(
    `/api/v1/portfolio/allocation?dimension=${dimension}${q ? `&${q.slice(1)}` : ""}`,
  );
}

export function setAssetSector(
  assetId: string,
  body: { sector: string | null; industry?: string | null },
): Promise<{ sector: string | null; industry: string | null }> {
  return request(`/api/v1/portfolio/assets/${assetId}/sector`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

// ── 매매(체결) 내역 ──────────────────────────────────────────────────────────

export interface Trade {
  id: string;
  account_id: string;
  account_name: string | null;
  trade_date: string;
  trade_no: string;
  side: "BUY" | "SELL";
  ticker: string;
  asset_name: string | null;
  sector: string | null;
  currency: string;
  quantity: string;
  price: string | null;
  amount_local: string | null;
  settlement_amount_local: string | null;
  commission_local: string | null;
  tax_local: string | null;
  exchange: string | null;
  channel: string | null;
  processed_at: string | null;
}

export interface TradeStats {
  currency: string;
  buy_count: number;
  sell_count: number;
  buy_amount: string;
  sell_amount: string;
  commission: string;
  tax: string;
}

// ── 일별 성과 / 실현손익 ─────────────────────────────────────────────────────

export interface DailyPerformancePoint {
  base_date: string;
  deposit_assets_krw: string | null;
  stock_value_krw: string | null;
  cumulative_pnl_krw: string | null;
  pnl_krw: string | null;
  deposit_krw: string | null;
  withdrawal_krw: string | null;
}

/** 주가 손익 → 원화 증감 사이의 다리. 서버 `app/core/return_bridge.py` 참고. */
export interface ReturnBridge {
  /** 증권사 일별 손익의 합. **환율이 들어 있지 않다** — 주가 손익이다. */
  price_pnl_krw: string | null;
  /** (끝자산 − 시작자산 − 순입금). **원화 기준**이다. */
  asset_change_krw: string | null;
  /** 잔차 = 원화 증감 − 주가 손익. 대부분 환율이지만 '환율'이라 단정하지 않는다. */
  fx_effect_krw: string | null;
  /** 주가 기준 시간가중수익률(연쇄). 환율은 빠져 있다. */
  twr: string | null;
  twr_days: number;
  unmeasured_days: number;
  missing_pnl_days: number;
}

export interface PerformanceSeries {
  items: DailyPerformancePoint[];
  first_date: string | null;
  last_date: string | null;
  start_assets_krw: string | null;
  end_assets_krw: string | null;
  net_deposit_krw: string | null;
  // (끝 - 시작 - 순입금). 입출금 영향을 뺀 실제 증감. **원화 기준**이다.
  gain_krw: string | null;
  bridge: ReturnBridge;
}

export interface RealizedPnlItem {
  id: string;
  sell_date: string;
  ticker: string;
  asset_name: string | null;
  sector: string | null;
  currency: string;
  quantity: string;
  avg_buy_price: string | null;
  avg_sell_price: string | null;
  buy_amount_local: string | null;
  sell_amount_local: string | null;
  commission_tax_local: string | null;
  pnl_local: string | null;
  pnl_krw: string | null;
  pnl_rate: string | null;
  buy_exchange_rate: string | null;
  sell_exchange_rate: string | null;
  // 환차손익 — 주가 손익과 별개다. 합치지 않는다.
  fx_pnl_krw: string | null;
}

/**
 * 실현손익을 **무엇으로 벌었나**로 쪼갠 것.
 *
 * ⚠️증권사 실현손익에는 **비용이 이미 차감돼 있다.** 그래서 `gross_trading_krw`
 *   는 비용을 되더한 값이고, 거기서 `cost_krw` 를 빼야 원래 손익으로 돌아온다.
 * ⚠️원화로는 수수료와 세금이 **합쳐서만** 온다. 분리는 달러뿐이다.
 */
export interface RealizedBreakdown {
  gross_trading_krw: string;
  /** **판 종목**에 붙은 비용(원화). */
  cost_krw: string;
  /** 같은 범위의 달러 금액 — cost_krw 와 짝이 맞는다. */
  cost_local: string | null;
  /** 체결 원장 **전체** 기준 분리. ⚠️cost_krw 의 분해가 아니다(범위가 다르다). */
  commission_usd: string | null;
  tax_usd: string | null;
  dividend_krw: string;
  /** 종목 수익(비용 차감 후) + 배당. */
  net_krw: string;
  /** ⚠️합계에 넣지 않는다 — 종목으로 번 건지 환율로 번 건지 구분이 사라진다. */
  fx_pnl_krw: string | null;
}

export interface RealizedPnlList {
  items: RealizedPnlItem[];
  total: number;
  pnl_krw: string | null;
  fx_pnl_krw: string | null;
  win_count: number;
  loss_count: number;
  first_sell_date: string | null;
  last_sell_date: string | null;
  breakdown: RealizedBreakdown | null;
  /** 같은 기간의 체결 내역 — 한 화면에서 "무엇을 팔았나"까지 본다. */
  trades: Trade[];
  trade_stats: TradeStats | null;
}

export function getPerformance(
  accountId?: string | null,
  days = 365,
): Promise<PerformanceSeries> {
  const q = accountQuery(accountId);
  return request<PerformanceSeries>(
    `/api/v1/portfolio/performance${q ? `${q}&` : "?"}days=${days}`,
  );
}

// ── 성과분석 (ETF성과분석_양식_v2.html 대응) ────────────────────────────────

export interface PeriodReturn {
  label: string;
  days: number;
  return_ratio: string | null;
  start_date: string | null;
  end_date: string | null;
  observations: number;
}

export interface RiskMetrics {
  label: string;
  observations: number;
  annualized_return: string | null;
  volatility: string | null;
  downside_volatility: string | null;
  max_drawdown: string | null;
  max_drawdown_peak_date: string | null;
  max_drawdown_trough_date: string | null;
  sharpe: string | null;
  sortino: string | null;
  hit_ratio: string | null;
}

export interface MonthlyReturn {
  month: string;
  return_ratio: string;
}

export interface DrawdownPoint {
  base_date: string;
  drawdown: string;
}

export interface Contribution {
  asset_id: string;
  ticker: string;
  name: string | null;
  sector: string | null;
  tech_l1: string | null;
  weight: string | null;
  purchase_krw: string | null;
  market_value_krw: string | null;
  unrealized_pnl_krw: string | null;
  unrealized_return: string | null;
  dividend_krw: string | null;
  contribution: string | null;
}

/** 다음 날로 밀려 기록돼 있던 입출금을 하루 앞으로 당긴 기록. 화면에 드러낸다. */
export interface FlowShift {
  moved_from: string;
  moved_to: string;
  amount: string;
}

export interface PerformanceAnalytics {
  first_date: string | null;
  last_date: string | null;
  periods: PeriodReturn[];
  risk: RiskMetrics[];
  monthly: MonthlyReturn[];
  drawdown: DrawdownPoint[];
  contributions: Contribution[];
  total_purchase_krw: string | null;
  total_unrealized_pnl_krw: string | null;
  total_return: string | null;
  realized_pnl_krw: string | null;
  dividend_krw: string | null;
  flow_shifts: FlowShift[];
}

export function getPerformanceAnalytics(
  accountId?: string | null,
  days = 1095,
): Promise<PerformanceAnalytics> {
  const q = accountQuery(accountId);
  return request<PerformanceAnalytics>(
    `/api/v1/portfolio/performance/analytics${q ? `${q}&` : "?"}days=${days}`,
  );
}

// ── 편입비 (매매 이력에서 복원, 원가 USD 기준) ──────────────────────────────

export interface InclusionEvent {
  event_date: string;
  ticker: string;
  asset_name: string | null;
  /** ENTRY(신규 편입) · ADD(추가 매수) · TRIM(일부 매도) · EXIT(전량 청산) */
  kind: "ENTRY" | "ADD" | "TRIM" | "EXIT";
  quantity: string;
  amount: string;
  weight_before: string | null;
  weight_after: string | null;
  holdings_after: number;
}

export interface InclusionHolding {
  ticker: string;
  asset_name: string | null;
  first_entry: string;
  exited_at: string | null;
  /** OPEN(보유 중) · CLOSED(청산) · STALE(매매 이력에 매도가 빠짐) */
  status: "OPEN" | "CLOSED" | "STALE";
  holding_days: number;
  cost: string | null;
  weight: string | null;
  buy_count: number;
  sell_count: number;
}

export interface InclusionWeightPoint {
  base_date: string;
  ticker: string;
  weight: string;
  cost: string;
}

export interface Inclusion {
  currency: string;
  first_trade_date: string | null;
  last_trade_date: string | null;
  holdings: InclusionHolding[];
  events: InclusionEvent[];
  monthly_weights: InclusionWeightPoint[];
  /** **지금 들고 있는 종목의 매입원가 합**이다. 누적 투자원금이 아니다. */
  total_cost: string | null;
  /** 계좌를 연 뒤 산 금액의 합(USD). */
  total_buy: string | null;
  /** 계좌를 연 뒤 판 금액의 합(USD). */
  total_sell: string | null;
  open_count: number;
  exited_count: number;
}

export function getInclusion(
  accountId?: string | null,
  days = 1095,
): Promise<Inclusion> {
  const q = accountQuery(accountId);
  return request<Inclusion>(
    `/api/v1/portfolio/inclusion${q ? `${q}&` : "?"}days=${days}`,
  );
}

// ── 실시간 시세 (보유 종목) ──────────────────────────────────────────────────
// 잔고 동기화(5초)와 **별개**로 돈다. 시세만 받아오므로 5초 주기여도 가볍다
// (실측 17종목 0.60초, 서버에 4초 TTL 캐시).
// ⚠️자산 현황의 금액(평가액·평가손익)은 이 값이 아니라 키움 값을 쓴다(2026-10-01).

export interface LiveQuote {
  ticker: string;
  name: string | null;
  price: string;
  currency: string;
  previous_close: string | null;
  change: string | null;
  change_rate: string | null;
  as_of: string | null;
  source: string;
  /**
   * 이 가격이 **얇은 데이마켓 체결**로 만들어졌는지.
   * 값을 버리지 않는다 — 한국 투자자가 실제로 체결할 수 있는 가격이다.
   * 다만 정규장 가격인 척하게 두지 않는다.
   */
  thin_session: boolean;
  /** 그 봉의 거래량. 얼마나 얇은지 화면이 말할 수 있어야 한다. */
  volume: string | null;
  quantity: string | null;
  market_value_local: string | null;
  market_value_krw: string | null;
  /** ⚠️**증권사와 같은 기준** — 제비용을 뺀 값이다. */
  unrealized_pnl_krw: string | null;
  /** 뺀 제비용(모형). 빼기 전 값이 필요하면 더한다. */
  fee_reserve_krw: string | null;
}

export interface LiveQuotes {
  items: LiveQuote[];
  total_market_value_krw: string | null;
  /** 제비용을 뺀 뒤 — 증권사 스냅샷과 같은 기준이다. */
  total_unrealized_pnl_krw: string | null;
  /** 뺀 제비용의 합(모형). */
  total_fee_reserve_krw: string | null;
  /** 시세를 못 받은 종목. 숨기지 않는다. */
  missing: string[];
  fetched: number;
  as_of: string | null;
}

export function getLiveQuotes(accountId?: string | null): Promise<LiveQuotes> {
  return request<LiveQuotes>(`/api/v1/portfolio/quotes${accountQuery(accountId)}`);
}

// ── 관심종목 ─────────────────────────────────────────────────────────────────

export interface WatchlistItem {
  id: string;
  ticker: string;
  asset_name: string | null;
  memo: string | null;
  target_price: string | null;
  stop_price: string | null;
  sort_order: number;
  /** 지금 보유 중인지. 저장값이 아니라 조회할 때마다 판단한다. */
  held: boolean;
  price: string | null;
  currency: string | null;
  previous_close: string | null;
  change: string | null;
  change_rate: string | null;
  fifty_two_week_low: string | null;
  fifty_two_week_high: string | null;
  /** 52주 저점 0 ~ 고점 1 사이의 위치. */
  fifty_two_week_position: string | null;
  /** 리밸런싱 목표 비중. null 이면 목표를 안 세운 것 — 0% 와 다른 말이다. */
  rebalance_weight: string | null;
  to_target: string | null;
  to_stop: string | null;
  source: string | null;
  as_of: string | null;
}

export interface WatchlistList {
  items: WatchlistItem[];
  missing: string[];
  fetched: number;
}

export function getWatchlist(): Promise<WatchlistList> {
  return request<WatchlistList>("/api/v1/watchlist");
}

export function addWatchlist(body: {
  ticker: string;
  asset_name?: string | null;
  memo?: string | null;
  target_price?: string | null;
  stop_price?: string | null;
}): Promise<WatchlistList> {
  return request<WatchlistList>("/api/v1/watchlist", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

/** 보낸 필드만 반영된다 — 메모만 고쳐도 목표가가 지워지지 않는다. */
export function updateWatchlist(
  id: string,
  body: Partial<{
    memo: string | null;
    target_price: string | null;
    stop_price: string | null;
  }>,
): Promise<WatchlistList> {
  return request<WatchlistList>(`/api/v1/watchlist/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function removeWatchlist(id: string): Promise<WatchlistList> {
  return request<WatchlistList>(`/api/v1/watchlist/${id}`, { method: "DELETE" });
}

export function importHoldingsToWatchlist(): Promise<WatchlistList> {
  return request<WatchlistList>("/api/v1/watchlist/import-holdings", {
    method: "POST",
  });
}

// ── 시장 모니터 ──────────────────────────────────────────────────────────────

export interface MarketRow {
  symbol: string;
  name: string;
  category: string;
  /** price(비율) · rate(bp) · level(포인트) — 단위가 다르다. */
  kind: "price" | "rate" | "level";
  note: string | null;
  price: string | null;
  currency: string | null;
  as_of: string | null;
  changes: Record<string, string | null>;
}

export interface MarketMonitor {
  rows: MarketRow[];
  categories: string[];
  periods: string[];
  missing: string[];
  missing_sources: string[];
}

export function getMarketMonitor(): Promise<MarketMonitor> {
  return request<MarketMonitor>("/api/v1/market/monitor");
}

// ── 리서치 라이브러리 ────────────────────────────────────────────────────────

export interface ResearchDocument {
  name: string;
  relative_path: string;
  extension: string;
  size_bytes: number;
  modified_at: string;
  /** 파일 **이름**에서 찾은 보유 종목. 내용을 읽지 않으므로 놓칠 수 있다. */
  tickers: string[];
}

export interface ResearchLibrary {
  /** false 는 오류가 아니라 **아직 폴더를 안 정한 것**이다. */
  configured: boolean;
  root: string | null;
  problem: string | null;
  documents: ResearchDocument[];
  truncated: boolean;
  matched_count: number;
  /** 켜는 방법. 화면이 그대로 보여 준다. */
  setup_hint: string;
}

export function getResearchLibrary(
  accountId?: string | null,
): Promise<ResearchLibrary> {
  return request<ResearchLibrary>(
    `/api/v1/portfolio/research/library${accountQuery(accountId)}`,
  );
}

// ── 입출금 ───────────────────────────────────────────────────────────────────

export interface CashflowEvent {
  base_date: string;
  deposit_krw: string | null;
  withdrawal_krw: string | null;
  net_krw: string;
  assets_after_krw: string | null;
}

export interface CashflowMonth {
  month: string;
  deposit_krw: string;
  withdrawal_krw: string;
  net_krw: string;
}

export interface Cashflow {
  events: CashflowEvent[];
  monthly: CashflowMonth[];
  total_deposit_krw: string | null;
  total_withdrawal_krw: string | null;
  net_deposit_krw: string | null;
  /** 기간 첫날의 순입출금. 시작 잔고에 포함돼 순입금에서 빠졌다. */
  first_day_flow_krw: string | null;
  /** 기간 시작 시점의 자산. 수익에 섞으면 안 된다. */
  opening_balance_krw: string | null;
  current_assets_krw: string | null;
  /** 금액 증감 — 수익률(TWR)이 아니다. */
  gain_krw: string | null;
  gain_ratio: string | null;
  first_date: string | null;
  last_date: string | null;
}

export function getCashflow(accountId?: string | null, days = 1095): Promise<Cashflow> {
  const q = accountQuery(accountId);
  return request<Cashflow>(
    `/api/v1/portfolio/cashflow${q ? `${q}&` : "?"}days=${days}`,
  );
}

// ── 매크로 지표 ──────────────────────────────────────────────────────────────

export interface MacroRow {
  series_id: string;
  name: string;
  category: string;
  /** level(값 자체) · yoy(전년 대비 변화율) · mom_diff(전월 대비 증감) */
  transform: "level" | "yoy" | "mom_diff";
  unit: string;
  note: string | null;
  value: string | null;
  /** 발표가 한 달 이상 늦는 지표가 있다 — 반드시 띄운다. */
  as_of: string | null;
  changes: Record<string, string | null>;
}

export interface MacroMonitor {
  rows: MacroRow[];
  categories: string[];
  periods: string[];
  missing: string[];
  notes: string[];
}

export function getMacro(): Promise<MacroMonitor> {
  return request<MacroMonitor>("/api/v1/market/macro");
}

export type MacroRange = "5y" | "10y" | "20y" | "max";

export interface MacroHistorySeries {
  series_id: string;
  name: string;
  category: string;
  transform: MacroRow["transform"];
  unit: string;
  note: string | null;
  /** [["YYYY-MM", 값]] — 월말 값, transform 적용 후(yoy 는 비율). */
  points: [string, number][];
}

export interface MacroHistory {
  range: MacroRange;
  /** 모든 차트가 같이 쓰는 x 축 구간(YYYY-MM). */
  start: string;
  end: string;
  series: MacroHistorySeries[];
  /** NBER 경기침체 구간(USREC) [시작월, 끝월] 양끝 포함. */
  recessions: [string, string][];
  categories: string[];
  missing: string[];
}

export function getMacroSeries(range: MacroRange): Promise<MacroHistory> {
  return request<MacroHistory>(`/api/v1/market/macro/series?range=${range}`);
}

// ── 벤치마크 비교 ────────────────────────────────────────────────────────────

export interface BenchmarkPoint {
  base_date: string;
  portfolio: string | null;
  benchmarks: Record<string, string | null>;
}

export interface BenchmarkPeriod {
  label: string;
  start_date: string;
  end_date: string;
  observations: number;
  portfolio: string | null;
  /** 비교의 정본 — 원화 환산. 내 수익률이 원화 기준이기 때문이다. */
  benchmarks_krw: Record<string, string | null>;
  /** "환율을 빼면 얼마였나"를 보려고 같이 낸다. */
  benchmarks_usd: Record<string, string | null>;
  excess: Record<string, string | null>;
}

export interface Benchmark {
  series: BenchmarkPoint[];
  periods: BenchmarkPeriod[];
  benchmarks: string[];
  currency_note: string;
  first_date: string | null;
  last_date: string | null;
  /** 계좌 전체의 **하루 기준** 실효 노출(1.0 = 지수와 같은 크기). */
  effective_exposure: string | null;
  /** 최대 비중 종목 — 왜 그 지수를 골랐는지의 근거. */
  top_ticker: string | null;
  top_weight: string | null;
}

export function getBenchmark(accountId?: string | null, days = 1095): Promise<Benchmark> {
  const q = accountQuery(accountId);
  return request<Benchmark>(
    `/api/v1/portfolio/benchmark${q ? `${q}&` : "?"}days=${days}`,
  );
}

// ── 실적 발표 일정 ───────────────────────────────────────────────────────────

export interface EarningsEvent {
  report_date: string;
  ticker: string;
  company: string;
  /** 장전 · 장후 · 미정 (먼 날짜는 대개 미정) */
  timing: string;
  eps_forecast: string | null;
  estimate_count: number | null;
  last_year_eps: string | null;
  market_cap: string | null;
  held: boolean;
}

export interface EpsHistoryRow {
  period: string;
  kind: string;
  consensus: string | null;
  /** 발표 전이면 null — Nasdaq 은 0.0 으로 준다. */
  actual: string | null;
  surprise: string | null;
}

export interface Earnings {
  mine: EarningsEvent[];
  major: EarningsEvent[];
  window_days: number;
  major_window_days: number;
  total_scanned: number;
  first_date: string;
  last_date: string;
}

export function getEarnings(tickers: string[]): Promise<Earnings> {
  const q = tickers.length ? `?tickers=${encodeURIComponent(tickers.join(","))}` : "";
  return request<Earnings>(`/api/v1/market/earnings${q}`);
}

export function getEpsHistory(symbol: string): Promise<EpsHistoryRow[]> {
  return request<EpsHistoryRow[]>(`/api/v1/market/earnings/${symbol}/history`);
}

// ── AI 생태계 지표 ───────────────────────────────────────────────────────────

export interface Accelerator {
  name: string;
  manufacturer: string;
  kind: string | null;
  release_date: string | null;
  /** 미공개면 null — 0 으로 채우면 "무료"가 된다. */
  price_usd: string | null;
  fp16_flops: string | null;
  fp8_flops: string | null;
  memory_bytes: string | null;
  bandwidth_bytes: string | null;
  tdp_watts: string | null;
  flops_per_watt: string | null;
}

export interface ManufacturerCount {
  name: string;
  count: number;
}

export interface PackageDownloads {
  package: string;
  label: string;
  last_week: number;
  prior_week: number;
  week_over_week: string | null;
  days: string[];
  counts: number[];
}

export interface AiData {
  accelerators: Accelerator[];
  manufacturers: ManufacturerCount[];
  total_accelerators: number;
  downloads: PackageDownloads[];
  sources: string[];
  /** 못 받은 원천. 비어 있으면 둘 다 받았다는 뜻이다. */
  missing: string[];
  /** ⚠️"시장의 최신"이 아니라 **이 데이터셋이 아는 최신** 출시일이다. */
  latest_release_date: string | null;
}

export function getAiData(): Promise<AiData> {
  return request<AiData>("/api/v1/market/ai-data");
}

// ── 환노출 ───────────────────────────────────────────────────────────────────

export interface FxPosition {
  ticker: string;
  name: string | null;
  currency: string;
  market_value_krw: string | null;
  /** 추정값 — 증권사가 매입 환율을 주지 않는다. 모르면 null. */
  estimated_entry_rate: string | null;
  estimated_fx_pnl_krw: string | null;
}

export interface FxShock {
  move: string;
  value_krw: string | null;
  delta_krw: string | null;
}

export interface FxExposure {
  base_currency: string;
  exposed_currency: string;
  current_rate: string | null;
  exposed_value_krw: string | null;
  /** 그중 외화 예수금. 노출에는 넣고, 평가 환차손익 추정에는 넣지 않는다. */
  foreign_cash_krw: string | null;
  exposure_ratio: string | null;
  positions: FxPosition[];
  estimated_entry_rate: string | null;
  rate_change_ratio: string | null;
  /** 추정(매입 환율이 추정이므로). */
  unrealized_fx_krw: string | null;
  /** 실측(증권사가 매수·매도 환율을 준다). */
  realized_fx_krw: string | null;
  shocks: FxShock[];
  rate_as_of: string | null;
  note: string;
}

/** 현재 USD/KRW — 네이버(하나은행 고시)를 먼저, 못 받으면 증권사 환율. */
export interface FxRate {
  rate: string | null;
  source: "naver" | "broker" | "none";
  bank: string | null;
  round: number | null;
  traded_at: string | null;
  fetched_at: string | null;
  /** 네이버 재요청이 실패해 마지막 값을 그대로 쓰는 중. */
  stale: boolean;
  broker_rate: string | null;
}

/** 계절성(계획 C4). 예측이 아니라 "과거에 어땠나" — `evidence=false` 면 '상승'은 기본값일 뿐이다. */
export type SeasonalityWindow = "전구간" | "10년" | "5년";

export interface SeasonalityCell {
  series: string;
  month: number;
  n: number;
  mean: number | null;
  win_rate: number | null;
  t: number | null;
  excess: number | null;
  p: number | null;
  fdr: boolean;
  halves_agree: boolean | null;
}

export interface SeasonalitySignal {
  series: string;
  label: string;
  /** direct | proxy(대용 ETF) | frozen(갱신 중단) */
  continuation: string;
  last_month: string;
  signal: "상승" | "중립" | "하락";
  evidence: boolean;
  t: number | null;
  n: number;
  hist_mean: number | null;
  hist_win_rate: number | null;
  band: [number | null, number | null] | null;
  fdr: boolean;
}

export interface SeasonalityGroup {
  last_month: string;
  signal_month: string | null;
  series: { key: string; label: string; continuation: string; proxy: string | null }[];
  cells: SeasonalityCell[];
  signals: SeasonalitySignal[];
  backtest: Record<"상승" | "중립" | "하락" | "항상상승", { n: number; hit: number | null }>;
}

export interface Seasonality {
  window: SeasonalityWindow;
  t_sig: number;
  groups: Partial<Record<"index" | "sector", SeasonalityGroup>>;
}

export function getSeasonality(window: SeasonalityWindow): Promise<Seasonality> {
  return request<Seasonality>(`/api/v1/market/seasonality?window=${encodeURIComponent(window)}`);
}

export function getSeasonalityCell(
  series: string,
  month: number,
): Promise<{ series: string; label: string; month: number; years: { year: number; ret: number }[] }> {
  return request(`/api/v1/market/seasonality/cell?series=${encodeURIComponent(series)}&month=${month}`);
}

/** 수집기(worker)·외부 원천의 마지막 성공/실패(0019). */
export interface SourceStatus {
  source: string;
  kind: "worker" | "source";
  /** worker: alive/down · source: ok / 403 / 429 / timeout / other / unknown */
  state: string;
  last_ok_at: string | null;
  last_error_at: string | null;
  last_error_kind: string | null;
  last_error_message: string | null;
  detail: Record<string, unknown> | null;
}

export function getJobSources(): Promise<{ items: SourceStatus[] }> {
  return request<{ items: SourceStatus[] }>("/api/v1/jobs/sources");
}

export function getFxRate(accountId?: string | null): Promise<FxRate> {
  return request<FxRate>(`/api/v1/portfolio/fx-rate${accountQuery(accountId)}`);
}

export function getFxExposure(accountId?: string | null): Promise<FxExposure> {
  return request<FxExposure>(`/api/v1/portfolio/fx-exposure${accountQuery(accountId)}`);
}

// ── 거래비용 ─────────────────────────────────────────────────────────────────

export interface CostBySide {
  side: string;
  trade_count: number;
  turnover: string;
  commission: string;
  tax: string;
  cost_ratio: string | null;
}

export interface CostByMonth {
  month: string;
  trade_count: number;
  turnover: string;
  cost: string;
}

export interface CostByTicker {
  ticker: string;
  name: string | null;
  trade_count: number;
  turnover: string;
  cost: string;
  cost_ratio: string | null;
}

export interface TradingCost {
  currency: string;
  trade_count: number;
  turnover: string | null;
  commission: string | null;
  tax: string | null;
  total_cost: string | null;
  /** 분모는 거래대금이다(평가액이 아니다). */
  cost_ratio: string | null;
  by_side: CostBySide[];
  by_month: CostByMonth[];
  by_ticker: CostByTicker[];
  /** 참고용으로 나란히 둘 뿐, 비용과 더하거나 빼지 않는다. */
  realized_pnl_krw: string | null;
  first_trade_date: string | null;
  last_trade_date: string | null;
}

export function getTradingCosts(
  accountId?: string | null,
  days = 1095,
): Promise<TradingCost> {
  const q = accountQuery(accountId);
  return request<TradingCost>(
    `/api/v1/portfolio/costs${q ? `${q}&` : "?"}days=${days}`,
  );
}

// ── 시장 뉴스 (주제별) ───────────────────────────────────────────────────────
// ★보유종목 뉴스와 같은 소스지만 질문이 다르다 — 거기는 "내 종목", 여기는 "판".
// ★**한국어를 쓴다.** 종목 검색은 한국어가 무너졌지만(최저 32%) 주제 검색은
//   97~100% 다(실측) — 주제어가 모호하지 않기 때문이다.

export interface TopicArticle {
  topic: string;
  topic_label: string;
  title: string;
  publisher: string | null;
  published_at: string | null;
  url: string;
  /** 제목에 걸린 내 보유 종목 — 보유종목 뉴스에서 이미 봤을 수 있다. */
  holdings: string[];
}

export interface NewsTopic {
  key: string;
  label: string;
  query: string;
  ok: boolean;
  reason: string | null;
  article_count: number;
  filtered_out: number;
}

export interface MarketNews {
  articles: TopicArticle[];
  topics: NewsTopic[];
  lang: string;
  window_days: number;
  filtered_total: number;
  holdings_hit_count: number;
  /** false 면 화면이 "뉴스가 없습니다"라고 말하면 안 된다. */
  source_ok: boolean;
  notes: string[];
}

export function getMarketNews(lang: "ko" | "en" = "ko"): Promise<MarketNews> {
  return request<MarketNews>(`/api/v1/market/news?lang=${lang}`);
}

// ── 수집 신선도 ──────────────────────────────────────────────────────────────
// ⚠️잔고·보유는 5초마다 자동이지만 **체결·배당·주문·일별성과는 이력 동기화를
//   돌려야만** 들어온다. 한 숫자로 뭉뚱그리면 "방금 동기화됨"이라 적어 놓고
//   체결은 사흘 전 것을 보여 주게 된다.

export interface LedgerFreshness {
  key: string;
  label: string;
  last_date: string | null;
  row_count: number;
  /** 5초 자동 동기화로 갱신되는가. false 면 이력 동기화가 필요하다. */
  auto: boolean;
}

export interface Freshness {
  last_history_sync_at: string | null;
  last_history_sync_status: string | null;
  hours_since: string | null;
  /** 마지막 동기화 이후 미국 정규장이 닫힌 적이 있는가. */
  stale: boolean;
  last_market_close_at: string | null;
  ledgers: LedgerFreshness[];
  notes: string[];
}

export function getFreshness(): Promise<Freshness> {
  return request<Freshness>("/api/v1/brokerage/freshness");
}

export function runHistorySync(): Promise<unknown> {
  return request<unknown>("/api/v1/brokerage/sync", { method: "POST" });
}

// ── 리밸런싱 ─────────────────────────────────────────────────────────────────
// ★알림이 "SOXL 비중 21.32% > 20%" 를 잡아 준다. 여기는 그 다음 질문에 답한다 —
//   **그래서 몇 주를 팔아야 하나.**
// ⚠️`delta_shares` 가 null 이면 **주수를 계산할 수 없었다**(가격 미상). 0 과 다르다.

/**
 * 목표를 정하기 전에 보는 '지금 어떤 모양인가'.
 *
 * ⚠️`effective_exposure` 는 **하루 기준**이다. 레버리지 ETF 의 배수는 하루
 *   수익률에만 적용되고, 여러 날에 걸치면 변동성 끌림 때문에 배수 ×
 *   기간수익률이 되지 않는다.
 */
export interface LeveragePosition {
  ticker: string;
  name: string | null;
  weight: string;
  multiplier: string;
  effective_weight: string;
  source: string;
  /** 시드와 증권사 종목명이 어긋나나. */
  disputed: boolean;
}

export interface PortfolioCharacter {
  leverage: LeveragePosition[];
  leveraged_weight: string;
  effective_exposure: string;
  top1_ticker: string | null;
  top1_weight: string | null;
  top3_weight: string;
  herfindahl: string;
  /** 1/HHI — "사실상 몇 종목에 걸려 있나". */
  effective_count: string | null;
  cash_weight: string;
  leverage_note: string;
}

export interface RebalanceLine {
  ticker: string;
  name: string | null;
  quantity: string;
  current_value_krw: string | null;
  current_weight: string | null;
  target_weight: string;
  target_value_krw: string | null;
  drift: string | null;
  delta_value_krw: string | null;
  price_krw: string | null;
  delta_shares: number | null;
  residual_krw: string | null;
  action: "BUY" | "SELL" | "HOLD";
  within_band: boolean;
  est_cost_krw: string | null;
  memo: string | null;
}

export interface Rebalance {
  lines: RebalanceLine[];
  /** 목표가 없는 보유 종목. **0% 로 치지 않는다.** */
  untargeted: RebalanceLine[];
  base_value_krw: string;
  cash_krw: string | null;
  target_sum: string;
  target_gap: string;
  /** 목표합 + 이 값이 100% 를 넘으면 그 계획은 실행할 수 없다. */
  untargeted_weight: string;
  net_buy_krw: string;
  /** 예수금으로 모자라는 금액. 0 이면 실행 가능. */
  shortfall_krw: string | null;
  band: string;
  buy_krw: string;
  sell_krw: string;
  est_cost_krw: string;
  cost_rate: string;
  trade_count: number;
  character: PortfolioCharacter | null;
  notes: string[];
}

/** 종목 하나의 목표 비중만 세운다 — **다른 목표를 건드리지 않는다.** */
export function putRebalanceTarget(
  ticker: string,
  targetWeight: string,
  memo?: string | null,
): Promise<Rebalance> {
  return request<Rebalance>(
    `/api/v1/portfolio/rebalance/targets/${encodeURIComponent(ticker)}`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ticker, target_weight: targetWeight, memo }),
    },
  );
}

export function deleteRebalanceTarget(ticker: string): Promise<Rebalance> {
  return request<Rebalance>(
    `/api/v1/portfolio/rebalance/targets/${encodeURIComponent(ticker)}`,
    { method: "DELETE" },
  );
}

// ── 알림 ─────────────────────────────────────────────────────────────────────
// ★**아직 보내지 않는다.** 전달 경로(텔레그램 등)가 붙기 전까지 `delivery_configured`
//   는 항상 false 다 — 화면이 "보냈다"고 말하면 안 된다.
// ⚠️상태가 셋이다: TRIGGERED / OK / **UNKNOWN**. 잴 수 없었는데 "미충족"이라고
//   적으면 화면이 괜찮다고 거짓말을 한다.

export interface AlertKind {
  key: string;
  label: string;
  hint: string;
  needs_ticker: boolean;
  /** "price" | "percent" | "days" | null */
  unit: string | null;
}

export interface AlertRule {
  id: string;
  kind: string;
  kind_label: string;
  ticker: string | null;
  name: string | null;
  threshold: string | null;
  unit: string | null;
  enabled: boolean;
  memo: string | null;
  state: "TRIGGERED" | "OK" | "UNKNOWN";
  actual: string | null;
  message: string;
  triggered_since: string | null;
}

export interface Alerts {
  rules: AlertRule[];
  kinds: AlertKind[];
  triggered_count: number;
  unknown_count: number;
  disabled_count: number;
  delivery_configured: boolean;
  notes: string[];
}

export function getAlerts(): Promise<Alerts> {
  return request<Alerts>("/api/v1/alerts");
}

export function createAlert(body: {
  kind: string;
  ticker?: string | null;
  threshold?: string | null;
  memo?: string | null;
}): Promise<AlertRule> {
  return request<AlertRule>("/api/v1/alerts", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function updateAlert(
  id: string,
  body: { threshold?: string; memo?: string; enabled?: boolean },
): Promise<AlertRule> {
  return request<AlertRule>(`/api/v1/alerts/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function deleteAlert(id: string): Promise<Alerts> {
  return request<Alerts>(`/api/v1/alerts/${id}`, { method: "DELETE" });
}

// ── 보유 종목 뉴스 (구글 뉴스 RSS) ───────────────────────────────────────────
// ★키가 필요 없다. 검색어는 SEC 영문 법인명에서 등기 접미사를 걷어내 만든다
//   (실측: `"CORNING INC /NY"` 14건 → `"CORNING"` 100건).
// ⚠️ETF 는 대상이 아니다 — 실측 제목 언급 비율 EETH 15% · TSL 33% · GLD 43%.

export interface NewsArticle {
  /** ⚠️한 기사가 여러 보유 종목에 걸릴 수 있다. 그래서 배열이다. */
  tickers: string[];
  companies: string[];
  title: string;
  publisher: string | null;
  published_at: string | null;
  url: string;
}

export interface NewsTicker {
  ticker: string;
  name: string | null;
  company: string | null;
  /** false 면 아예 대상이 아니다(ETF) — 조회 실패와 다르다. */
  covered: boolean;
  ok: boolean;
  reason: string | null;
  article_count: number;
  /** 관련성 필터로 걸러낸 건수. 숨기지 않는다. */
  filtered_out: number;
}

export interface News {
  articles: NewsArticle[];
  tickers: NewsTicker[];
  window_days: number;
  covered_count: number;
  not_covered_count: number;
  filtered_total: number;
  /** false 면 화면이 "뉴스가 없습니다"라고 말하면 안 된다. */
  source_ok: boolean;
  notes: string[];
}

export function getHoldingsNews(accountId?: string | null): Promise<News> {
  return request<News>(`/api/v1/portfolio/news${accountQuery(accountId)}`);
}

// ── 기간 리포트 ──────────────────────────────────────────────────────────────
// ⚠️**기간별 평가 기여도는 없다.** 종목별 "이번 달 기여"를 내려면 보유 일별
//   시계열이 필요한데 스냅샷이 6건뿐이다. 실현손익(증권사 실측)만 종목별로 온다.

export interface ReportPeriod {
  key: string;
  label: string;
  start_date: string;
  end_date: string;
}

export interface ReportRealized {
  ticker: string;
  name: string | null;
  pnl_krw: string;
  fx_pnl_krw: string | null;
  sell_count: number;
}

export interface ReportPositionChange {
  ticker: string;
  name: string | null;
  kind: "NEW" | "CLOSED";
  first_date: string;
  last_date: string;
  trade_count: number;
}

export interface ReportBenchmark {
  name: string;
  return_krw: string | null;
  excess: string | null;
}

/** '그 외'의 분해. 넷을 더하면 total_krw 가 된다. */
export interface ResidualBreakdown {
  total_krw: string | null;
  /** **추정**이다 — 전일 주식평가액 × 환율 변동률. 나머지는 실측. */
  fx_estimate_krw: string | null;
  dividend_krw: string;
  cost_krw: string;
  /** 넷으로 설명되지 않고 남는 것. 0 으로 맞추지 않는다. */
  leftover_krw: string | null;
  fx_days: number;
  fx_missing_days: number;
}

export interface Report {
  periods: ReportPeriod[];
  period: ReportPeriod | null;
  opening_assets_krw: string | null;
  closing_assets_krw: string | null;
  net_flow_krw: string;
  pnl_krw: string;
  /** ⚠️환차손익이라고 부르지 않는다 — 실측할 수 없다. */
  unexplained_krw: string | null;
  /** 구간이 짧아 계산할 수 없으면 null(0 이 아니다). */
  twr: string | null;
  benchmarks: ReportBenchmark[];
  /** 같은 창의 USD/KRW 변동. '그 외'를 견줘 보라고 나란히 준다. */
  fx_change_ratio: string | null;
  residual: ResidualBreakdown;
  buy_count: number;
  sell_count: number;
  turnover_krw: string;
  cost_krw: string;
  dividend_krw: string;
  realized: ReportRealized[];
  realized_total_krw: string;
  changes: ReportPositionChange[];
  best_day: string | null;
  best_day_krw: string | null;
  worst_day: string | null;
  worst_day_krw: string | null;
  trading_days: number;
  notes: string[];
}

export function getReport(
  accountId?: string | null,
  period?: string | null,
): Promise<Report> {
  const q = accountQuery(accountId);
  const suffix = period ? `${q ? `${q}&` : "?"}period=${period}` : q;
  return request<Report>(`/api/v1/portfolio/report${suffix}`);
}

// ── 공시 (SEC EDGAR) ─────────────────────────────────────────────────────────
// ★키가 필요 없다. ⚠️내부자 서식(3/4/5/144)은 **건수로만** 온다 — 실측 NVDA
//   최근 1001건 중 803건이 임원 서류라 나열하면 나머지가 안 보인다.

export interface Filing {
  ticker: string;
  company: string | null;
  form: string;
  form_label: string;
  category: string;
  filed_date: string;
  report_date: string | null;
  /** 8-K 항목 코드. 그 자체로는 뜻이 없다. */
  items: string[];
  /** 항목 코드의 한국어 이름("2.02" → "실적 발표"). */
  item_labels: string[];
  url: string;
}

export interface FilingTicker {
  ticker: string;
  name: string | null;
  cik: string | null;
  /** ⚠️`ok=false`(못 받았다)와 `filing_count=0`(없다)은 다른 상태다. */
  ok: boolean;
  reason: string | null;
  filing_count: number;
  insider_count: number;
  /** 그중 최근 1/3 구간(기본 30일). ⚠️방향은 모른다 — 매수·매도·부여가 섞여 있다. */
  insider_recent_count: number;
  truncated: boolean;
}

export interface Filings {
  filings: Filing[];
  tickers: FilingTicker[];
  categories: string[];
  window_days: number;
  insider_window_days: number;
  insider_total: number;
  insider_recent_total: number;
  covered_count: number;
  not_covered_count: number;
  /** false 면 화면이 "공시가 없습니다"라고 말하면 안 된다. */
  source_ok: boolean;
  user_agent_is_default: boolean;
}

export function getFilings(accountId?: string | null): Promise<Filings> {
  return request<Filings>(`/api/v1/portfolio/filings${accountQuery(accountId)}`);
}

// ── 세금 (해외주식 양도소득 · 배당소득) ──────────────────────────────────────
// ⚠️**신고 자료가 아니다.** 그리고 여기서만 환차를 양도차익에 더한다 —
//   세법의 양도차익은 원화 기준 양도가액 − 취득가액이라 환율이 과세 대상이다.

export interface TaxSale {
  ticker: string;
  name: string | null;
  sell_date: string;
  quantity: string;
  proceeds_krw: string;
  cost_basis_krw: string;
  expense_krw: string;
  gain_krw: string;
}

export interface TaxYear {
  year: number;
  sale_count: number;
  proceeds_krw: string;
  cost_basis_krw: string;
  expense_krw: string;
  /** 체결일 환율로 계산한 양도차익(법정 정의). */
  gain_krw: string;
  /** 증권사가 준 값(주가손익 + 환차손익). */
  gain_krw_broker: string;
  /** 두 방식의 차이 — 숨기지 않는다. */
  method_diff_krw: string;
  deduction_krw: string;
  taxable_base_krw: string;
  tax_rate: string;
  tax_krw: string;
  /** 기본공제까지 남은 여유. 음수면 이미 과세 구간이다. */
  headroom_krw: string;
  dividend_krw: string;
  dividend_count: number;
  comprehensive_threshold_krw: string;
  sales: TaxSale[];
}

export interface Tax {
  years: number[];
  current: TaxYear | null;
  notes: string[];
}

export function getTax(
  accountId?: string | null,
  year?: number | null,
): Promise<Tax> {
  const q = accountQuery(accountId);
  const suffix = year ? `${q ? `${q}&` : "?"}year=${year}` : q;
  return request<Tax>(`/api/v1/portfolio/tax${suffix}`);
}

// ── 월별 현금흐름 ────────────────────────────────────────────────────────────
// ★여기 금액은 **전부 원화**다. 원천이 account_daily_performance 하나뿐이라
//   통화를 섞을 일이 없다 — 수수료/세금 화면(USD, trades 원천)과는 다른 출처다.
//   두 화면의 비용 숫자를 환율로 이어 붙이지 않는다.

export interface MonthlyCashflowRow {
  month: string;
  /** 외부 흐름 — 내 지갑 ↔ 계좌. 수익이 아니다. */
  deposit_krw: string;
  withdrawal_krw: string;
  net_flow_krw: string;
  /** 계좌가 만든 현금 — 시장과 무관하게 실제로 생기거나 사라진 돈. */
  dividend_krw: string;
  cost_krw: string;
  net_cash_generated_krw: string;
  /** 매매 회전 — 계좌 안에서 현금 ↔ 주식. 손익이 아니다. */
  buy_krw: string;
  sell_krw: string;
  pnl_krw: string;
  opening_assets_krw: string | null;
  closing_assets_krw: string | null;
  /** 월초 + 순납입 + 손익으로 설명되지 않는 나머지. **환차라고 부르지 않는다.** */
  unexplained_krw: string | null;
}

export interface MonthlyCashflow {
  rows: MonthlyCashflowRow[];
  total_deposit_krw: string;
  total_withdrawal_krw: string;
  total_dividend_krw: string;
  total_cost_krw: string;
  net_cash_generated_krw: string;
  total_buy_krw: string;
  total_sell_krw: string;
  months_dividend_covered_cost: number;
  months_total: number;
  first_month: string | null;
  last_month: string | null;
  note: string;
}

export function getMonthlyCashflow(
  accountId?: string | null,
  days = 1095,
): Promise<MonthlyCashflow> {
  const q = accountQuery(accountId);
  return request<MonthlyCashflow>(
    `/api/v1/portfolio/monthly-cashflow${q ? `${q}&` : "?"}days=${days}`,
  );
}

export function getRealizedPnl(
  accountId?: string | null,
  days = 365,
): Promise<RealizedPnlList> {
  const q = accountQuery(accountId);
  return request<RealizedPnlList>(
    `/api/v1/portfolio/realized${q ? `${q}&` : "?"}days=${days}`,
  );
}

// ── 증권사 연동 (키 등록 · 계좌 확인 · 동기화) ───────────────────────────────
// ⚠️키는 **보내기만** 한다. 어떤 응답에도 키가 실려 오지 않는다(지문과 꼬리 4자리뿐).

export interface BrokerAccountPreview {
  external_account_id: string;
  account_number_masked: string | null;
  account_name: string | null;
  account_type: string | null;
}

export interface CredentialsStatus {
  configured: boolean;
  // 키움 허용목록에 등록해야 하는 서버 공인 IP. IP 차단일 때만 채워진다.
  public_ip: string | null;
  environment: string;
  markets: string[];
  fingerprint: string | null;
  app_key_tail: string | null;
  connection_ok: boolean | null;
  connection_reason: string | null;
  connection_message: string | null;
  accounts: BrokerAccountPreview[];
}

export interface SyncResult {
  ok: boolean;
  accounts_synced: number;
  positions: number;
  trades: number;
  daily_performance: number;
  realized_pnl: number;
  dividends: number;
  message: string | null;
}

/** 등록된 키로 조회되는 계좌 목록 — 연결 확인까지 같이 한다(느릴 수 있다). */
export function getBrokerAccounts(): Promise<CredentialsStatus> {
  return request<CredentialsStatus>("/api/v1/brokerage/accounts");
}

export function registerCredentials(body: {
  app_key: string;
  secret_key: string;
  environment: string;
  markets: string[];
}): Promise<CredentialsStatus> {
  return request<CredentialsStatus>("/api/v1/brokerage/credentials", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function runBrokerageSync(): Promise<SyncResult> {
  return request<SyncResult>("/api/v1/brokerage/sync", { method: "POST" });
}

// ── 배당 ────────────────────────────────────────────────────────────────────
// 금액은 증권사가 준 **원화**다. 이 TR(usa21730)은 외화 원금액을 주지 않는다.

export interface DividendItem {
  id: string;
  pay_date: string;
  ticker: string;
  asset_name: string | null;
  sector: string | null;
  amount_krw: string;
  currency: string;
}

export interface DividendList {
  items: DividendItem[];
  total: number;
  total_amount_krw: string | null;
  monthly: { month: string; amount_krw: string; count: number }[];
  by_ticker: {
    ticker: string;
    asset_name: string | null;
    amount_krw: string;
    count: number;
  }[];
  first_pay_date: string | null;
  last_pay_date: string | null;
}

export function getDividends(
  accountId?: string | null,
  days = 365,
): Promise<DividendList> {
  const q = accountQuery(accountId);
  return request<DividendList>(
    `/api/v1/portfolio/dividends${q ? `${q}&` : "?"}days=${days}`,
  );
}

export interface QuickSyncResult {
  ok: boolean;
  positions: number;
  balances: number;
  as_of: string | null;
  elapsed_ms: number;
  message: string | null;
}

/** 가벼운 동기화 — 잔고·보유만 갱신(실측 ~1.6초). 이력은 건드리지 않는다. */
export function runQuickSync(): Promise<QuickSyncResult> {
  return request<QuickSyncResult>("/api/v1/brokerage/sync/quick", {
    method: "POST",
  });
}

// ── 거장 13F (계획 A5) ─────────────────────────────────────────────────────────
// ⚠️기술 도구 — 예측이 아니다. 응답마다 `disclaimer`.

export interface GuruQuarter {
  period: string;
  label: string;
}

export interface GuruRef {
  cik: string;
  guru: string;
  firm: string;
}

export interface GuruStockMove {
  key: string;
  cusip: string;
  name: string | null;
  ticker: string | null;
  n_gurus: number;
  total_bp: number;
  gurus: (GuruRef & { bp: number })[];
}

export interface GuruSectorRow {
  sector: string;
  net_bp: number;
  curr_wgt_bp: number;
  prev_wgt_bp: number;
  up: number;
  down: number;
  top: { cusip: string; name: string | null; ticker: string | null; delta_bp: number }[];
}

export interface GuruSectorFlow extends GuruQuarter {
  prev: GuruQuarter;
  n_participants: number;
  rows: GuruSectorRow[];
  coverage_curr: number | null;
  coverage_prev: number | null;
  unclassified_unreliable: boolean;
}

export interface GuruMyHolding {
  ticker: string;
  name: string | null;
  n_gurus: number;
  avg_bp: number | null;
  delta_bp: number | null;
  holders: (GuruRef & { bp: number })[];
}

export interface GuruOverview {
  disclaimer: string;
  n_gurus: number;
  latest: { period: string; label: string; n_filed: number; n_gurus: number; filed_pct: number; usable: boolean } | null;
  quorum: number;
  curr: GuruQuarter | null;
  prev: GuruQuarter | null;
  period_meta: { period: string; label: string; n_filed: number; filed_pct: number; usable: boolean }[];
  roster: (GuruRef & { last_period: GuruQuarter | null; filed_latest: boolean })[];
  n_participants: number;
  multi_entries: GuruStockMove[];
  multi_exits: GuruStockMove[];
  my_holdings: GuruMyHolding[];
  sector_history: GuruSectorFlow[];
  warnings: string[];
}

export interface GuruRebalanceRow {
  key: string;
  name: string | null;
  ticker: string | null;
  movers: number;
  buyers: number;
  sellers: number;
  gross_bp: number;
  net_bp: number;
  agreement: number;
}

export interface GuruQuarterDetail {
  disclaimer: string;
  curr: GuruQuarter;
  prev: GuruQuarter;
  n_participants: number;
  entries: GuruStockMove[];
  exits: GuruStockMove[];
  total_entries: number;
  total_exits: number;
  rebalance: GuruRebalanceRow[];
  sector: Omit<GuruSectorFlow, "period" | "label" | "prev">;
}

export interface GuruStockTrend {
  disclaimer: string;
  ticker: string;
  periods: GuruQuarter[];
  gurus: (GuruRef & { points: (number | null)[] })[];
}

export function getGuruOverview(): Promise<GuruOverview> {
  return request("/api/v1/research/guru/overview");
}

export function getGuruQuarter(period: string): Promise<GuruQuarterDetail> {
  return request(`/api/v1/research/guru/quarter?period=${encodeURIComponent(period)}`);
}

export function getGuruStock(ticker: string): Promise<GuruStockTrend> {
  return request(`/api/v1/research/guru/stock?ticker=${encodeURIComponent(ticker)}`);
}

// ── 내부자 거래 (계획 A6) ──────────────────────────────────────────────────────
// ★순매수 = 비파생 · 코드 P/S · 10b5-1 계획매매 제외 · 정정 대체분 제외. 나머지는 월 상세에 회색으로.

export interface InsiderMonth {
  month: string;
  n_trades: number;
  net_value: number | null; // 거래 없는 달은 null(막대 없음 — 0 과 다르다)
  by_ticker: { ticker: string; net_value: number }[];
}

export interface InsiderOverview {
  window_days: number;
  rule: string;
  targets: string[];
  no_data: string[];
  data_from: { ticker: string; from: string; to: string }[];
  net_value_window: number;
  buy_count_window: number;
  sell_count_window: number;
  multi_insider_buys: { ticker: string; n_insiders: number }[];
  recent_13d: { filing_date: string; watch_name: string; issuer_name: string | null; headline: string; source_url: string }[];
  monthly: InsiderMonth[];
  future_dated: number;
}

export interface InsiderTrade {
  ticker: string;
  date: string;
  code: string | null;
  code_label: string | null;
  insider: string | null;
  role: string | null;
  shares: number | null;
  price: number | null;
  value: number | null;
  signed_value: number | null;
  planned: boolean;
  counted: boolean;
  excluded_reason: string | null;
  accession: string;
}

export interface InsiderMonthDetail {
  month: string;
  net_value: number | null;
  n_counted: number;
  n_excluded: number;
  trades: InsiderTrade[];
}

export function getInsiderOverview(): Promise<InsiderOverview> {
  return request("/api/v1/research/insiders/overview");
}

export function getInsiderMonth(month: string): Promise<InsiderMonthDetail> {
  return request(`/api/v1/research/insiders/month?month=${encodeURIComponent(month)}`);
}

// ── 거장 명단 관리 (계획 A7) ─────────────────────────────────────────────────

export interface GuruRosterItem {
  cik: string;
  guru_name: string | null;
  firm: string;
  filer_name: string;
  kind: "guru" | "index";
  active: boolean;
  backfill_status: "pending" | "running" | "done" | "failed" | "skip";
  backfill_from: string;
  added_at: string;
  note: string | null;
  n_periods: number;
  last_period: string | null;
}

export interface GuruSearchHit {
  cik: string;
  name: string;
  in_roster: boolean;
  kind: string | null;
  active: boolean | null;
}

export function getGuruRoster(): Promise<{ items: GuruRosterItem[] }> {
  return request("/api/v1/research/guru/roster");
}

export function searchGuru(q: string): Promise<{ query: string; items: GuruSearchHit[] }> {
  return request(`/api/v1/research/guru/search?q=${encodeURIComponent(q)}`);
}

export function addGuru(body: { cik: string; filer_name: string; guru_name?: string; firm?: string }): Promise<GuruRosterItem> {
  return request("/api/v1/research/guru/roster", { method: "POST", headers: JSON_HEADERS, body: JSON.stringify(body) });
}

export function setGuruActive(cik: string, active: boolean): Promise<GuruRosterItem> {
  return request(`/api/v1/research/guru/roster/${cik}`, {
    method: "PATCH",
    headers: JSON_HEADERS,
    body: JSON.stringify({ active }),
  });
}

// ── 실적 모니터 (계획 B3a · B6) ─────────────────────────────────────────────────
// 일정 · EPS 컨센 = Nasdaq, 매출 컨센 = Investing.com(B3b — 실패 시 "수집 실패"), 실적 · 반응 = B4, 관전포인트 = B2 · B5.

export interface EarningsMonEvent {
  id: number;
  ticker: string;
  quarter: string;
  company: string | null;
  report_date: string | null;
  timing: "장전" | "장후" | "미정";
  eps_forecast: number | null;
  n_estimates: number | null;
  revenue_forecast: number | null;
  revenue_forecast_status: "ok" | "failed" | "unverified" | null;
  eps_forecast_verified: boolean;
  revenue_forecast_verified: boolean;
  source: string;
}

export interface EarningsMonUpcoming extends EarningsMonEvent {
  days_left: number;
  within_4w: boolean;
}

export interface EarningsMonResult extends EarningsMonEvent {
  eps_actual: number | null;
  revenue_actual: number | null;
  eps_surprise_pct: number | null;
  revenue_surprise_pct: number | null;
  verdict: "상회" | "부합" | "하회" | null;
  reaction_pct: number | null;
  reaction_window: string | null;
  eps_actual_verified: boolean;
  revenue_actual_verified: boolean;
  verdict_verified: boolean;
  verified: boolean; // compatibility alias for verdict_verified
}

export interface EarningsMonDay {
  date: string;
  week: number;
  tickers: string[];
  bmo: number;
  amc: number;
  tbd: number;
}

export interface EarningsMonOverview {
  today: string;
  targets: string[];
  no_events: string[];
  this_week_count: number;
  last_week: { beat: number; miss: number; inline: number; n: number };
  next: EarningsMonUpcoming | null;
  max_reaction: EarningsMonResult | null;
  days: EarningsMonDay[];
  upcoming: EarningsMonUpcoming[];
  recent: EarningsMonResult[];
}

export interface EarningsMonWatchpoint {
  quarter: string;
  rank: number;
  point: string | null;
  result: string | null;
  source: "import" | "llm";
  model: string | null;
}

export interface EarningsMonStockEvent extends EarningsMonResult {
  filing_url: string | null;
  overall: "서프라이즈" | "중립" | "쇼크" | "미확인" | null; // B5 LLM 결과 판정
  reaction_note: string | null;
  watchpoints: EarningsMonWatchpoint[];
  guidance: {
    metric: string;
    period: string | null;
    low: number | null;
    high: number | null;
    prior_low: number | null;
    prior_high: number | null;
    direction: string | null;
    text: string | null;
  }[];
}

export interface EarningsMonStock {
  ticker: string;
  company: string;
  events: EarningsMonStockEvent[];
}

export function getEarningsMonitor(): Promise<EarningsMonOverview> {
  return request("/api/v1/research/earnings/overview");
}

export function getEarningsMonitorStock(ticker: string): Promise<EarningsMonStock> {
  return request(`/api/v1/research/earnings/stock/${encodeURIComponent(ticker)}`);
}
