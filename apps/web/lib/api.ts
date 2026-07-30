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
  pct: number;
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
  // 환 자체 등락률(통화 기준). '환 수익률' 열은 현금 행에서만 이 값을 쓴다.
  fx_return_pct?: number | null;
  // 환을 반영했을 때의 종목 수익률 = (1+현지수익률)(1+환등락) − 1.
  return_krw_pct?: number | null;
  weight_pct: number;
  prev_close: number | null;
  livePrice: number | null;
  return_pct: number | null;
  contribution_pct: number | null;
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
  // 환 노출 통화(비중 최대 외화)와 그 순수 등락률 — 현금 행의 '환 수익률'로 표시.
  fx_currency?: string | null;
  fx_return_pct?: number | null;
  // ② 전일종가→최근체결가 (USD / 원화)
  return2_usd?: number | null;
  return2_krw?: number | null;
  // ① 전전일→전일 종가수익률 (USD / 원화) + 기준일·신선도
  return1_usd?: number | null;
  return1_krw?: number | null;
  return1_basis_date?: string | null; // "YYYYMMDD"
  return1_prev_date?: string | null; // "YYYYMMDD"
  return1_is_current?: boolean;
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

// ── [성과보고 HTML] S: bat 산출물 뷰어 ────────────────────────────────
// 계산·서사가 전부 S: 쪽 bat 으로 넘어간 구조. 대시보드는 파일명 규약으로 고른
// 자체완결 HTML 을 iframe(srcDoc)으로 띄우기만 한다. 기준일=파일명, 작성일=mtime.
export interface PerfReportItem {
  rel: string; // 루트 기준 상대경로 (파일 요청 키)
  name: string;
  kind: "daily" | "weekly";
  asOf: string;
  start: string | null;
  end: string;
  label: string; // "데일리 · 2026.07.29 기준"
  writtenOn: string; // 파일 mtime 날짜
  savedAt: string; // 파일 mtime (분까지)
}
export interface PerfReportListing {
  today: string;
  weekday: number;
  expected: "daily" | "weekly" | null;
  status: "ready" | "pending" | "off";
  current: PerfReportItem | null; // 오늘 만들어진 보고서 (없으면 null)
  latest: PerfReportItem | null; // 종류 무관 최신분 (pending 안내용)
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
  kind: "open5" | "roll1h";
  changePct: number;
  spreadPct: number | null; // roll1h: 60분 변동폭(%p)
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
  mean: number | null;
  mode: number | null;
  median: number | null;
}

export interface LpEvalBasisStat {
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
}
export interface LpEvalEtf {
  code: string;
  name: string;
  basis: { lp?: LpEvalBasisStat; total?: LpEvalBasisStat };
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
