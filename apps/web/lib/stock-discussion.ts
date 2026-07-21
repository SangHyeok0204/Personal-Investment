// 종토방(네이버·토스 종목토론방) 읽기 클라이언트. 로컬 대시보드 Postgres 서빙
// 사본을 조회한다(정본=개발 PC, ralplan §1.6·§2). request 래퍼는 api.ts 에서
// export 되지 않으므로(모듈 private) 같은 에러 봉투 처리를 재구현하되, 공개된
// API_BASE_URL·ApiError 는 재사용해 ApiErrorBanner 가 그대로 동작하게 한다.
import { useQuery, keepPreviousData } from "@tanstack/react-query";
import { API_BASE_URL, ApiError } from "@/lib/api";

// ── 도메인 타입 (백엔드 응답 계약, teammate 브리핑 + 실측 curl 기준) ──
export type SdSource = "네이버" | "토스증권";
export type SdSentiment = "긍정" | "부정" | "중립";

export interface SdPost {
  id: number;
  src_id: number;
  source: SdSource;
  post_id: string;
  etf_code: string;
  etf_name: string;
  title: string;
  content: string;
  post_date: string | null;
  post_date_raw: string | null;
  author: string;
  likes: number;
  dislikes: number;
  comments: number;
  crawled_at: string;
  sentiment: SdSentiment | null;
  sentiment_confidence: number | null;
  sentiment_model: string | null;
  sentiment_at: string | null;
  ingested_at: string;
}

export interface SdRecentResponse {
  items: SdPost[];
  total: number;
  limit: number;
  offset: number;
}

export interface SdEtf {
  code: string;
  name: string;
  issuer: string;
  category: string;
  updated_at: string;
}

export interface SdHealthChannel {
  last_ok: string | null;
  last_error: string | null;
  consecutive_errors: number;
}

export interface SdStats {
  total: number;
  today: number;
  last_hour: number;
  by_etf_source: {
    etf_code: string;
    etf_name: string;
    source: SdSource;
    n: number;
  }[];
  today_by_etf: { etf_code: string; n: number }[];
  sentiment: {
    labeled: number;
    긍정: number;
    부정: number;
    중립: number;
  };
  health: {
    naver: SdHealthChannel;
    toss: SdHealthChannel;
    sentiment: { labeled_total: number; cost_usd_total: number };
    spy: { labels_total: number };
  };
  last_ingest_at: string | null;
}

export interface SdSpy {
  id: number;
  source: SdSource;
  author: string;
  label: string;
  reason: string;
  stats: unknown;
  updated_at: string;
}

// ── request 래퍼 (api.ts 의 private request 를 미러 — 같은 ApiError 봉투) ──
async function sdRequest<T>(path: string): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE_URL}${path}`);
  } catch {
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
    const env = data as
      | { error?: { code?: string; message?: string; details?: Record<string, unknown> } }
      | null;
    const code = env?.error?.code ?? "INTERNAL_ERROR";
    const message = env?.error?.message ?? `Request failed (${res.status})`;
    throw new ApiError(res.status, code, message, env?.error?.details);
  }

  return data as T;
}

// ── 필터 + 페처 ──
export interface RecentFilters {
  etf_code?: string | null;
  etf_codes?: string[] | null;
  source?: SdSource | null;
  keyword?: string | null;
}

const BASE = "/api/v1/stock-discussion";

export function getSdEtfs(): Promise<SdEtf[]> {
  return sdRequest<SdEtf[]>(`${BASE}/etfs`);
}

export function getSdRecent(
  filters: RecentFilters,
  limit: number,
): Promise<SdRecentResponse> {
  const q = new URLSearchParams();
  q.set("limit", String(limit));
  q.set("offset", "0"); // 성장 윈도우: offset 항상 0 (ralplan §1.2 페이징)
  if (filters.etf_code) {
    q.set("etf_code", filters.etf_code);
  } else if (filters.etf_codes && filters.etf_codes.length > 0) {
    q.set("etf_codes", filters.etf_codes.join(","));
  }
  if (filters.source) q.set("source", filters.source);
  const kw = filters.keyword?.trim();
  if (kw) q.set("keyword", kw);
  return sdRequest<SdRecentResponse>(`${BASE}/recent?${q.toString()}`);
}

export function getSdStats(): Promise<SdStats> {
  return sdRequest<SdStats>(`${BASE}/stats`);
}

export function getSdSpies(): Promise<SdSpy[]> {
  return sdRequest<SdSpy[]>(`${BASE}/spies`);
}

// ── react-query 훅 (폴링 12s/30s, retry:false — ralplan §4·§1.6) ──
export function useEtfs() {
  return useQuery({
    queryKey: ["sd", "etfs"],
    queryFn: getSdEtfs,
    staleTime: Infinity,
    retry: false,
  });
}

export function useRecentPosts(
  filters: RecentFilters,
  { limit }: { limit: number },
) {
  return useQuery({
    queryKey: ["sd", "recent", filters, limit],
    queryFn: () => getSdRecent(filters, limit),
    refetchInterval: 12000,
    retry: false,
    // 필터 변경 시 스켈레톤 깜빡임 대신 직전 피드를 유지(§6 last-good).
    placeholderData: keepPreviousData,
  });
}

export function useStats() {
  return useQuery({
    queryKey: ["sd", "stats"],
    queryFn: getSdStats,
    refetchInterval: 30000,
    retry: false,
  });
}

export function useSpies() {
  return useQuery({
    queryKey: ["sd", "spies"],
    queryFn: getSdSpies,
    refetchInterval: 30000,
    retry: false,
  });
}
