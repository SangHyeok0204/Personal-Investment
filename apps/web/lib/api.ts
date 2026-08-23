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
  // null = 소진율 판정 불가(Genspark 가 월 할당량을 못 알아낸 경우). 0% 로 그리지 않는다.
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
  // Genspark 전용 — 월 할당/잔여 크레딧. Claude/GPT 는 항상 null.
  monthly_credits: number | null;
  credit_balance: number | null;
  items: AiUsageMeter[];
}

export interface AiTokenUsageResponse {
  monitor_base_url: string;
  reachable: boolean;
  error: string | null;
  fetched_at: string;
  claude: AiUsageAccount[];
  codex: AiUsageAccount[];
  genspark: AiUsageAccount[];
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
  universe?: number;
  value_basis?: string;
  note?: string;
  rows: StockMonitorRow[];
}

export function getStockMonitor(
  sort: "value" | "change" | "sigma" = "value",
  limit = 30,
  day?: string,
): Promise<StockMonitor> {
  const qs = new URLSearchParams({ sort, limit: String(limit) });
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
