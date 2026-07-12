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

// ── Kiwoom portfolio (round 2) ─────────────────────────────────────────────
// Shapes mirror docs/architecture/contract-kiwoom.md §6. snake_case, ISO8601 UTC.
// Numeric fields serialize as JSON numbers; KRW-converted / FX-dependent fields
// are nullable (US rows may lack an FX rate until known).

export type ConnectionStatus = "CONFIGURED" | "CONNECTED" | "ERROR";
export type SyncStatus = "NEVER_SYNCED" | "SUCCESS" | "FAILED" | "RUNNING";

export interface Position {
  account_id: string;
  asset_id: string;
  broker: string | null;
  country: string | null;
  market: string | null;
  ticker: string | null;
  asset_name: string | null;
  asset_type: string | null;
  currency: string | null;
  quantity: number | null;
  available_quantity: number | null;
  average_purchase_price: number | null;
  purchase_amount_local: number | null;
  current_price: number | null;
  market_value_local: number | null;
  unrealized_pnl_local: number | null;
  unrealized_return: number | null;
  exchange_rate: number | null;
  market_value_krw: number | null;
  unrealized_pnl_krw: number | null;
  as_of: string | null;
  source_job_id: string | null;
}

export interface PositionListResponse {
  items: Position[];
  total: number;
}

export interface BrokerageConnection {
  id: string;
  broker_code: string;
  connection_name: string;
  environment: string;
  status: ConnectionStatus;
  last_connected_at: string | null;
  last_synced_at: string | null;
  last_error: string | null;
  credentials_configured: boolean;
}

export interface BrokerageConnectionListResponse {
  items: BrokerageConnection[];
}

export interface SyncTriggerResponse {
  job_id: string;
  status: JobStatus;
  reused: boolean;
}

export interface PortfolioSummary {
  total_assets_krw: number;
  securities_value_krw: number;
  cash_value_krw: number;
  total_purchase_amount_krw: number;
  total_unrealized_pnl_krw: number;
  unrealized_return_pct: number | null;
  position_count: number;
  account_count: number;
}

export interface PortfolioAccount {
  id: string;
  account_name: string | null;
  account_number_masked: string | null;
  account_type: string | null;
  base_currency: string | null;
  total_assets_krw: number | null;
  last_synced_at: string | null;
}

export interface CashBalance {
  account_id: string;
  currency: string;
  cash_balance: number | null;
  available_cash: number | null;
  exchange_rate: number | null;
  /** This row's cash converted to KRW by Kiwoom's rate. Use this for cash totals. */
  cash_krw: number | null;
  /** Kiwoom's 추정예탁자산 (account-level: cash + securities), NOT this row's cash in
   * KRW. Reconciliation figure only — summing it as cash double-counts securities. */
  estimated_total_assets_krw: number | null;
  as_of: string | null;
}

export interface MarketBreakdown {
  country: string | null;
  securities_value_krw: number;
  position_count: number;
}

// 자산군 (portfolio-detail-spec §2). Cash is not a holding, so it is an asset
// CLASS (donut slice) but never an asset TYPE a user can assign to a position.
export type AssetType = "STOCK" | "BOND" | "DERIVATIVE" | "OTHER";
export type AssetClass = AssetType | "CASH";

export interface AssetClassBreakdown {
  asset_class: AssetClass;
  value_krw: number;
  weight_pct: number;
  /** null for CASH — cash has no positions. */
  position_count: number | null;
}

export interface Asset {
  id: string;
  ticker: string | null;
  name: string | null;
  asset_type: AssetType;
}

export interface ConnectionBrief {
  id: string;
  status: ConnectionStatus;
  credentials_configured: boolean;
  last_error: string | null;
}

export interface PortfolioOverview {
  summary: PortfolioSummary;
  accounts: PortfolioAccount[];
  positions: Position[];
  cash_balances: CashBalance[];
  market_breakdown: MarketBreakdown[];
  /** Always five slices, fixed order, zeros included. The API is the single
   * source of this aggregation — the web never recomputes it. */
  asset_class_breakdown: AssetClassBreakdown[];
  last_synced_at: string | null;
  sync_status: SyncStatus;
  connection: ConnectionBrief | null;
}

export interface PositionFilters {
  account_id?: string;
  country?: string;
  currency?: string;
}

// 자산 추이 (performance-chart-spec §1). One point per KST day — the day's last
// snapshot. Snapshots only exist from the first sync onward; history is never
// backfilled.
export interface HistoryPoint {
  date: string;
  snapshot_at: string;
  total_assets_krw: number;
  securities_value_krw: number;
  cash_value_krw: number;
  total_purchase_amount_krw: number;
  total_unrealized_pnl_krw: number;
  unrealized_return_pct: number | null;
}

export interface PortfolioHistory {
  points: HistoryPoint[];
  distinct_days: number;
  first_snapshot_at: string | null;
  last_snapshot_at: string | null;
  excluded_tickers: string[];
}

export interface HistoryFilters {
  days?: number;
  /** Recomputes each point without these tickers, so a screen that hides
   * positions shows a chart that agrees with its own cards (§1.2). */
  exclude_tickers?: string[];
}

export function getPortfolioHistory(
  filters: HistoryFilters = {},
): Promise<PortfolioHistory> {
  const q = new URLSearchParams();
  if (filters.days != null) q.set("days", String(filters.days));
  if (filters.exclude_tickers?.length) {
    q.set("exclude_tickers", filters.exclude_tickers.join(","));
  }
  const qs = q.toString();
  return request<PortfolioHistory>(
    `/api/v1/portfolio/history${qs ? `?${qs}` : ""}`,
  );
}

export function getBrokerageConnections(): Promise<BrokerageConnectionListResponse> {
  return request<BrokerageConnectionListResponse>(
    "/api/v1/brokerage-connections",
  );
}

export function getBrokerageConnection(id: string): Promise<BrokerageConnection> {
  return request<BrokerageConnection>(`/api/v1/brokerage-connections/${id}`);
}

export function syncConnection(id: string): Promise<SyncTriggerResponse> {
  return request<SyncTriggerResponse>(
    `/api/v1/brokerage-connections/${id}/sync`,
    { method: "POST" },
  );
}

export function getPortfolioOverview(): Promise<PortfolioOverview> {
  return request<PortfolioOverview>("/api/v1/portfolio/overview");
}

/** 자산군 수동 지정 (portfolio-detail-spec §2/§3). The worker never overwrites
 * asset_type, so a user's choice survives the next sync. */
export function updateAssetType(
  assetId: string,
  assetType: AssetType,
): Promise<Asset> {
  return request<Asset>(`/api/v1/assets/${assetId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ asset_type: assetType }),
  });
}

export function getPositions(
  filters: PositionFilters = {},
): Promise<PositionListResponse> {
  const q = new URLSearchParams();
  if (filters.account_id) q.set("account_id", filters.account_id);
  if (filters.country) q.set("country", filters.country);
  if (filters.currency) q.set("currency", filters.currency);
  const qs = q.toString();
  return request<PositionListResponse>(
    `/api/v1/portfolio/positions${qs ? `?${qs}` : ""}`,
  );
}
