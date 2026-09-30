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

/* ── [국내상장 ETF] 분류별 개인순매수·수익률 ──────────────────────────────────
   collector 가 `국내상장ETF 모니터링.xlsm` value 시트를 읽어 만든 한 묶음.
   축(구분/대분류/중분류/소분류/국가) 5개 × 기간 9개를 **전부** 담고 온다 —
   화면이 축·기간을 바꿔도 재요청이 없고, 집계식이 서버 한 곳에만 있다.

   ★기간 키는 두 갈래다. 누적(cum) 은 창 그대로(당일·1주·1개월·3개월·6개월),
     구간(iv) 은 누적끼리 뺀 것(최근1주·1주~1개월·1~3개월·3~6개월). 네 창이 전부
     오늘로 끝나 서로 포개지므로, 겹침을 걷어내지 않으면 같은 돈을 네 번 센다. */
export type EtfPeriodKey = "d" | "1w" | "1m" | "3m" | "6m";
export type EtfIvKey = "1w" | "1m" | "3m" | "6m";
export type EtfAxisKey = "gubun" | "big" | "mid" | "small" | "country";

export interface EtfPeriodSpec {
  key: EtfPeriodKey;
  label: string;
  span: string | null;
  start: string | null;
  end: string | null;
  /** 창 안의 거래일 수(주말 제외·공휴일 미반영). 유입액을 일평균으로 나눌 때 쓴다 —
   *  총액을 한 축에 놓으면 1개월이 어제의 20배가 넘어 어제 막대가 안 보인다. */
  days: number;
}
export interface EtfIntervalSpec {
  key: EtfIvKey;
  label: string;
  outer: string;
  inner: string | null;
  start: string | null;
  end: string | null;
  days: number;
}
type ByPeriod = Record<EtfPeriodKey, number | null>;
type ByIv = Record<EtfIvKey, number | null>;

export interface EtfGroupRow {
  key: string; // 조상 경로까지 붙인 고유키 ("시장&전략 / 전략형 / 커버드콜")
  label: string; // 표시명 ("커버드콜")
  path: string[]; // 조상 라벨
  n: number;
  mcap: number; // 억
  amt: number; // 거래대금 억
  net_cum: ByPeriod; // 개인순매수 누적(억)
  net_iv: ByIv; // 개인순매수 구간(억)
  ret_cum: ByPeriod; // 시총가중 수익률(소수)
  ret_cum_eq: ByPeriod; // 단순평균 수익률(소수)
  ret_iv: ByIv;
  ret_iv_eq: ByIv;
  ratio_cum: ByPeriod; // 순매수/시총 (%)
  ratio_iv: ByIv;
}
export interface EtfRow {
  /** AXES 순서(구분·대분류·중분류·소분류·투자국가)의 분류 키. 서버가 실제로 넣은
   *  묶음의 키다 — 화면은 이걸로 조인한다. 같은 규칙을 프런트에 한 벌 더 두면
   *  표기 접기(`Top10`/`TOP10`) 같은 게 들어올 때 두 곳이 갈린다. */
  gkeys: string[];
  code: string;
  name: string;
  /** 상장일 'YYYY-MM-DD'. '신규 상장' 칸이 쓴다. */
  listed: string;
  country: string;
  gubun: string;
  big: string;
  mid: string;
  small: string;
  mcap: number | null;
  amt: number | null;
  price: number | null;
  interest: boolean;
  net_cum: ByPeriod;
  net_iv: ByIv;
  ret_cum: ByPeriod;
  ret_iv: ByIv;
}
export interface EtfClassPayload {
  generated_at: string;
  asof: string | null; // 워크북 기준일
  source_modified: string | null;
  note: string | null; // 원천 결측·판독 실패 — 있으면 화면이 띄운다
  axes: { key: EtfAxisKey; label: string }[];
  periods: EtfPeriodSpec[];
  intervals: EtfIntervalSpec[];
  windows: Record<string, { start: string | null; end: string | null }>;
  groups: Record<EtfAxisKey, EtfGroupRow[]>;
  etfs: EtfRow[];
  totals: EtfGroupRow | null;
  history_days: number; // 적재된 스냅샷 일수
  /** 워크북이 결측 대신 0 을 준 기간 수익률을 몇 개나 걸렀는지(창 시작 전 상장 등). */
  masked_returns: number;
}
export function getEtfClass(): Promise<EtfClassPayload> {
  return request<EtfClassPayload>("/api/v1/etf-class");
}

/* 시점별 추이(`/api/v1/etf-class/history`)는 2026-09-01 사용자 지시로 **화면에서 뺐다**.
   collector 쪽 적재와 엔드포인트는 남겨 뒀다 — 원천 워크북이 매일 덮어쓰기라 지금 안 쌓으면
   그 날짜는 영영 복구할 수 없기 때문이다. 다시 그릴 일이 생기면 클라이언트만 붙이면 된다. */

/* ── [국내상장 ETF] 신규상장 세 갈래 ────────────────────────────────────────
   원천이 넷이고 주인이 달라 collector 가 가져다 붙인다(etf_new_listing.py 주석 참조).
   ★DART 는 확정 상장일을 주지 않는다 — 예상 **범위**만 준다. 그래서 확정(`listing`,
     KRX LIST_DD)과 예정(`upcoming`, DART est_listing)이 따로 온다. 섞으면 "오늘 상장"
     이라 써 놓고 다음 주에 상장하는 일이 생긴다. */
export interface EtfListingHolding {
  name: string;
  weight: number | null;
}
/** 성적표 한 줄 — daily_analysis/YYYYMMDD_신규상장.txt. 금액 단위는 억원.
 *  `ret` 는 txt 에 없어 워크북 등락률을 이름으로 붙인 값(소수)이다. */
export interface EtfListingReportRow {
  rank: number;
  name: string;
  /** 상장일 기준(txt). 아래 realtime 의 같은 이름 값과 **시점이 다르다**. */
  trade_value: number | null;
  net_buy: number | null;
  ret: number | null;
  /** 아래 셋은 서버가 이름으로 이어 붙인 KRX·CHECK 값. 못 찾으면 빈 값/null. */
  ticker: string;
  fee: number | null;
  realtime: EtfListingRealtime | null;
}
/** CHECK 호가 envelope 의 newEtfs. ⚠️단위가 섞여 있다 —
 *  trade_value·market_cap·indiv_net 은 **억원**, volume 은 **주**, change 는 **%**. */
export interface EtfListingRealtime {
  price: number | null;
  change: number | null;
  trade_value: number | null;
  volume: number | null;
  market_cap: number | null;
  indiv_net: number | null;
  listed: string;
}
export interface EtfListingRow {
  name: string;
  ticker: string;
  isin: string;
  company: string;
  /** 총보수(%) — KRX ETF_TOT_FEE. 펀드공시모니터 캐시의 fee 는 비어 있어 KRX 에서 받는다. */
  fee: number | null;
  benchmark: string;
  asset_class: string;
  holdings: EtfListingHolding[];
  /** CHECK 관심목록 밖의 종목은 null (실측: MIDAS 머니마켓액티브). */
  realtime: EtfListingRealtime | null;
}
export interface EtfUpcomingRow {
  rcept_no: string;
  name: string;
  company: string;
  est_from: string;
  est_to: string;
  is_amend: boolean;
  holdings: EtfListingHolding[];
  holdings_src: string;
}
export interface EtfNewListingPayload {
  generated_at: string;
  today: string;
  note: string | null;
  /** CHECK envelope 이 언제 것인가. 낡으면(5분 초과) 화면이 '실시간' 이라 쓰지 않는다 —
   *  장 마감·CHECK PC 정지 뒤의 마지막 값을 실시간이라 보여주면 그 자체가 틀린 말이다. */
  realtime_asof: string | null;
  realtime_stale: boolean;
  report: { date: string | null; is_today: boolean; rows: EtfListingReportRow[] };
  listing: { date: string | null; is_today: boolean; rows: EtfListingRow[] };
  upcoming: EtfUpcomingRow[];
}
export function getEtfNewListing(): Promise<EtfNewListingPayload> {
  return request<EtfNewListingPayload>("/api/v1/etf-class/new-listing");
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
// 잔고 동기화(30초)와 **별개**로 돈다. 시세만 받아오므로 5초 주기여도 가볍다
// (실측 17종목 0.60초, 서버에 4초 TTL 캐시).

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
