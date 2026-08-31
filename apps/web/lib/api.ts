// Typed client for the FastAPI backend. Shapes mirror docs/architecture/contract.md §5.

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export const APP_VERSION = "0.1.0";

export type JobStatus = "PENDING" | "RUNNING" | "SUCCESS" | "FAILED";
export type LogLevel = "INFO" | "WARNING" | "ERROR";

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

export interface JobLog {
  id: string;
  level: LogLevel;
  step: string | null;
  message: string;
  metadata: unknown | null;
  created_at: string;
}

export interface JobDetail extends Job {
  logs: JobLog[];
}

export interface JobListResponse {
  items: Job[];
  total: number;
  limit: number;
  offset: number;
}

export interface JobStats {
  total: number;
  pending: number;
  running: number;
  success: number;
  failed: number;
}

export interface HealthResponse {
  status: "ok" | "error";
  database: "connected" | "disconnected";
}

export interface CsvImportResponse {
  job_id: string;
  import_id: string;
  original_filename: string;
}

export interface AiUsageMeter {
  label: string;
  subtitle: string | null;
  // null = 소진율 판정 불가(업스트림이 %를 산출하지 못한 경우). 0% 로 그리지 않는다.
  pct: number | null;
  remaining_pct: number | null;
}

export interface AiUsageAccount {
  account_num: number;
  email: string | null;
  plan: string | null;
  captured_at: string | null;
  age_seconds: number | null;
  stale: boolean;
  // '사용 크레딧'(초과분 과금) 토글 실측값. false = 플랜 한도에서 그대로 중단.
  // null = 판정 불가(스위치 미발견 / GPT 는 해당 개념 없음).
  extra_usage_enabled: boolean | null;
  items: AiUsageMeter[];
}

export interface AiTokenUsageResponse {
  monitor_base_url: string;
  reachable: boolean;
  error: string | null;
  fetched_at: string;
  claude: AiUsageAccount[];
  codex: AiUsageAccount[];
}

export interface InavEtf {
  ticker: string;
  name: string;
  inav_per_share: number | null;
  kr_etf_price: number | null;
  change_pct: number | null;
  prev_close: number | null;
  trade_value_krw: number | null;
  aum_krw: number | null;
  expense_pct: number | null;
  annual_fee_krw: number | null;
  deviation_pct: number | null;
  priced_weight_pct: number | null;
  component_count: number | null;
  price_candidate_count: number | null;
  priced_component_count: number | null;
  intraday_dev_pct: number | null;
  lp_value_krw: number | null;
}

// ACE 프리픽스(자사 ETF)만 합산한 헤더 합계.
export interface InavSums {
  aum_krw: number | null;
  trade_value_krw: number | null;
  annual_fee_krw: number | null;
}

export interface InavStaleness {
  fx_age_s: number | null;
  price_age_s: number | null;
  twse_age_s: number | null;
  kr_etf_age_s: number | null;
  compute_age_s: number | null;
  basket_basis_date: string | null;
  basket_source: string | null;
  token_valid: boolean;
  token_ttl_s: number | null;
}

export interface InavComponentRow {
  isin: string | null;
  name: string;
  exchange: string | null;
  currency: string | null;
  quantity: number | null;
  basePrice: number | null;
  livePrice: number | null;
  krwPrice: number | null;
  weightPct: number | null;
  tradeTime: string | null;
  isCash: boolean;
  valueSource: string;
}

export interface InavEtfComponents {
  etfName: string;
  inavTotalKrw: number | null;
  components: InavComponentRow[];
}

export interface InavComponentsPayload {
  generatedAt: string;
  timestamp: number;
  fxRates: Record<string, number>;
  byEtf: Record<string, InavEtfComponents>;
}

// WRAP 포트폴리오 실시간 수익률 (구 wrap.js 스키마 + holdings_source/basis_date).
export interface WrapHolding {
  ticker: string;
  name: string | null;
  exchange: string | null;
  currency?: string | null;
  is_cash?: boolean;
  weight_pct: number;
  prev2_close: number | null; // T-2 종가 (소스 시트 E열)
  prev_close: number | null; // T-1 종가 (소스 시트 F열)
  livePrice: number | null;
  // 수익률 = 전일종가/전전일종가 − 1 (현지통화). 카드 ① 의 재료.
  return_pct: number | null;
  // 같은 구간에 환까지 반영 = (1+수익률)(1+환등락) − 1.
  return_krw_pct?: number | null;
  // 기여 = 수익률 × 비중. 이 열의 합이 카드 ① 의 주식분.
  contribution_pct: number | null;
  // 실시간수익률 = 현재가/전일종가 − 1 (장중 등락).
  realtime_return_pct: number | null;
  // 같은 구간에 환까지 반영 = (1+실시간수익률)(1+환등락②) − 1.
  // return_krw_pct 의 ② 짝 — 분류 트리 '환율 ON' × 실시간 모드가 쓴다.
  realtime_return_krw_pct?: number | null;
  matched: boolean;
  tradeTime: string | null;
  cat1: string;
  cat2: string;
  cat3: string;
}

export interface WrapPortfolio {
  key: string;
  name: string;
  return_pct: number;
  matched_weight_pct: number;
  total_weight_pct: number;
  n_matched: number;
  n_total: number;
  holdings: WrapHolding[];
  holdings_source: "SOURCE" | "PDF_FALLBACK" | null;
  basis_date: string | null;
  // 환등락률 원본 — 검산용. ① 은 T-2→T-1(소스 시트), ② 는 T-1→실시간(네이버).
  fx_currency?: string | null;
  fx_return_pct?: number | null;
  fx_realtime_pct?: number | null;
  fx_t2?: number | null;
  fx_t1?: number | null;
  // ② 전일종가→최근체결가 (현지통화 / 환 반영)
  return2_usd?: number | null;
  return2_krw?: number | null;
  // ① 전전일→전일 종가수익률 (현지통화 / 환 반영) + 기준일·신선도
  return1_usd?: number | null;
  return1_krw?: number | null;
  return1_basis_date?: string | null; // "YYYYMMDD"
  return1_prev_date?: string | null; // "YYYYMMDD"
  return1_is_current?: boolean;
  ret1_weight_pct?: number | null; // ① 계산에 실제 들어간 비중합
}

export interface WrapPayload {
  date: string;
  generatedAt: string;
  timestamp: number;
  priceGeneratedAt: string;
  portfolios: WrapPortfolio[];
  fx?: {
    rates?: Record<string, number> | null;
    fetched_at?: string | null;
  } | null;
}

// 성과 비교(track record): 자사(AI코어테크랩) vs TORUS(BM) 누적수익률% 시계열.
// points = [날짜 "YYYY-MM-DD", 누적수익률%(각 시트 인셉션 기준)] 배열.
export interface WrapPerfSeries {
  label: string;
  base_date: string;
  last_date: string;
  points: [string, number][];
}

export interface WrapPerformance {
  generatedAt: string;
  series: Record<string, WrapPerfSeries>; // "aicoretech" | "torus"
}

export function getInavWrapPerformance(): Promise<WrapPerformance> {
  return request<WrapPerformance>("/api/v1/inav/wrap-performance");
}

// [누적 수익률 비교] 등록된 펀드 시계열. S: 의 build_funds.py 가 만든 표준 스키마를 그대로
// 받는다. 엑셀 레이아웃 편차(시트명·헤더 위치·단위)는 전부 S: 에서 흡수되므로 여기서부터는
// 펀드가 2개든 20개든 같은 모양이다.
// points = [날짜 "YYYY-MM-DD", 누적수익률%(각 펀드 인셉션 기준)].
export interface FundSeries {
  id: string;
  label: string;
  inception: string;
  lastDate: string;
  count: number;
  points: [string, number][];
  rebalancing: string[]; // 리밸런싱 날짜 → 차트 마커
  source?: string | null;
  sourceModified?: string | null;
  generatedAt?: string | null;
  qa?: string[];
}

export interface FundSeriesResponse {
  generatedAt: string;
  funds: FundSeries[];
  skipped: string[]; // 스키마가 안 맞아 건너뛴 파일명
}

export function getFundSeries(): Promise<FundSeriesResponse> {
  return request<FundSeriesResponse>("/api/v1/inav/fund-series");
}

// 소스 엑셀 재적재(S: build_funds 재실행). SMB xlsx 파싱이라 수 초 걸리는 1회성 경로.
export interface FundSeriesRefresh {
  status: "ok" | "error";
  reason?: string;
  log?: string[];
}
export function refreshFundSeries(): Promise<FundSeriesRefresh> {
  return request<FundSeriesRefresh>("/api/v1/inav/fund-series/refresh", {
    method: "POST",
  });
}

// 리밸런싱 이력(track record): 자사·TORUS 시점별 편입 구성.
export interface RebalHolding {
  name: string;
  cat1: string;
  cat2: string;
  cat3: string;
  weight_pct: number;
}
export interface RebalCat {
  name: string; // 대분류
  weight_pct: number;
}
// 리밸 전/후 1주 기여도 (Price 시계열 × 리밸 시점 비중, 대분류 집계).
export interface RebalContribStock {
  name: string;
  cat1: string;
  weight_pct: number;
  ret_pct: number;
  contrib_pct: number;
}
export interface RebalWindowPerf {
  start: string; // "YYYY-MM-DD"
  end: string;
  ret_total: number; // 가격보유 종목 기여 합(구간 수익률 근사)
  priced_n: number;
  total_n: number;
  top: RebalContribStock[]; // 기여 상위 5
  cats: { cat1: string; contrib_pct: number }[]; // 대분류별 기여
}
export interface RebalPerf {
  before: RebalWindowPerf | null; // 직전 구성 기준 리밸 전 1주
  after: RebalWindowPerf | null; // 신규 구성 기준 리밸 후 1주
}
export interface RebalEvent {
  date: string; // "YYYY-MM-DD"
  holdings: RebalHolding[];
  n_holdings: number;
  cash_pct: number;
  etc_pct: number;
  unclassified_pct: number;
  cats: RebalCat[]; // 대분류 소계(분류별 비중 섹션)
  perf?: RebalPerf | null; // 리밸 전/후 1주 기여도 (Price 있을 때만)
}
export interface RebalSeries {
  label: string;
  events: RebalEvent[];
}
export interface WrapRebalancing {
  generatedAt: string;
  portfolios: Record<string, RebalSeries>; // "aicoretech" | "torus"
}

export function getInavWrapRebalancing(): Promise<WrapRebalancing> {
  return request<WrapRebalancing>("/api/v1/inav/wrap-rebalancing");
}

// ── GURU[13F] track record — 13F 기관/거장 포트폴리오 (collector + api proxy) ──
// 백엔드가 최신 스냅샷 리프레시 완료 전까지 503 을 던진다 → 페이지는 degraded 처리.
export interface Guru13fRosterEntry {
  cik: string;
  guru: string;
  firm: string;
  latest: string; // 해당 거장의 최신 분기
  quarters: string[];
  aum_usd: number;
}
export interface Guru13fRoster {
  generatedAt: string;
  dbVersion: string;
  latest_period: string;
  gurus: Guru13fRosterEntry[]; // aum_usd 내림차순 정렬
}

export interface Guru13fHolding {
  cusip: string;
  name: string;
  ticker: string | null;
  weight_pct: number;
  value_usd: number;
  shares: number;
}
export interface Guru13fPortfolio {
  generatedAt: string;
  dbVersion: string;
  cik: string;
  guru: string;
  firm: string;
  period: string;
  filingDate: string | null;
  aum_usd: number;
  n_holdings: number;
  priced_n: number;
  total_n: number;
  top5_pct: number;
  top10_pct: number;
  holdings: Guru13fHolding[]; // 비중 내림차순 top-15
}

export interface Guru13fChangeItem {
  cusip: string;
  name: string;
  ticker: string | null;
  weight_pct: number;
  delta_ppt: number;
}
export interface Guru13fExitItem {
  cusip: string;
  name: string;
  ticker: string | null;
  prev_weight_pct: number;
  delta_ppt: number;
}
export interface Guru13fChanges {
  generatedAt: string;
  dbVersion: string;
  cik: string;
  period: string;
  prevPeriod: string | null;
  isFirst: boolean;
  amended: boolean; // 정정본(13F-HR/A)
  new: Guru13fChangeItem[];
  increased: Guru13fChangeItem[];
  decreased: Guru13fChangeItem[];
  exited: Guru13fExitItem[];
}

export interface Guru13fTimelineSeries {
  cusip: string;
  name: string;
  ticker: string | null;
  weights: number[]; // periods 정렬, PERCENT
}
export interface Guru13fTimeline {
  generatedAt: string;
  dbVersion: string;
  cik: string;
  periods: string[];
  series: Guru13fTimelineSeries[]; // top-8 holdings
}

export interface Guru13fConsensusHolding {
  cusip: string;
  name: string;
  ticker: string | null;
  holders_n: number;
  conviction_pct: number;
}
export interface Guru13fConsensusFlow {
  cusip: string;
  name: string;
  ticker: string | null;
  buyers: number;
  sellers: number;
  net: number;
}
export interface Guru13fConsensus {
  generatedAt: string;
  dbVersion: string;
  period: string;
  prev_period: string | null;
  gurus_n: number;
  holdings: Guru13fConsensusHolding[];
  buys: Guru13fConsensusFlow[];
  sells: Guru13fConsensusFlow[];
}

export interface Guru13fTurnoverRow {
  cik: string;
  guru: string;
  firm: string;
  turnover_pct: number;
  new_n: number;
  exited_n: number;
  partial: boolean;
  aum_usd: number;
}
export interface Guru13fTurnover {
  generatedAt: string;
  dbVersion: string;
  period: string;
  rows: Guru13fTurnoverRow[];
}

export function getGuru13fRoster(): Promise<Guru13fRoster> {
  return request<Guru13fRoster>("/api/v1/inav/guru-13f/roster");
}
export function getGuru13fPortfolio(
  cik: string,
  period: string,
): Promise<Guru13fPortfolio> {
  const q = new URLSearchParams({ cik, period });
  return request<Guru13fPortfolio>(`/api/v1/inav/guru-13f/portfolio?${q.toString()}`);
}
export function getGuru13fChanges(
  cik: string,
  period: string,
): Promise<Guru13fChanges> {
  const q = new URLSearchParams({ cik, period });
  return request<Guru13fChanges>(`/api/v1/inav/guru-13f/changes?${q.toString()}`);
}
export function getGuru13fTimeline(cik: string): Promise<Guru13fTimeline> {
  const q = new URLSearchParams({ cik });
  return request<Guru13fTimeline>(`/api/v1/inav/guru-13f/timeline?${q.toString()}`);
}
export function getGuru13fConsensus(): Promise<Guru13fConsensus> {
  return request<Guru13fConsensus>("/api/v1/inav/guru-13f/consensus");
}
export function getGuru13fTurnover(): Promise<Guru13fTurnover> {
  return request<Guru13fTurnover>("/api/v1/inav/guru-13f/turnover");
}

// ── [GURU 13F] 변동 분석: 동시 리밸런싱 / 편입·방출 / 섹터 ──────────
export interface Guru13fFlowGuru {
  cik: string;
  guru: string;
  firm: string;
}
export interface Guru13fPeriodMeta {
  period: string;
  n_filed: number;
  filed_pct: number;
  usable: boolean; // 제출률이 낮아 비교에서 제외된 분기는 false
}
export interface Guru13fRebalanceRow {
  cusip: string;
  name: string;
  ticker: string;
  movers: number; // 비중을 min_bp 이상 조정한 거장 수
  buyers: number;
  sellers: number;
  gross_bp: number; // Σ|Δwgt| 총 조정량 (방향 상쇄 없음)
  net_bp: number; // ΣΔwgt 순방향
  agreement: number; // |net|/gross · 1=전원 동일방향, 0=정확히 갈림
  holders_prev: number;
  holders_curr: number;
  by_guru: (Guru13fFlowGuru & {
    prev_bp: number;
    curr_bp: number;
    delta_bp: number;
    action: "new" | "exited" | "increased" | "decreased";
  })[];
  // 평소 대비 이례성. 표본(movers_n_obs)이 부족하면 전부 null 이다.
  movers_n_obs: number;
  movers_baseline: number | null;
  movers_pctile: number | null;
  is_unusual: boolean | null;
}
export interface Guru13fEntryExitRow {
  cusip: string;
  name: string;
  ticker: string;
  n_gurus: number;
  total_bp: number;
  avg_bp: number;
  gurus: (Guru13fFlowGuru & { bp: number })[];
}
export interface Guru13fSectorRow {
  sector: string;
  movers: number;
  up: number;
  down: number;
  gross_bp: number;
  net_bp: number;
  agreement: number;
  prev_wgt_bp: number; // 거장 평균 비중 (합산 아님)
  curr_wgt_bp: number;
  top_contributors: { cusip: string; name: string; ticker: string; delta_bp: number }[];
}
interface Guru13fFlowBase {
  kind: string;
  curr_period: string | null;
  prev_period: string | null;
  n_participants: number;
  participants: Guru13fFlowGuru[];
  excluded: string[];
  period_meta: Guru13fPeriodMeta[];
  insufficient_history?: boolean;
}
export interface Guru13fRebalance extends Guru13fFlowBase {
  min_bp: number;
  baseline: { quarters_used: number; min_obs: number };
  rows: Guru13fRebalanceRow[];
  total_rows: number;
}
export interface Guru13fEntriesExits extends Guru13fFlowBase {
  entries: Guru13fEntryExitRow[];
  exits: Guru13fEntryExitRow[];
  total_entries: number;
  total_exits: number;
}
export interface Guru13fSectorFlow extends Guru13fFlowBase {
  coverage: number | null; // 최신분기 비중 기준 섹터 매핑률(%)
  coverage_curr: number;
  coverage_prev: number;
  coverage_gap: number;
  // 분기 간 매핑률 격차가 크면 '미분류' 행의 net 은 실제 이동이 아니라 결손 아티팩트다.
  unclassified_unreliable: boolean;
  mapped_cusips: number;
  min_bp: number;
  rows: Guru13fSectorRow[];
}
export interface Guru13fFlows {
  generatedAt: string;
  dbVersion: string;
  rebalance: Guru13fRebalance;
  entries_exits: Guru13fEntriesExits;
  sector: Guru13fSectorFlow;
}

export function getGuru13fFlows(): Promise<Guru13fFlows> {
  return request<Guru13fFlows>("/api/v1/inav/guru-13f/flows");
}

// ── [매크로] 물가·고용·유동성 패널 ───────────────────────────────────
// 근거는 S: 매크로모니터가 구운 macro_panels.json(FRED/BLS/CME). 계산은 전부 S: 소관이라
// 프론트는 그대로 그리기만 한다 — 여기서 YoY 를 다시 구하면 리포트와 갈라진다.
export interface MacroPriceRow {
  label: string;
  date: string; // 관측 기간 시작일 YYYY-MM-DD
  index: number;
  yoy: number | null;
  yoy_prev: number | null;
  mom: number | null;
  ann3: number | null;
  ann6: number | null;
  basis: "NSA" | "SA"; // YoY 산출 근거 — PCE 는 FRED 가 SA 만 준다
  spark: number[];
  series_id_sa: string;
  series_id_nsa: string | null;
}
export interface MacroLaborRow {
  label: string;
  date: string;
  value: number;
  unit: string;
  chg_1m: number | null;
  chg_12m: number | null;
  spark: number[];
  series_id: string;
}
export interface MacroLiquidityRow {
  label: string;
  date: string;
  value: number;
  unit: string;
  chg_short: number | null;
  chg_long: number | null;
  short_label: string; // "4주" | "1개월" — 주간·월간 시리즈가 섞여 있다
  long_label: string;
  spark: number[];
  series_id: string;
}
export interface MacroFomcBucket {
  lower: number;
  upper: number;
  prob: number; // 0~1
}
export interface MacroFomcBand {
  lower: number;
  upper: number;
  label: string; // "350-375"
}
export interface MacroFomcCell {
  prob: number | null; // 0~1
  rank: number; // 1=회의 내 최고확률, 2=차순위, 0=그 외(0% 는 순위 제외)
}
export interface MacroFomcMeeting {
  date: string;
  cells: MacroFomcCell[]; // bands 와 같은 순서
}
export interface MacroFomc {
  snapshot_date?: string;
  fomc_date?: string;
  bands?: MacroFomcBand[];
  meetings?: MacroFomcMeeting[];
  buckets?: MacroFomcBucket[]; // 리포트 페이지4(다음 회의 막대)가 쓰는 값
}

// 대시보드 선그래프용 — x=시간, y=%. 발표가 이산적이라 점이 듬성하지만 추세로 읽는다.
export interface MacroSeriesPoint {
  d: string; // 관측 기간 시작일
  v: number; // %
}
export interface MacroSeries {
  label: string;
  series_id: string;
  color: string;
  unit: string;
  basis?: "NSA" | "SA"; // 물가 YoY 산출 근거
  mode?: string; // 고용·유동성: "수준" | "YoY"
  // 스케일이 다른 계열을 한 그래프에 놓기 위한 축 지정.
  // 실업률(3.5~4.5%)과 지급준비금 YoY(-13~+21%)를 한 축에 두면 실업률이 직선이 된다.
  axis?: "left" | "right";
  latest: number;
  latest_date: string;
  points: MacroSeriesPoint[];
}
// CPI 세부품목 — BLS flat file(cu.data.0.Current) JOIN 결과.
// 가중치가 flat file 에 없어 기여도(bp)는 만들 수 없다 — 품목별 상승률까지다.
export interface MacroCpiItemRow {
  label: string;
  item_code: string;
  name_en: string; // BLS 품목 마스터 원명 — 한글 라벨이 무엇을 가리키는지 대조용
  date: string;
  yoy: number | null;
  mom: number | null;
  ann3: number | null;
  basis: "SA" | "NSA"; // MoM·3M 산출 근거
  spark: number[];
}
export interface MacroCpiDetail {
  groups: MacroCpiItemRow[]; // 품목 그룹 8종
  cuts: MacroCpiItemRow[]; // 에너지·주거비·서비스·근원상품
  note: string;
}
// 최근 '처음 들어온' 관측치 = 새 발표. 표는 최신값만 보여줘서 무엇이 새로 반영됐는지
// 알 수 없다. 월간 지표라 대부분의 날은 빈 배열이다.
export interface MacroRelease {
  series_id: string;
  name_ko: string | null;
  unit: string | null;
  observation_date: string;
  value: number | null;
  first_seen_at: string;
}
// PPI 상품군(제조 투입원가) 15군. 그룹 총지수는 BLS flat file 에 NSA 만 있어 YoY 만 낸다
// — NSA 로 MoM 을 내면 농산물·연료처럼 계절성 큰 군에서 거짓 신호가 된다.
export interface MacroPpiGroupRow {
  label: string;
  group_code: string;
  series_id: string;
  name_en: string;
  date: string;
  index: number;
  yoy: number | null;
  yoy_prev: number | null;
  spark: number[];
}
export interface MacroPpiGroups {
  rows: MacroPpiGroupRow[];
  note: string;
}
// 수집이 조용히 멈추는 것이 이 파이프라인의 실제 실패 모드다. blocked(자격증명 미설정)는
// 고장이 아니라 대기라서 경고로 올리지 않는다 — 매일 뜨는 경고는 진짜 장애를 가린다.
export interface MacroCollection {
  last_ok_at: string | null;
  age_hours: number | null;
  stale: boolean;
  failed: string[];
  blocked: string[];
  reason: string;
}
// investing.com 스크랩 값 ↔ 원천기관(BLS/FRED) 값 대조. 일치하면 화면에 안 뜬다 —
// 참조 월이 다르거나 파싱이 안 되면 '불일치'가 아니라 비교 대상에서 빠진다(오탐 금지).
export interface MacroCrosscheck {
  event_id: number;
  label: string;
  series_id: string;
  date: string;
  ref_month: number;
  theirs: number;
  ours: number;
  ours_rounded: number;
  match: boolean;
  unit: string;
}
export interface MacroPanels {
  collection: MacroCollection;
  crosscheck: MacroCrosscheck[];
  releases: MacroRelease[];
  ppi_groups: MacroPpiGroups;
  price_series: MacroSeries[]; // 근원 CPI · 근원 PPI · 근원 PCE (YoY %)
  // 물가 툴팁의 세부내역 — 선으로 그리지 않고 커서 시점 값만 쓴다(선 7개는 못 읽는다)
  price_detail_series: { label: string; item_code: string; unit: string; points: MacroSeriesPoint[] }[];
  labor_liq_series: MacroSeries[]; // 실업률(수준) · M2 · 지급준비금 (YoY %)
  // 금리 커브 — 10Y-2Y 스프레드(좌축 %p) + 10년·2년 금리(우축 %). FRED 일간을 주간으로 솎은 값.
  rate_series: MacroSeries[];
  prices: MacroPriceRow[];
  labor: MacroLaborRow[];
  liquidity: MacroLiquidityRow[];
  cpi_detail: MacroCpiDetail;
  ppi_detail: MacroCpiItemRow[]; // PPI 최종수요 분해(상품/서비스 · 식품/에너지/근원)
  fomc: MacroFomc;
  asof: string;
  generatedAt: string;
}

export function getMacroPanels(): Promise<MacroPanels> {
  return request<MacroPanels>("/api/v1/macro/panels");
}

// ── [회의] 회의자료 파일 탐색기 (PoC) ────────────────────────────────
export interface MeetingEntry {
  name: string;
  type: "dir" | "html";
  rel: string; // 루트 기준 상대경로
  size?: number;
}
export interface MeetingListing {
  path: string; // 현재 폴더 (루트는 "")
  parent: string; // 상위 폴더 rel
  entries: MeetingEntry[];
}
export interface MeetingFile {
  path: string;
  html: string; // 자체완결 HTML 원문 (iframe srcDoc 용)
}
export function getMeetingList(path = ""): Promise<MeetingListing> {
  return request<MeetingListing>(
    `/api/v1/inav/meeting/list?path=${encodeURIComponent(path)}`,
  );
}
// 원본 S: 파일을 부서에서 수시로 고치므로 매 호출이 디스크 재읽기여야 한다(collector
// 는 캐시·ETag 없이 그때그때 읽는다) — 브라우저 HTTP 캐시를 끊어 갱신 버튼이 실제로
// 최신본을 가져오게 한다.
export function getMeetingFile(path: string): Promise<MeetingFile> {
  return request<MeetingFile>(
    `/api/v1/inav/meeting/file?path=${encodeURIComponent(path)}`,
    { cache: "no-store" },
  );
}

// ── [뉴스 모니터링 · 텔레그램] 카드 피드 ──────────────────────────────
// 내용과 '언급 n건'은 전부 상류(S: Telegram_Bot)가 만든 집계 JSON 에서 온다 —
// 일간 HTML 리포트와 같은 산정 방식(Opus 가 24h 토픽을 의미 단위로 묶음)이고,
// 풀링은 08:00·13:00 KST. collector 는 읽어 넘기기만 한다.
export interface TelegramNewsCard {
  id: string;
  title: string;
  chips: string[]; // summary 를 '·' 로 끊은 수치·키워드
  mentions: number | null; // 관련 토픽 수 (Opus 추정)
  notable: boolean; // 단독·특이 (열당 2장, 리포트의 앰버 카드)
}
export interface TelegramNewsSection {
  key: "macro" | "industry" | "stock";
  label: string;
  icon: string;
  cards: TelegramNewsCard[]; // 상위 3 + 특이 2 = 5장
}
export interface TelegramNews {
  generatedAt: string; // 상류가 집계한 시각
  readAt: string; // collector 가 읽은 시각
  available: boolean; // 집계 파일 존재 여부
  stale: boolean; // 예정 풀링이 빠졌는가
  expectedAt: string; // 직전에 돌았어야 할 풀링 시각
  poolTimes: string[]; // ["08:00","13:00"]
  windowHours: number;
  windowStart: string;
  windowEnd: string;
  topics: number; // 집계에 들어간 토픽 수
  rooms: number;
  analysisPath: string;
  categories: TelegramNewsSection[]; // 매크로 · 산업 · 종목
}
export function getTelegramNews(): Promise<TelegramNews> {
  return request<TelegramNews>("/api/v1/inav/telegram-news");
}

// ── [성과보고 HTML] S: bat 산출물 뷰어 ────────────────────────────────
// 계산·서사가 전부 S: 쪽 bat 으로 넘어간 구조. 대시보드는 파일명 규약으로 고른
// 자체완결 HTML 을 iframe(srcDoc)으로 띄우기만 한다. 기준일=파일명, 작성일=mtime.
// [성과분석 보고서] S: 의 단일PORT_분석.bat / 비교PORT_분석.bat 산출물.
// legacy 는 은퇴한 파이프라인이 남긴 지난 보고서다(목록에서 사라지지 않게 계속 읽는다).
export interface PerfReportItem {
  rel: string; // 루트 기준 상대경로 (파일 요청 키)
  name: string;
  kind: "single" | "compare" | "legacy";
  scope: string; // "일간" | "주간" | "월간" | "데일리" | "위클리"
  who: string; // "AI코어테크" | "AI코어테크 vs TORUS"
  asOf: string; // 기준일 (파일명에서)
  label: string; // "단일 · AI코어테크 · 월간 · 2026.07.31 기준"
  writtenOn: string; // 파일 mtime 날짜
  savedAt: string; // 파일 mtime (분까지)
}
export interface PerfReportListing {
  today: string;
  status: "ready" | "empty";
  current: PerfReportItem | null; // 가장 최근 보고서 (기준일 → 작성일 순)
  latest: PerfReportItem | null; // current 와 같다. 호환용
  items: PerfReportItem[];
  generatedAt: string;
}
export interface PerfReportFile {
  path: string;
  html: string;
}
export function getPerfReportList(): Promise<PerfReportListing> {
  return request<PerfReportListing>("/api/v1/inav/perf-report", {
    cache: "no-store",
  });
}
// bat 이 같은 파일을 덮어쓰므로 매 호출이 디스크 재읽기여야 한다 — 브라우저 캐시를
// 끊어 '갱신'이 실제 최신본을 가져오게 한다(회의 탭과 같은 정책).
export function getPerfReportFile(path: string): Promise<PerfReportFile> {
  return request<PerfReportFile>(
    `/api/v1/inav/perf-report/file?path=${encodeURIComponent(path)}`,
    { cache: "no-store" },
  );
}

// ── [성과보고] 데일리·위클리 성과 브리프 ──────────────────────────────
// performance-brief 스킬이 만든 JSON 을 collector 가 요일 규칙(월=위클리 /
// 화~금=데일리)으로 골라 내려준다. 본문 문자열은 인라인 마크업을 쓴다:
//   **굵게** · {+양수 강조} · {-음수 강조}
export type PerfTone = "pos" | "neg";

export interface PerfScore {
  label: string;
  value: string; // 이미 서식된 값 ("−0.46%", "+35bp")
  tone?: PerfTone | null;
  variant?: "alpha" | "ytd" | null;
  sub?: string | null;
}
export interface PerfBarRow {
  label: string;
  note?: string | null;
  value: number; // 부호 있는 값. 바 폭은 프론트가 차트 최대값 기준으로 계산.
  value2?: number | null; // dualBars 전용 — BM
}
export interface PerfPathDay {
  label: string;
  self: number; // %
  bm: number; // %
  spreadBp: number;
}
export type PerfBlock =
  | {
      type: "bars" | "dualBars";
      title: string;
      unit?: string | null;
      valueUnit?: "bp" | "pct" | "pp" | null;
      meta?: string | null; // 리밸런싱 블록 상단 한 줄
      rows: PerfBarRow[];
      caption?: string | null;
    }
  | {
      type: "path";
      title: string;
      unit?: string | null;
      legend?: string | null;
      days: PerfPathDay[];
      caption?: string | null;
    }
  | { type: "stories"; items: PerfStory[] };

export interface PerfStory {
  verdict: string;
  tag?: string | null;
  tagTone?: PerfTone | null;
  body: string;
  watch?: string | null;
}
export interface PerfSection {
  id: string;
  eyebrow: string;
  title: string;
  bm?: string | null;
  scores: PerfScore[];
  blocks: PerfBlock[];
}
export interface PerfMarketChip {
  head: string;
  value?: string | null;
  tone?: PerfTone | null;
  note: string;
}
export interface PerfReport {
  schema: number;
  kind: "daily" | "weekly";
  asOf: string;
  period?: { start: string; end: string } | null;
  writtenOn: string;
  eyebrow: string;
  title: string;
  dateLine: string;
  dateNote?: string | null;
  market: PerfMarketChip[];
  sections: PerfSection[];
  checkpoints?: { title: string; items: { head: string; note: string }[] } | null;
  footnote?: string | null;
}
export interface PerfBriefResponse {
  today: string;
  weekday: number; // 0=월
  expected: "daily" | "weekly" | null;
  status: "ready" | "pending" | "off";
  report: PerfReport | null;
  latest: {
    kind: "daily" | "weekly";
    asOf: string;
    label: string;
    writtenOn: string | null;
  } | null;
  source?: string;
  generatedAt: string;
}
export function getPerfBrief(): Promise<PerfBriefResponse> {
  return request<PerfBriefResponse>("/api/v1/inav/perf-brief");
}

// [분석 시작] — 운용역 소스 엑셀을 그 자리에서 읽어 정량 분석만 만든 report.
// 서사 블록(market/stories/checkpoints)은 비어 있다 — 뉴스 조사가 필요해 엑셀만으론 못 만든다.
export interface PerfAnalysis extends PerfReport {
  warnings: string[];
  source: string; // 읽은 엑셀 파일명
  sourceSavedAt: string; // 그 파일의 최종 저장 시각
}
export function getPerfAnalysis(mode: "daily" | "weekly"): Promise<PerfAnalysis> {
  return request<PerfAnalysis>(`/api/v1/inav/perf-brief/analyze?mode=${mode}`);
}

// [보고서 생성] — Windows 러너의 claude 서브프로세스가 뉴스 조사 + 서사까지 붙인
// 완성 보고서를 만들어 정기미팅 폴더에 저장한다. 수 분 걸리는 비동기 작업.
export interface PerfGenerateJob {
  status: "idle" | "running" | "done" | "failed";
  mode: "daily" | "weekly" | null;
  startedAt: string | null;
  finishedAt: string | null;
  elapsedSec?: number;
  log: string[];
  error: string | null;
  savedAs: string | null;
}
export function startPerfGenerate(mode: "daily" | "weekly"): Promise<PerfGenerateJob> {
  return request<PerfGenerateJob>(`/api/v1/inav/perf-brief/generate?mode=${mode}`, {
    method: "POST",
  });
}
export function getPerfGenerateStatus(): Promise<PerfGenerateJob> {
  return request<PerfGenerateJob>("/api/v1/inav/perf-brief/generate/status");
}

export interface InavSnapshot {
  date: string;
  generated_at: string;
  timestamp: number;
  market_status: string | null;
  setup_done: boolean | null;
  etf_count: number | null;
  etfs: InavEtf[];
  fx: Record<string, number>;
  sums: InavSums | null;
  staleness: InavStaleness;
}

// CHECK 에이전트 호가 envelope (data.js pass-through — camelCase 무변경).
// asks = [매도5→매도1], bids = [매수1→매수5] 잔량(주) — 구 뷰어와 동일 인덱스 매핑.
export interface HogaEtf {
  code: string;
  name: string;
  asks: number[];
  bids: number[];
  nav: number | null;
  price: number | null;
  obThreshold: number | null;
  premiumIntra: number | null;
  premiumActual: number | null;
  // 최우선 호가 — 2026-07-20 CHECK 에이전트 필드 추가 (이전 피드에는 없어 optional).
  bestAsk?: number | null;
  bestAskQty?: number | null;
  bestBid?: number | null;
  bestBidQty?: number | null;
  // 5단 호가 가격/잔량 — asks/bids 와 달리 둘 다 최우선(1호가)이 인덱스 0.
  // askPrices 오름차순(매도1→매도5), bidPrices 내림차순(매수1→매수5).
  askPrices?: number[] | null;
  askQtys?: number[] | null;
  bidPrices?: number[] | null;
  bidQtys?: number[] | null;
  // 10단 호가 — 2026-07-29 CHECK 확장. 기존 5단을 늘린 게 아니라 별도 필드로 왔다.
  // 앞 5개는 askPrices 와 동일함을 실측 확인(14/14). 판정은 이쪽을 우선 쓴다.
  // ⚠️askQtys10/bidQtys10 은 현재 전 종목·전 인덱스 0 으로 들어온다(CHECK 미채움).
  // 알림·카드는 총호가가 아니라 LP 잔량(lpAskQtys/lpBidQtys)을 쓰므로 판정에는 무관.
  askPrices10?: number[] | null;
  askQtys10?: number[] | null;
  bidPrices10?: number[] | null;
  bidQtys10?: number[] | null;
  // LP 전용 잔량 — 길이 10. index 0 = 최우선, 총호가(askQtys)와 같은 격자·정렬
  // (실측상 LP ≤ 총호가). 호가카드는 이 LP 잔량을 5단으로 표시한다 (2026-07-24).
  //
  // ★격자는 '틱'이 아니라 '호가단계'다 — lpAskQtys[i] 는 askPrices[i] 의 잔량이지
  // (최우선호가 + i틱) 의 잔량이 아니다. CHECK 피드가 빈 틱을 건너뛰므로 둘은 다르다.
  // 2026-07-29 라이브 스냅샷으로 검정: 단계-정렬 가정은 LP ≤ 총호가 위반 0건,
  // 연속틱 가정은 gap 있는 사이드에서 14건 위반 → 단계-정렬이 정답.
  // 따라서 index 5~9 는 6~10번째 호가단계의 LP 잔량인데, 그 단계의 가격은 피드에
  // 오지 않아(askPrices 는 5개뿐) 틱 거리를 계산할 수 없다 — 스프레드 판정이 사실상
  // 상위 5단계로 제한된다.
  //
  // ★예정: CHECK 에이전트가 6~10단계 가격도 싣도록 확장 예정 (2026-07-29 사용자).
  // 그때 **코드 수정은 필요 없다** — 판정 함수(hoga.ts recognizedQuotePrice, collector
  // lp_eval._recognized_quote_price)는 둘 다 prices 길이만큼 훑으므로 askPrices 가
  // 10개로 오면 자동으로 10단계를 본다. 길이가 어긋나도(prices 10 / qtys 5) 양쪽 다
  // 안전하게 건너뛴다. 5를 하드코딩한 LADDER_LEVELS·ASK_LABELS·padLevels 는 전부
  // 호가카드 표시 전용이라 판정과 무관하다(카드는 계속 연속 5틱 창).
  lpAskQtys?: number[] | null;
  lpBidQtys?: number[] | null;
}

// CHECK 에이전트가 hoga 페이로드에 함께 싣는 지수 시세 (payload.indices[]).
// NQ_FUT(나스닥 선물)·KOSPI·KOSPI200·KOSDAQ·KOSDAQ150·KRX300·SPX 등.
export interface IndexQuote {
  code: string;
  name: string;
  price: number | null;
  change: number | null;
  changePct?: number | null;
  tradeDate?: string | null;
}

export interface InavHoga {
  payload:
    | { etfs: HogaEtf[]; index?: IndexQuote | null; indices?: IndexQuote[] | null }
    | null;
  source_timestamp: string | null;
  sent_at: string | null;
  seq: number | null;
  hoga_last_received_age_s: number | null;
  hoga_source_age_s: number | null;
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

export function getHealth(): Promise<HealthResponse> {
  return request<HealthResponse>("/system/health");
}

export function getJobStats(): Promise<JobStats> {
  return request<JobStats>("/api/v1/jobs/stats");
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

export function getJob(id: string): Promise<JobDetail> {
  return request<JobDetail>(`/api/v1/jobs/${id}`);
}

export function createTestJob(payload?: unknown): Promise<Job> {
  return request<Job>("/api/v1/jobs/test", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload === undefined ? {} : { payload }),
  });
}

export function uploadCsv(file: File): Promise<CsvImportResponse> {
  const form = new FormData();
  form.append("file", file);
  return request<CsvImportResponse>("/api/v1/imports/csv", {
    method: "POST",
    body: form,
  });
}

export function getAiTokenUsage(): Promise<AiTokenUsageResponse> {
  return request<AiTokenUsageResponse>("/api/v1/ai-token-usage");
}

// Proxied from the collector profile service. Throws ApiError(503) when the
// collector is stopped/unreachable so the page can render a degraded notice.
export function getInavSnapshot(): Promise<InavSnapshot> {
  return request<InavSnapshot>("/api/v1/inav/snapshot");
}

export function getInavComponents(): Promise<InavComponentsPayload> {
  return request<InavComponentsPayload>("/api/v1/inav/components");
}

export function getWrapSnapshot(): Promise<WrapPayload> {
  return request<WrapPayload>("/api/v1/inav/wrap");
}

export function getInavHoga(): Promise<InavHoga> {
  return request<InavHoga>("/api/v1/inav/hoga");
}

// 지수 롤링 윈도우 통계 — collector가 INDEX_MONITOR.db(CHECK 분단위 적재)에서
// 지수별 '최근 60분 change_pct 변동폭(max−min)'을 계산해 준다 (알림 팝업 트리거②용).
export interface IndexWindowEntry {
  code: string;
  name: string;
  latest_at: string | null;
  latest_age_s: number | null;
  latest_pct: number | null; // 전일 종가 대비 등락률(%)
  latest_price: number | null;
  max_pct: number | null;
  min_pct: number | null;
  max_at: string | null; // 60분 창 내 고점 시각 (KST 'YYYY-MM-DD HH:MM:SS')
  min_at: string | null; // 60분 창 내 저점 시각
  spread_pct: number | null; // 60분 max−min (%p)
  rose: boolean | null; // 저점이 고점보다 먼저 = 최근 1시간 순상승
  n: number;
}

export interface IndexWindow {
  generated_at: string;
  window_min: number;
  indices: IndexWindowEntry[];
}

export function getIndexWindow(): Promise<IndexWindow> {
  return request<IndexWindow>("/api/v1/inav/index-window");
}

// 지수 급등락 하루 알림 로그 — collector가 INDEX_MONITOR 전일 이력을 스캔해 서버측에서
// 계산·보관한다(08:55~16:00). 모든 브라우저가 동일 목록을 받는다(늦게 켜도 소급 표시).
export interface IndexAlertItem {
  id: string;
  code: string;
  label: string;
  // 2026-08-14 이후 roll1h 하나뿐(구 open5 = 09:05 전일比 스냅샷은 폐지 —
  // 임계값이 없어 +0.03% 도 '급등락'으로 나갔고, 지수 줄이 전일比 등락률을
  // 상시 표시하게 되면서 중복이 됐다).
  kind: "roll1h";
  changePct: number;
  spreadPct: number | null; // 60분 변동폭(%p)
  rose: boolean | null;
  maxAt: string | null; // "YYYY-MM-DD HH:MM:SS" (KST)
  minAt: string | null;
  price: number | null;
  at: number; // epoch ms
}
export interface IndexAlertsResponse {
  generatedAt: string;
  alerts: IndexAlertItem[]; // 최신 우선
}
export function getIndexAlerts(): Promise<IndexAlertsResponse> {
  return request<IndexAlertsResponse>("/api/v1/inav/index-alerts");
}

// LP 평가 — collector가 CHECK 호가에서 ACE 9종의 인정 스프레드를 1분마다 표본해
// (LP 의무시간 09:05~15:20) trade_date·기준(basis)별로 누적한다.
// hist 는 틱 히스토그램(차트용). 통계표는 아래 bands(bp 구간별)가 정본이다.

// bp 구간별 통계 — 화면 요약 바의 색 밴드와 같은 경계(0~20 / 20~40 / 40↑ / 없음).
// minutes = 그 구간에 머문 분수(표본 1건 = 1분). mean/mode/median 은 bp 기준이고
// '없음'(인정호가 부재)은 bp 가 없어 null.
export interface LpEvalBand {
  key: "calm" | "warn" | "crit" | "none";
  label: string;
  minutes: number;
  // 2026-08-04 신설 — minutes / session_minutes(총 장 기간 375분) × 100. 화면 통계표는
  // mode 대신 이 값을 쓴다. 수신이 끊긴 분은 어느 구간에도 안 들어가므로 합 < 100%.
  share: number;
  mean: number | null;
  mode: number | null;
  median: number | null;
}

export interface LpEvalBasisStat {
  // 히스토그램 = 원시 틱 분포. 키 "0-2"(0~2틱 묶음, 표본 0 이어도 항상 옴) + "3","4",…
  // 2026-08-04 이전 로직은 20bp 미만을 "ok" 한 칸으로 접었다. 시계열이 없는 과거일
  // (2026-07-28 이전)은 서버가 구 버킷(none/ok/틱)으로 폴백하므로 "0-2" 키가 없다.
  hist: Record<string, number>;
  none_min: number;
  ok_min: number;
  alert_min: number;
  total_min: number;
  mean_tick: number | null;
  mode_tick: number | null;
  median_tick: number | null;
  // 2026-07-30 신설 — 통계표의 정본.
  bands: LpEvalBand[];
  // bp 기록 전(2026-07-30 이전) 표본 분수. 틱만 있어 구간 분류 불가 → 합계에서 빠진다.
  unbanded_min: number;
  // 2026-08-04 신설 — 카드 대표값. mean_bp = 그 날 bp 표본 전체의 시간가중 평균,
  // banded_min = 그 평균의 분모(분). '없음'은 bp 가 없어 분모에서 빠진다.
  mean_bp: number | null;
  banded_min: number;
  // 시간대별 평균 스프레드(bp) — 전 종목. 마지막 구간(전체)은 mean_bp 와 같은 값.
  windows?: LpEvalWindow[];
}
// 시간대별 평균 — 전 종목에 항상 온다(2026-08-04. 그 전에는 중국 편입 3종만).
// 5구간: 09:05~10:30 / 10:30~13:00 / 13:00~14:00 / 14:00~15:30 / 09:05~15:20(전체).
// short = 카드에 5칸을 나란히 놓을 때 쓰는 짧은 라벨(앞 4구간은 시작시각, 마지막은
// '전체'). 앞 4구간이 빈틈없이 이어져 있어 시작시각만으로 구간이 특정된다.
export interface LpEvalWindow {
  key: string;
  label: string;
  short: string;
  mean: number | null;
  minutes: number;
}
// 실제괴리(자체 iNAV 기준, %) 평균 — basis(LP/총호가) 토글과 무관해 ETF 단위다.
// mean 은 부호를 살린 평균(프리미엄/디스카운트 치우침), abs_mean 은 부호 상쇄로
// mean 이 0 에 가까워지는 경우를 드러낸다. windows 는 전 종목에 온다.
// ※ 0199C0 은 서버가 거래소 공시 장중괴리로 덮어 보낸다(iNAV 페이지의 DEV_MIRROR
//   임시조치와 같은 집합) — 두 화면이 같은 '실제괴리'를 말하게 하려는 것.
export interface LpEvalDev {
  mean: number | null;
  abs_mean: number | null;
  minutes: number;
  windows?: LpEvalWindow[];
}
export interface LpEvalEtf {
  code: string;
  name: string;
  basis: { lp?: LpEvalBasisStat; total?: LpEvalBasisStat };
  dev?: LpEvalDev;
}
export interface LpEval {
  trade_date: string;
  generated_at: string;
  session: { start: string; end: string };
  recognized_qty_min: number;
  // 심각도 밴드 경계(bp) — 회색↔오렌지 / 오렌지↔빨강. 요약 바와 동일.
  // 2026-07-30 상시 요약 전환으로 구 alert_min_ticks·alert_min_bp 를 대체.
  warn_bp: number;
  crit_bp: number;
  // 표본 구간 전체 분수(09:05~15:20 = 375). 구간 유지분수 합이 이 값에 못 닿으면
  // 그만큼 CHECK 수신이 끊겼거나 지연됐다는 뜻.
  session_minutes: number;
  available_dates: string[];
  etfs: LpEvalEtf[];
}

export function getLpEval(date?: string): Promise<LpEval> {
  const qs = date ? `?date=${encodeURIComponent(date)}` : "";
  return request<LpEval>(`/api/v1/inav/lp-eval${qs}`);
}

// 인정 스프레드 틱 시계열(분봉) — ETF별 [ts, tick] 포인트. tick=null 은 '없음'.
// available_dates 는 시간이 기록된 날만(과거 집계-only 날 제외).
export interface LpEvalTsSeries {
  code: string;
  name: string;
  points: [string, number | null][];
}
export interface LpEvalTs {
  trade_date: string;
  basis: string;
  session: { start: string; end: string };
  available_dates: string[];
  series: LpEvalTsSeries[];
}

export function getLpEvalTs(date?: string, basis?: string): Promise<LpEvalTs> {
  const params = new URLSearchParams();
  if (date) params.set("date", date);
  if (basis) params.set("basis", basis);
  const qs = params.toString();
  return request<LpEvalTs>(`/api/v1/inav/lp-eval-ts${qs ? `?${qs}` : ""}`);
}

// ── LAN 대시보드 (lan-dashboard 이식) — 필드는 원본 camelCase 계약 유지 ──
export interface LanStatus {
  status: string; // online | offline | error | unknown
  responseTime: number | null;
  error?: string | null;
  httpStatus?: number | null;
  lastChecked: string | null;
}

export interface LanServer {
  id: string;
  name: string;
  host: string;
  port: number;
  protocol: string; // tcp | http | https | heartbeat
  description: string;
  group: string;
  key: string; // heartbeat 키
  maxAgeSec: number | null; // heartbeat 임계(초)
  status: LanStatus;
}

export interface LanServerInput {
  name: string;
  host: string;
  port: number;
  protocol: string;
  description: string;
  group: string;
  key: string;
  maxAgeSec: number | null;
}

const JSON_HEADERS = { "Content-Type": "application/json" };

export function getLanServers(): Promise<LanServer[]> {
  return request<LanServer[]>("/api/v1/lan/servers");
}

export function addLanServer(body: LanServerInput): Promise<LanServer> {
  return request<LanServer>("/api/v1/lan/servers", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify(body),
  });
}

export function updateLanServer(
  id: string,
  body: Partial<LanServerInput>,
): Promise<LanServer> {
  return request<LanServer>(`/api/v1/lan/servers/${id}`, {
    method: "PUT",
    headers: JSON_HEADERS,
    body: JSON.stringify(body),
  });
}

export function deleteLanServer(id: string): Promise<{ ok: boolean }> {
  return request<{ ok: boolean }>(`/api/v1/lan/servers/${id}`, {
    method: "DELETE",
  });
}

export function checkAllLan(): Promise<{ ok: boolean; checkedAt: string }> {
  return request<{ ok: boolean; checkedAt: string }>("/api/v1/lan/check", {
    method: "POST",
  });
}

export function checkLanServer(id: string): Promise<LanStatus> {
  return request<LanStatus>(`/api/v1/lan/check/${id}`, { method: "POST" });
}

export function getLanGroups(): Promise<string[]> {
  return request<string[]>("/api/v1/lan/groups");
}

export function addLanGroup(name: string): Promise<{ name: string }> {
  return request<{ name: string }>("/api/v1/lan/groups", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({ name }),
  });
}

// ── [종목 모니터] KOSPI200 분봉 급등락·이상현상 ──────────────────────────────
// 원천은 Toss_분봉_모니터가 쌓는 분봉 DB. 계산(등락률·σ·거래대금)은 전부 collector 쪽이다.
// ★market_cap·industry·issue 는 원천이 없어 항상 null 이다 — 화면에 컬럼 자리는 두되
//   값은 비워 둔다(사용자 확정 2026-08-21). 소스가 생기면 collector 만 고치면 된다.
export interface StockMonitorRow {
  rank: number;
  symbol: string;
  name: string;
  price: number | null;
  change_pct: number | null;
  value: number | null;          // 분봉 Σ(volume×close) — 토스 '토스증권 거래대금'과 다름
  volume: number | null;
  market_cap: number | null;     // 원천 없음
  industry: string | null;       // 원천 없음
  issue: string | null;          // [실시간 이슈] — 원천 없음
  cap_rank: number | null;
  change_sigma: number | null;   // 등락률 / 그 종목의 sigma_daily
  volume_z: number | null;       // (당일누적 − vol_mu) / vol_sigma
}
export interface StockMonitor {
  asof: string | null;
  day?: string;
  sort?: string;
  market?: string;         // "kr"(기본) | "us"
  universe?: number;
  value_basis?: string;
  change_basis?: string;   // us: 등락률 앵커 정의(직전 정규장 마감 이전 마지막 체결)
  feed_at?: string | null; // us: 수집기 마지막 flush 시각(status.last_flush_at)
  note?: string;
  rows: StockMonitorRow[];
}

// market=us 는 미장_실시간체결가.db lane — 토스 WS 틱 기반, 한글명 없음(name=symbol),
// σ·z 통계 없음(전부 null). KR 과 payload 모양은 같다.
export type StockMarket = "kr" | "us";

export function getStockMonitor(
  sort: "value" | "change" | "sigma" = "value",
  limit = 30,
  market: StockMarket = "kr",
  day?: string,
): Promise<StockMonitor> {
  const qs = new URLSearchParams({ sort, limit: String(limit), market });
  if (day) qs.set("day", day);
  return request<StockMonitor>(`/api/v1/stock-monitor?${qs.toString()}`);
}

// ── [종목 모니터] 상단 지수 스트립 ───────────────────────────────────────────
// 원천은 CHECK 에이전트가 분단위로 쌓는 INDEX_MONITOR.db. spark 는 최근 4시간을
// 60점으로 솎은 가격 배열이다(원본 990틱을 그대로 나르지 않는다).
export interface IndexStripItem {
  code: string;
  name: string;
  price: number | null;
  change: number | null;      // 절대 변화 — DB 컬럼 그대로(역산하지 않음)
  change_pct: number | null;
  at: string;
  spark: number[];
}
export interface IndexStrip {
  generated_at: string;
  indices: IndexStripItem[];
}

export function getIndexStrip(): Promise<IndexStrip> {
  return request<IndexStrip>("/api/v1/stock-monitor/index-strip");
}

// ── [종목 모니터] ETF 순매수 모니터 ──────────────────────────────────────────
// 원천은 CHECK 에이전트가 적재하는 ETF_FLOW_MONITOR.db (관심 ETF 수급 스냅샷,
// 계약은 시장모니터 폴더의 ETF_FLOW_MONITOR_DB_안내.md). 적재 시작 전에는
// rows 가 빈 배열로 온다 — 카드가 대기 문구를 띄운다.
export interface EtfFlowRow {
  code: string;
  name: string | null;
  listing_date: string | null;  // 'YYYY-MM-DD'
  trade_value: number | null;   // 당일 누적 거래대금(원)
  trade_volume: number | null;  // 당일 누적 거래량(주)
  indiv_net_buy: number | null; // 당일 누적 개인 순매수 대금(원, 매수우위 +)
  indiv_net_lp_est: number | null; // LP기반 추정 개인 순매수(원) — 피드 vol3tick(억원)×1e8
  trade_date: string | null;
  observed_at: string;
}
export interface EtfFlows {
  generated_at: string;
  asof: string | null;
  rows: EtfFlowRow[];
}

export function getEtfFlows(): Promise<EtfFlows> {
  return request<EtfFlows>("/api/v1/stock-monitor/etf-flows");
}

// ── [종목 모니터] 수익률 모니터 ──────────────────────────────────────────────
// 원천은 주간가격모니터 price_monitor.xlsx (S: 마운트) — collector price_returns.py
// 가 계산까지 마친 값을 나른다(자산 목록 정본도 그쪽 ASSETS). unit="pct" 는 %수익률,
// "bp" 는 금리 변화폭(bp). rebound 는 1주/1달/3달 저점 대비 중 √시간 정규화로 고른
// 대표 1개(all 에 3종 전부 동봉). spark 는 최근 1년을 60점으로 솎은 값 배열.
export interface PriceReturnAsset {
  key: string;
  name: string;
  unit: "pct" | "bp";
  asof: string;               // 'YYYY-MM-DD' — 그 자산의 마지막 관측일
  last: number;
  returns: {
    ytd: number | null;
    mtd: number | null;
    wtd: number | null;
    dtd: number | null;
  };
  rebound: {
    window: "1w" | "1m" | "3m";
    label: string;            // '1달 저점 대비' 등 — collector 가 정한다
    value: number;
    low: number;
    low_date: string;
    all: Record<string, number | null>;
  } | null;
  spark: number[];
}
export interface PriceReturns {
  generated_at: string;
  asof: string | null;
  assets: PriceReturnAsset[];
}

export function getPriceReturns(): Promise<PriceReturns> {
  return request<PriceReturns>("/api/v1/stock-monitor/price-returns");
}

// ── [AI Key Data] 컴퓨팅 지수 모니터링 ───────────────────────────────────────
// Silicon Data GPU 렌탈 지수($/GPU-hr) — 세대별로 패널 하나씩.
// 원천은 AI Key Data의 GPU임대지수_주가_통합.xlsx — collector compute_index.py
// 가 판독하고 지수 목록 정본도 그쪽 INDICES(현재 H100·B200·A100 순).
// ★단가를 한 차트에 여러 y축으로 겹치면 안 되므로(세대별 스케일 2배 차이) 세로 분할.
// ★기초 파일에 없는 지수는 series 에서 조용히 빠진다 — 화면은 온 것만 그린다.
// points = [날짜 "YYYY-MM-DD", 값] 오름차순.
export interface ComputeIndexStats {
  start: number;
  start_date: string;
  last: number;
  last_date: string;
  min: number;
  min_date: string;
  max: number;
  max_date: string;
  chg_1d_pct: number | null; // 전일 대비(지수가 일간이라 마지막 두 점)
  chg_pct: number | null;    // 구간 전체
  n: number;
}
export interface ComputeIndexSeries {
  key: "h100" | "b200" | "a100";
  name: string;              // 'SDH100RT' | 'SDB200RT' | 'SDA100RT'
  label: string;             // 'H100' | 'B200' | 'A100'
  unit: string;              // '$/GPU-hr'
  kind: "price";
  points: [string, number][];
  stats: ComputeIndexStats;
}
export interface ComputeIndex {
  generated_at: string;
  asof: string | null;
  unit: string;
  // 계열이 비어 있을 때의 사유(예: 원천 xlsx 가 폴더에서 사라짐). 카드가 그대로 띄운다.
  note?: string | null;
  series: ComputeIndexSeries[];
}

export function getComputeIndex(): Promise<ComputeIndex> {
  return request<ComputeIndex>("/api/v1/stock-monitor/compute-index");
}

// ── [AI Key Data] 정책금리 ───────────────────────────────────────────────────
// FOMC 금리 결정(수준 %). 원천은 AI Key Data macro_releases.csv 의 event=RATE
// 행 — 같은 파일의 CPI·PCE 는 전월비 %(변화율)라 단위가 달라 섞지 않는다.
// ★points 는 **결정 시점만** 담는다. 회의 사이엔 금리가 그대로 유지되므로 화면이
//   계단(step)으로 편다 — 점을 직선으로 이으면 없던 중간값이 생긴다.
export interface PolicyRate {
  generated_at: string;
  unit: string;                    // '%'
  note?: string | null;            // 계열이 비었을 때의 사유(원천 결측 등)
  asof: string | null;
  last: number | null;             // 현재 정책금리(%)
  last_date: string | null;
  chg_bp: number | null;           // 직전 결정 대비(bp)
  last_change_date: string | null; // 마지막으로 움직인 회의
  holds: number;                   // 그 뒤 동결 횟수
  points: [string, number][];      // [결정일, 금리%] 오름차순
}

export function getPolicyRate(): Promise<PolicyRate> {
  return request<PolicyRate>("/api/v1/stock-monitor/policy-rate");
}

// ── [AI Key Data] 금리 5주제 ─────────────────────────────────────────────────
// 원천은 `input/raw/금리/금리_2.xlsx` 한 장(신상품팀 공모손차 데이터 사본, 계약서는
// 같은 폴더 _출처.md). 다섯 카드가 같은 파일을 보므로 **엔드포인트도 하나**다 —
// react-query 가 같은 queryKey 로 묶어 주므로 실제 fetch 도 한 번이다.
// ★일별 3,886행짜리(인플레·WTI)는 collector 가 **주간 마지막값**으로 솎아서 준다.
export interface RateSeries {
  key: string;
  label: string;                 // 시트의 컬럼명 그대로(단위 포함)
  last: number;
  last_date: string;
  points: [string, number][];
}
export interface RateSeriesGroup {
  asof: string | null;
  series: RateSeries[];
}
export interface BondIssuer {
  ticker: string;
  name: string;
  amt_b: number;
  n: number;
}
export interface RateBonds {
  by_year: [number, number][];   // [연도, 발행액(십억)]
  by_issuer: BondIssuer[];
  total_b: number;
  n: number;
  asof: string | null;
  // ⚠️발행 통화 액면을 그대로 합산한 값이다(워크북 Year 요약 열과 같은 정의).
  unit: string;
}
export interface RateTopics {
  generated_at: string;
  note?: string | null;
  bonds: RateBonds | null;
  inflation: RateSeriesGroup | null;
  wti: RateSeriesGroup | null;
  adp: RateSeriesGroup | null;
  fomc_prob: RateSeriesGroup | null;
}

export function getRateTopics(): Promise<RateTopics> {
  return request<RateTopics>("/api/v1/stock-monitor/rate-topics");
}

// ══ [AI Key Data] AI 사용량 · Epoch — 2026-08-28 D2안 ═══════════════════════
// 사용자 승인: ADP·FOMC내재확률을 메인에서 이 계열(하위 라우트)로 이주하고
// 그 2칸에 AI 사용량 카드를 넣는다(그리드 무변경, 기존 6장 안 건드림).
// 신규 엔드포인트는 전부 `/api/v1/ai-key-data` 신규 라우터 소관
// (기존 3개는 여전히 `/api/v1/stock-monitor` 밑 — 이전은 별도 작업, ws2 설계 §2.3).
//
// ⚠️★★아래 타입은 ws2 설계 문서의 제네릭 계약(그룹={series:[{key,label,kind,points}]})
//   이 아니라 **실제 라이브 응답을 2026-08-28 curl 로 실측해 그대로 옮긴 것**이다.
//   백엔드(ws1/ws3)가 문서보다 더 구체적인 모양으로 구현했다 — 예: OpenRouter 는
//   벤더가 시계열이 아니라 스냅샷 목록, Epoch 칩은 날짜-값 쌍이 아니라 `quarters`
//   공유축 + 병렬 배열, 데이터센터는 레코드 배열(`buildout`). 화면은 이 실제
//   모양을 작은 매퍼로 `AiSeries`(TimeSeriesChart 입력)로 변환해서 그린다.
//   VS Code(`/vscode-installs`)만 아직 라우트가 없다(404 실측, 2026-08-28) —
//   그 타입만 설계 문서 그대로 유지한 추정치다.

// staleness 소스 블록 — 6개 라이브 엔드포인트가 공통으로 붙이는 그대로.
// ★2026-08-28 재정정: `irrecoverable` 이 이제 6개 전부에 항상 실린다(vscode 만
//   true, 나머지 5개는 명시적 false — curl 로 재확인). 한때 필드가 안 보여서
//   `fetch_ok` 로 우회했었는데 원래 설계(§4.3)대로 되돌린다: stale_days<=1 이면
//   무표시, stale_days>=2 && irrecoverable 이면 rose("N일 미수집 — 복구 불가"),
//   stale_days>=2 (그 외) 면 amber("N일 지연"). 필드 부재와 false 를 가를 필요가
//   이제 없다(항상 명시적으로 온다).
export interface AiKeyDataSource {
  name: string;
  dataset: string;
  url: string;
  license: string | null;
  license_url: string | null;
  citation: string;
  retrieved: string;
  irrecoverable: boolean; // true = 결측이 영구 손실인 소스(현재는 VS Code 뿐)
  stale_days: number;
  fetched_at: string;
  fetch_ok: boolean;
  latest_date: string | null;
}

// 화면이 그리는 저수준 계열(TimeSeriesChart 입력) — API 원본과 모양이 다를 때
// (칩의 병렬 배열, 데이터센터의 레코드 배열, 펀딩의 이벤트 목록) 카드가 매핑한다.
// ★point 값이 null 이면 "결측"이지 0 이 아니다 — 선을 잇지 않고 끊는다.
// anomaly_dates 는 그 날짜의 점을 rose 로 강조한다(예: VS Code MS 소급 정정으로
// 값이 줄어든 날) — 0으로 자르거나 숨기지 않고 **보이게** 만드는 장치.
export interface AiSeries {
  key: string;
  label: string;
  unit?: string;
  kind: "line" | "step" | "scatter";
  last: number | null;
  points: [string, number | null][];
  incomplete_from?: string | null;
  anomaly_dates?: string[];
}

// ── AI 사용량 탭 카드 ① OpenRouter 토큰 사용량 ───────────────────────────────
// 원천 tokens_daily_long.csv(BOM+CRLF) — collector openrouter_tokens.py.
// ★★`coverage:"top50_plus_other"` — 전수가 아니다. `vendors` 는 시계열이 아니라
//   **스냅샷**(최근 창 합계 1개씩)이라 차트가 아니라 숫자 뱃지로만 노출한다.
//   "점유율" 대신 `other_share_pct` 를 그대로 보여준다(모델별 % 는 만들지 않는다).
// `totals.daily_ma7` 가 기본 표시선, `totals.daily` 는 범례 토글(raw). license 는
// `source.license` 가 null 이라 대외 게재 전 이용약관 확인 필요(조건 임의 생성 금지).
// ⚠️이름을 `AiTokenUsage`/`getAiTokenUsage` 로 하면 이미 있는 무관한 기능
//   (Claude/Codex 플랜 사용량 모니터, :84 `AiTokenUsageResponse` · :1203
//   `getAiTokenUsage` → `/api/v1/ai-token-usage`)과 겹쳐 next build 가 죽는다.
//   URL 경로는 설계 그대로 쓰고 TS 식별자만 `OpenRouter` 로 갈랐다.
export interface OpenRouterVendor {
  key: string;
  name: string;
  tokens: number;
  n_models: number;
  share_pct: number;
}
export interface OpenRouterTokenUsage {
  generated_at: string;
  asof: string | null;
  note?: string | null;
  source: AiKeyDataSource | null;
  unit: string; // "tokens"
  coverage: string; // "top50_plus_other"
  totals: {
    daily: [string, number][];
    daily_ma7: [string, number | null][];
    weekly: [string, number][];
  };
  incomplete_buckets: string[]; // 부분 집계 버킷 날짜(주로 weekly 쪽 — daily 뷰엔 영향 적음)
  stats: {
    last_date: string;
    last: number;
    mtd_t: number;
    mom_pct: number | null;
    yoy_x: number | null;
  };
  vendors: OpenRouterVendor[]; // 스냅샷 — 차트 아님, 뱃지 전용
  // ★모델별 **시계열**. 서버가 최근 창(30일) 기준 상위 10개를 골라 실어 준다.
  //   ⚠️`points` 의 값이 `null` 이면 "그날 top-50 밖"이지 0이 아니다 — 선을 끊는다.
  //   ⚠️총합(`totals.daily`, 605일)과 **구간이 다르다**(모델별은 30일). 같은 축에 겹치지 않는다.
  models: OpenRouterModel[];
  // ★★화면이 그리는 건 이쪽이다(2026-08-31 사용자 지시) — **모델 버전이 아니라 벤더**.
  //   `deepseek/deepseek-v4-flash-20260731` 같은 버전 단위는 모델이 갈릴 때마다 선이 끊겨
  //   추세가 안 읽힌다. 벤더로 접으면 "누가 밀고 있나"가 보인다.
  //   ⚠️전 구간(605일)이다. `models` 는 30일 창이라 구간이 다르다.
  //   ⚠️`other(top-50 밖)` 는 벤더가 아니라 OpenRouter 자신의 **잔차 버킷**이고,
  //     `기타 벤더` 는 상위 N 밖 벤더를 접은 것이다 — 뜻이 달라 이름을 갈라 놨다.
  vendor_series: OpenRouterVendorSeries[];
  active_models_30d: number;
  other_share_pct: number;
}
export interface OpenRouterVendorSeries {
  key: string;
  name: string;
  tokens: number;
  share_pct: number | null;
  points: [string, number | null][]; // null = 그날 그 벤더 모델이 top-50 밖(0 아님)
}
export interface OpenRouterModel {
  slug: string;
  vendor: string;
  tokens: number;
  share_pct: number | null;
  points: [string, number | null][];
}
export function getOpenRouterTokenUsage(): Promise<OpenRouterTokenUsage> {
  return request<OpenRouterTokenUsage>("/api/v1/ai-key-data/ai-token-usage");
}

// ── AI 사용량 탭 카드 ② npm 코딩에이전트 다운로드 ────────────────────────────
// 요일 효과가 커서(주말 스윙) `totals.daily_ma7` 이 기본, raw 는 범례 토글.
// `packages[]` 는 패키지별 실측치(자체 raw+ma7+stats 보유) — 카드 폭 제약상
// 차트엔 총합만 그리고, 상위 패키지는 숫자 뱃지로만 노출한다.
export interface NpmPackageStats {
  last: number;
  last_date: string;
  chg_1d_pct: number | null;
  chg_1w_pct: number | null;
  window_total: number;
  share_pct: number;
  n: number;
  stale_days: number;
}
export interface NpmPackage {
  key: string;
  name: string;
  kind: "line";
  points: [string, number][];
  ma7: [string, number | null][];
  stats: NpmPackageStats;
}
export interface NpmDownloads {
  generated_at: string;
  asof: string | null;
  note?: string | null;
  source: AiKeyDataSource | null;
  totals: {
    daily: [string, number][];
    daily_ma7: [string, number | null][];
    // ★화면이 그리는 **유일한 선**. `daily_ma7` 에서 이상치에 오염된 구간만 선형보간으로
    //   갈아 끼운 것이다. 보정 계열을 따로 그어 두 줄로 만들지 않는다(2026-08-31 사용자 지시).
    daily_ma7_interp: [string, number | null][];
  };
  packages: NpmPackage[];
  n_packages: number;
  // 패키지별 이상치 판정 전량(숨기지 않는다). 총합 차트에 다 찍으면 잡음이라
  // 화면은 아래 `totals_anomaly_dates` 만 빨갛게 표시한다.
  anomalies: NpmAnomaly[];
  // 총합 곡선이 실제로 튄 날(비율 20%↑ **그리고** 최댓값의 1%↑ = 차트에서 보이는 것).
  totals_anomaly_dates: string[];
  // `daily_ma7_interp` 에서 실제로 보간된 날짜 — 화면이 이 구간만 빨간 선으로 덧그린다.
  // ⚠️이상치 날짜보다 넓다(ma7 이 7일 창이라 이상치 하루가 평균 7점을 오염시킨다).
  ma7_interp_dates: string[];
}
export interface NpmAnomaly {
  date: string;
  package: string;
  value: number;
  expected: number; // 좌우 창 중앙값의 작은 쪽
  ratio: number;
}
export function getNpmDownloads(): Promise<NpmDownloads> {
  return request<NpmDownloads>("/api/v1/ai-key-data/npm-downloads");
}

// ── AI 사용량 탭 카드 ③ VS Code 확장 설치수 ──────────────────────────────────
// ★2026-08-28 라우트 개통·curl 실측으로 재작성(이전엔 404 라 설계 문서 추정치였다).
// `measure:"stock"` — 시점 누적 총량이지 증분이 아니다. **결측일은 과거 조회 API 가
// 없어 영구 손실**(`source.irrecoverable=true`) — 데몬이 꺼졌던 구간은 `gaps[]`
// 로 남고 다시는 못 채운다.
//
// ★★현재는 스냅샷이 1일치뿐이라(`n_snapshots:1`) `delta`/`delta_marks`/
//   `revisions`/`gaps` 가 전부 빈 배열이다 — note 가 "내일 수집분부터 자동으로
//   생깁니다"라고 명시. 아래 타입·화면 로직은 계약대로 미리 짜 둔 것이고,
//   비어있지 않은 실 데이터로는 아직(2026-08-28) 검증 못 했다.
// ★span_days 필수 확인 지점 — 데몬이 하루 이상 꺼졌다 켜지면 다음 delta 는
//   "하루 증분"이 아니라 `span_days` 일치 누적분이다. 일 증분처럼 그리면 틀린
//   숫자가 된다 — 화면은 `span_days>1` 이면 "N일 누적 + 일평균 환산" 을 같이 적는다.
// ★음수 델타(`delta_marks[].negative`)는 MS 소급 정정 — 0으로 자르거나 숨기지
//   않는다. `revisions[]` 에 원래 from→to 가 보존돼 있어 그대로 노출한다.
export interface VscodeSnapshot {
  date: string;
  utc: string;
  n_extensions: number;
}
// ★2026-08-31 실측으로 정정. 결측 **날짜 문자열 배열**이다(객체가 아니다).
//   콜렉터 `vscode_installs.py:117` 이 첫 스냅샷~마지막 사이의 빠진 날을 그대로 나열한다.
export type VscodeGap = string;
export interface VscodeExtensionStats {
  last: number;
  last_date: string;
  n: number;
  delta_last: number | null;
  delta_last_date: string | null;
  negative_days: number;
  stale_days: number;
}
// ★★2026-08-31 실측으로 전면 정정. 아래 두 타입은 설계 문서 기준 **추정치**였고 실물과
//   달랐다 — 그 탓에 화면이 `lastDelta.value`(undefined)를 포맷하다 TypeError 로 죽었다.
//   어제까지는 스냅샷이 1개라 delta 가 빈 배열이어서 그 분기가 아예 안 돌았고, 오늘 처음
//   2개가 되면서 터졌다. 정본은 콜렉터 `vscode_installs.py:143-144`.
//
// delta 는 객체가 아니라 **[날짜, 증분] 튜플**이다.
export type VscodeDeltaPoint = [string, number];
// marks 는 delta 와 **인덱스 1:1**이고 자기 날짜를 갖지 않는다 — 날짜는 delta[i][0] 에 있다.
// ★`span_days` 가 1보다 크면 데몬 공백을 낀 누적분이다("하루 증분"으로 읽으면 안 된다).
export interface VscodeDeltaMark {
  negative: boolean; // true = 그 시점 값이 직전보다 줄었다(MS 소급 정정)
  span_days: number;
  from: string;      // 차분의 시작 스냅샷 날짜
}
export interface VscodeExtension {
  key: string;
  id: string;
  name: string;
  short: string;
  kind: "line";
  install: number;
  snapshot_date: string;
  snapshot_utc: string;
  version: string;
  last_updated: string;
  update_count: number;
  download_count: number;
  avg_rating: number;
  rating_count: number;
  stock: [string, number][]; // 시점 누적 설치수 — 이게 차트에 그리는 계열
  delta: VscodeDeltaPoint[];
  delta_marks: VscodeDeltaMark[];
  stats: VscodeExtensionStats;
}
export interface VscodeRevision {
  extension: string;
  date: string;
  delta: number;
  from: number;
  to: number;
}
export interface VscodeInstalls {
  generated_at: string;
  asof: string | null;
  note?: string | null;
  source: AiKeyDataSource | null;
  unit: string; // "installs"
  kind: "line";
  measure: "stock";
  snapshots: VscodeSnapshot[];
  n_snapshots: number;
  gaps: VscodeGap[]; // 영구 손실 구간 — irrecoverable 과 묶어서 노출한다
  extensions: VscodeExtension[];
  revisions: VscodeRevision[];
  totals: {
    install: number;
    snapshot_date: string;
    n_extensions: number;
    delta: VscodeDeltaPoint[];
  };
}
export function getVscodeInstalls(): Promise<VscodeInstalls> {
  return request<VscodeInstalls>("/api/v1/ai-key-data/vscode-installs");
}

// ── Epoch AI — 기업 / 칩 / 데이터센터 (2026-08-28 부터 /ai-key-data 메인 카드) ──
// 3년에 수십 행짜리 뉴스 이벤트라 kind 가 step|scatter 로 온다 — 연속선 금지
// (없는 정밀도를 만든다). 라이선스는 `source.license`("CC BY 4.0") 그대로 노출.
// ★usage·compute_spend 그룹은 안 온다 — ws1 실측(usage_reports 12/49행,
//   compute_spend 14행/2사)이 너무 희소해 **1차 제외**로 확정됐다(마스터 플랜 §4).
//   ws2 설계 문서의 4그룹 표는 그 확정 전 초안이다.
export interface EpochSeriesStats {
  last: number | null;
  last_date: string | null;
  chg_pct?: number | null;
  n: number;
  stale_days?: number;
}
export interface EpochRevenueSeries {
  key: string;
  name: string;
  points: [string, number][];
  stats: EpochSeriesStats;
}
export interface EpochFundingRound {
  company: string;
  date: string;
  equity: number | null;
  debt: number | null;
  valuation: number | null;
  status: string;
  type: string;
  confidence: string;
}
export interface EpochCompanies {
  generated_at: string;
  asof: string | null;
  note?: string | null;
  source: AiKeyDataSource | null;
  revenue: {
    unit: string;
    kind: "line" | "step" | "scatter";
    note?: string | null;
    series: EpochRevenueSeries[];
  } | null;
  funding: {
    unit: string;
    kind: "line" | "step" | "scatter";
    note?: string | null;
    rounds: EpochFundingRound[]; // 시계열이 아니라 이벤트 목록 — 카드가 회사별로 묶어 점을 만든다
  } | null;
}
export function getEpochCompanies(): Promise<EpochCompanies> {
  return request<EpochCompanies>("/api/v1/ai-key-data/epoch-companies");
}

// ★칩은 날짜-값 쌍이 아니라 `quarters`(공유 x축) + 설계사별 **병렬 배열**
//   (`flow`/`cum`/`units`, 인덱스가 quarters 와 1:1)로 온다 — 카드가 zip 해서 그린다.
export interface EpochChipDesigner {
  key: string;
  name: string;
  flow: number[]; // 분기 신규
  cum: number[]; // 누적(H100e 환산)
  units: number[];
  stats: { cum_last: number; flow_last: number; share_pct: number };
}
export interface EpochChips {
  generated_at: string;
  asof: string | null;
  note?: string | null;
  source: AiKeyDataSource | null;
  unit: string; // "H100e"
  quarters: string[]; // designers[].flow/cum/units 와 같은 인덱스를 공유하는 x축(분기말)
  incomplete_quarters: string[];
  // ★끝난 분기 중 마지막(분기말 <= asof). **분기 신규(flow) 차트는 여기까지만 그린다** —
  //   진행 중 분기는 제조사 한 곳만 보고돼 있어 그대로 그리면 '출하 급감'으로 읽힌다.
  //   ⚠️누적(cum)에는 적용하지 않는다(부분 관측도 누적엔 유효, 자르면 5% 과소계상).
  last_complete_quarter: string | null;
  designers: EpochChipDesigner[];
}
export function getEpochChips(): Promise<EpochChips> {
  return request<EpochChips>("/api/v1/ai-key-data/epoch-chips");
}

// ★데이터센터는 `buildout[]` 레코드 배열 하나에 날짜+3지표(전력·H100e·Capex)가
//   같이 들어 있다 — 카드가 지표별로 풀어 3계열을 만든다.
export interface EpochDcBuildoutPoint {
  date: string;
  sites: number;
  it_power_mw: number;
  h100e: number;
  capex_bn: number;
}
export interface EpochDatacenters {
  generated_at: string;
  asof: string | null;
  note?: string | null;
  source: AiKeyDataSource | null;
  units: { power: string; compute: string; capex: string };
  buildout: EpochDcBuildoutPoint[];
}
export function getEpochDatacenters(): Promise<EpochDatacenters> {
  return request<EpochDatacenters>("/api/v1/ai-key-data/epoch-datacenters");
}

// ── AI 사용량 탭 카드 ④ OpenRouter tool-calling (2026-08-31 신설) ────────────
// 원천 `tool_calling_long.csv`(date,total_tokens,tool_calling_tokens) — 수집기가 같은
// rankings-daily 를 필터 없이 1회 + `modality=tool_calling` 1회 쳐서 굽는다.
//
// ★★**비중(tool/total)을 그리지 않는다.** 598일 내내 99.28~99.46% 라 사실상 상수다
//   (원본 xlsx·재수집 양쪽 실측). OpenRouter 의 `tool_calling` 은 "툴콜을 실제로 쓴
//   요청"이 아니라 "툴콜을 지원하는 모델" 쪽에 가까워서, 비중을 그리면 평평한 99%
//   직선이 나오고 아무 정보가 없다. 그래서 서버가 `series` 로 주는 건 둘뿐이다:
//     · ratio    = tool / non-tool  — 실측 72~185배 구간에서 실제로 움직인다
//     · non_tool = total - tool     — 71B~120B 구간에서 움직인다
//   비중은 `stats.share_pct` 에 숫자 한 개로만 온다(맥락용, 차트 금지).
// ⚠️non_tool 이 0 인 날은 ratio 계열에서 **점이 빠진다**(0/inf 로 채우지 않는다).
//   그래서 두 계열의 길이가 다를 수 있다 — 화면은 각 계열의 자기 points 만 본다.
export interface ToolCallingSeries {
  key: "ratio" | "non_tool";
  label: string;
  unit: string;
  points: [string, number][];
}
export interface ToolCallingStats {
  last_date: string;
  total: number;
  tool: number;
  non_tool: number;
  ratio: number | null;
  share_pct: number | null; // ★차트 금지 — 사실상 상수
  n: number;
}
export interface ToolCalling {
  generated_at: string;
  asof: string | null;
  note?: string | null;
  source: AiKeyDataSource | null;
  unit: string;
  kind: "line";
  series: ToolCallingSeries[];
  stats: ToolCallingStats | null;
}
export function getToolCalling(): Promise<ToolCalling> {
  return request<ToolCalling>("/api/v1/ai-key-data/tool-calling");
}

// ── [종목 모니터] 가격 모니터 (주간가격모니터 84개 시장) ──────────────────────
// 원천은 price_monitor.xlsx — collector price_board.py 가 판독하고, 분류·라벨·지표
// 정의는 회의자료 생성기(dashboard_html_writer.py)에서 이식한 것이다.
// ★자산군 하나씩 받는다(cat) — 84개 전량 + 3년 주간 시계열을 한 번에 실으면 무겁다.
// ★★채권(bond)은 **bp**, 나머지는 **%**. `is_yield`·`unit` 로 갈라 표기한다 —
//   금리의 %변화율은 의미가 없고 마이너스 구간에서 부호가 뒤집힌다.
export type PriceCatKey = "equity" | "bond" | "commodity" | "fx" | "crypto";

// ★달력 앵커(mtd·ytd)와 롤링(r1m~r1y)이 **둘 다** 온다(2026-08-31). 달력 앵커는
//   "이번 달 얼마"를 답하고, 롤링은 시장끼리 비교할 때 쓴다 — 월초에는 모든 시장의
//   MtD 가 0 근처로 뭉쳐 비교가 안 되기 때문이다. 우하단 요약 표가 8개를 다 쓴다.
export interface PriceBoardRow {
  key: string;      // 블룸버그 티커 = 고유키
  group: string;    // layer1 — 벤치마크/DM/EM · 미국/한국/… · 에너지/귀금속/… (없으면 "")
  sub_group: string; // layer2 — DM·EM 안의 지역 묶음(없으면 "")
  label: string;
  sub: string;      // 보조 라벨(단위·출처)
  asof: string;
  price: number;
  dtd: number | null;
  wtd: number | null;
  mtd: number | null;
  ytd: number | null;
  r1m: number | null;  // 롤링 30일
  r3m: number | null;  // 롤링 91일 — 차트의 '롤링 3M' 과 같은 창
  r6m: number | null;  // 롤링 182일
  r1y: number | null;  // 롤링 365일
}

// 좌측 목록의 계층 — 자산군(탭) → layer1 → layer2 → 실제 지수(leaf).
// 그룹이 빈 자산군(환·비트코인)은 leaf 가 최상단에 바로 온다.
export type PriceTreeNode =
  | { type: "node"; label: string; children: PriceTreeNode[] }
  | ({ type: "leaf" } & Omit<PriceBoardRow, "group" | "sub_group">);
export interface PriceBoardSeries {
  key: string;
  label: string;
  points: [string, number][]; // 3년 주간 마지막값
}
export interface PriceBoard {
  generated_at: string;
  note?: string | null;
  cat: PriceCatKey;
  cat_label: string;
  unit: string;       // '%' | 'bp'
  is_yield: boolean;
  asof: string | null;
  categories: { key: PriceCatKey; label: string }[];
  rows: PriceBoardRow[];
  tree: PriceTreeNode[];
  series: PriceBoardSeries[];
}

export function getPriceBoard(cat: PriceCatKey): Promise<PriceBoard> {
  return request<PriceBoard>(`/api/v1/stock-monitor/price-board?cat=${cat}`);
}

// ── 차트 계열 ────────────────────────────────────────────────────────────────
// ★★2026-08-31 계약 교체. DtD·WtD·MtD·YtD **시계열**은 없어졌다 — 달력 앵커라
//   월초·연초마다 0 으로 리셋되는 톱니여서 추세를 읽을 수 없고, 그 숫자는 요약
//   표(PriceBoardRow)가 이미 준다. 차트는 2모드다:
//     · cum (누적수익률) — **프론트가** 보는 구간 첫 점 기준으로 price 를 리베이스
//     · r3m (롤링 3M)    — 서버가 계산해 준 그대로
//   그래서 계열마다 price·r3m 을 **둘 다** 싣는다 — 모드를 바꿔도 재요청이 없다.
// ★cum 을 서버가 못 만드는 이유: 리베이스 기준점이 사용자가 좁힌 구간의 첫 점이라
//   서버가 모른다. 고정 시작점으로 계산하면 구간을 좁혀도 0% 가 안 따라온다.
// ★'벤치마크 대비'(상대곡선) 모드는 만들었다가 같은 날 제거했다(사용자 지시) —
//   payload 에 벤치마크 계열이 없는 이유다.
export type PriceChartMode = "cum" | "r3m";
export interface PriceChartSeries {
  key: string;   // 티커
  label: string;
  sub: string;
  price: [string, number][]; // 가격 원본(주간) — cum 의 재료
  r3m: [string, number][];   // 롤링 91일 지표(주간). 앞 91일이 없어 price 보다 짧다
}
interface PriceChartCommon {
  generated_at: string;
  unit: string;      // '%' | 'bp'
  is_yield: boolean;
  modes: { key: PriceChartMode; label: string }[];
  series: PriceChartSeries[];
  note?: string | null;
}
export interface PriceMetricPayload extends PriceChartCommon {
  key: string;
  label: string;
  sub: string;
  cat: PriceCatKey | null;
  asof?: string;
  price?: number;
}

export function getPriceMetricSeries(key: string): Promise<PriceMetricPayload> {
  return request<PriceMetricPayload>(
    `/api/v1/stock-monitor/price-board/metric-series?key=${encodeURIComponent(key)}`,
  );
}

// 묶음(예: DM/미국) 안 시장들의 차트 계열. metric-series 와 **payload 모양이 같다**
// — 계열이 1개냐 N개냐만 다르다. 그래서 차트는 series 배열 하나만 그리면 양쪽을 다 그린다.
export interface PriceGroupPayload extends PriceChartCommon {
  kind: "group";
  cat: PriceCatKey;
  l1: string;
  l2: string;
  label: string;
  sub: string;
  asof: string | null;
}

export function getPriceGroupSeries(
  cat: PriceCatKey,
  l1: string,
  l2: string,
): Promise<PriceGroupPayload> {
  const q = new URLSearchParams({ cat, l1, l2 });
  return request<PriceGroupPayload>(
    `/api/v1/stock-monitor/price-board/group-series?${q.toString()}`,
  );
}

// ── [종목 모니터] 종목 상세(5대 축) ──────────────────────────────────────────
// 원천이 S:\...\Toss_분봉_모니터\input\raw 의 이름-키 JSON 이라 name 으로 묻는다.
// (차트 스크리닝·실시간 뉴스는 2026-08-25 은퇴 — chart 타입·클라이언트도 함께 삭제)
export interface StockDetail {
  name: string;
  symbol: string | null;
  sector: Record<string, string> | null;  // {L1..L5}
  country: string | null;
  currency: string | null;
  news_axis: boolean;
  axes: string[];                          // 5대 축 — 수기 입력, 화면에서 편집
  has_axis_file: boolean;
}
export function getStockDetail(name: string): Promise<StockDetail> {
  return request<StockDetail>(
    `/api/v1/stock-monitor/stock-detail?name=${encodeURIComponent(name)}`,
  );
}

export interface SaveStockAxisInput {
  name: string;
  symbol?: string | null;   // 있으면 서버가 파일과 대조한다(불일치 409)
  news_axis: boolean;
  axes: string[];           // 정확히 5개
}
export function saveStockAxis(body: SaveStockAxisInput): Promise<{ ok: boolean }> {
  return request<{ ok: boolean }>("/api/v1/stock-monitor/stock-axis", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify(body),
  });
}
