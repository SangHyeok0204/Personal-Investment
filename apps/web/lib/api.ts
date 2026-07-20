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
}

export interface WrapPayload {
  date: string;
  generatedAt: string;
  timestamp: number;
  priceGeneratedAt: string;
  portfolios: WrapPortfolio[];
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
  obThreshold: number | null;
  premiumIntra: number | null;
  premiumActual: number | null;
}

export interface InavHoga {
  payload: { etfs: HogaEtf[] } | null;
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
