// AI Key Data(S5) 전용 클라이언트 — `GET /api/v1/market/ai/status` · `/api/v1/market/ai/{source}`.
//
// ⚠️`lib/api.ts` 의 `request()` 는 모듈 private 이라 가져올 수 없다. 공개된
//   `API_BASE_URL` · `ApiError` 만 가져와 같은 에러 봉투 처리를 재구현한다
//   (`lib/api-coverage.ts` · `lib/api-valuechain.ts` 와 같은 방식, 계획 §12-8).
// ⚠️타입은 2026-09-27 라이브 응답을 curl 로 실측해 옮겼다(apps/api/app/schemas.py
//   AiSeriesOut · AiTableOut · AiSourceOut · AiSourceStatusOut · AiStatusOut).
//   구 `/api/v1/market/ai-data`(`getAiData`)는 백엔드에 남아 있지만 이 탭은 더 안 쓴다.
import { API_BASE_URL, ApiError } from "@/lib/api";

export const AI_SOURCES = [
  "npm",
  "vscode",
  "pypi",
  "openrouter",
  "tool_calling",
  "ramp",
  "epoch",
] as const;

export type AiSourceKey = (typeof AI_SOURCES)[number];

/** ok | stale(갱신 실패, 마지막 정상값) | key_missing | error | empty | unknown */
export type AiSourceState = "ok" | "stale" | "key_missing" | "error" | "empty" | "fetching" | (string & {});

/** [["YYYY-MM-DD", 값]] 오름차순. 결측일은 점이 없다(0 이 아니다). */
export type AiPoint = [string, number];

export interface AiLiveSeries {
  key: string;
  label: string;
  /** 같은 소스 안의 묶음 — npm 'cli'|'sdk', vscode 'install'|'delta', epoch 'chip_h100e'|'lab_arr' … */
  group: string | null;
  unit: string | null;
  points: AiPoint[];
}

export type AiTableCell = string | number | boolean | null;

export interface AiLiveTable {
  key: string;
  label: string;
  columns: string[];
  rows: Record<string, AiTableCell>[];
}

export interface AiSourcePayload {
  source: AiSourceKey;
  status: AiSourceState;
  series: AiLiveSeries[];
  tables: AiLiveTable[];
  /** 원천이 스스로 밝힌 기준 시각(OpenRouter meta.as_of 등). */
  as_of: string | null;
  /** 데이터의 마지막 날짜. */
  latest_date: string | null;
  source_url: string;
  /** ⚠️OpenRouter 는 `{as_of}` 자리표시자가 그대로 온다 — 화면이 채운다. */
  attribution: string | null;
  note: string | null;
  fetched_at: string | null;
  last_ok: string | null;
  extra: Record<string, unknown> | null;
}

export interface AiSourceStatus {
  source: AiSourceKey;
  status: AiSourceState;
  ok: boolean;
  /** 이 프로세스가 캐시를 한 번이라도 채웠나(라이브 소스). */
  fetched: boolean;
  last_ok: string | null;
  latest_date: string | null;
  note: string | null;
  as_of: string | null;
  key_missing: boolean;
}

export interface AiStatus {
  items: AiSourceStatus[];
}

async function get<T>(path: string): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE_URL}${path}`);
  } catch {
    throw new ApiError(0, "NETWORK_ERROR", "API unreachable");
  }
  const text = await res.text();
  let data: unknown = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = null;
    }
  }
  if (!res.ok) {
    const env = data as { error?: { code?: string; message?: string; details?: Record<string, unknown> } } | null;
    throw new ApiError(
      res.status,
      env?.error?.code ?? "INTERNAL_ERROR",
      env?.error?.message ?? `Request failed (${res.status})`,
      env?.error?.details,
    );
  }
  return data as T;
}

export function getAiStatus(): Promise<AiStatus> {
  return get<AiStatus>("/api/v1/market/ai/status");
}

export function getAiSource(source: AiSourceKey): Promise<AiSourcePayload> {
  return get<AiSourcePayload>(`/api/v1/market/ai/${source}`);
}

export const aiQueryKeys = {
  status: ["ai", "status"] as const,
  source: (s: AiSourceKey) => ["ai", "source", s] as const,
};
