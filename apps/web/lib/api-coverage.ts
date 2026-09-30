// 데이터 보유 현황판(S8) 전용 클라이언트 — `GET /api/v1/research/coverage/{kind}`.
//
// ⚠️`lib/api.ts` 의 `request()` 는 그 파일 안에서만 쓰는 비공개 함수라 그대로
//   가져올 수 없다. `API_BASE_URL` · `ApiError` 만 가져와 같은 모양으로 다시 만든다
//   — `lib/api.ts` 자체는 다른 레인이 쓰고 있어 건드리지 않는다(§12-8).
// ⚠️라우터가 아직 `main.py` 에 안 붙어 있다(레인 C·리드가 나중에 통합) — 그동안은
//   이 호출이 전부 404/네트워크 에러로 실패한다. `coverage-panel.tsx` 가 그 상태를
//   에러 배너로 보여 준다.
import { API_BASE_URL, ApiError } from "@/lib/api";

export type CoverageKind = "stocks" | "guru" | "earnings" | "filings";

export interface CoverageKpi {
  label: string;
  value: string;
  hint: string | null;
}

export interface CoverageSource {
  source: string;
  last_ok_at: string | null;
  last_error_at: string | null;
  last_error_kind: string | null;
  stale: boolean;
}

export type CoverageCell = string | number | boolean | null;

export interface CoverageTableRow {
  key: string;
  label: string;
  link: string | null;
  cells: CoverageCell[];
}

export interface CoverageTable {
  columns: string[];
  rows: CoverageTableRow[];
}

export interface CoverageResponse {
  kind: CoverageKind;
  generated_at: string;
  kpis: CoverageKpi[];
  table: CoverageTable;
  sources: CoverageSource[];
  anomalies: string[];
  notes: string[];
}

interface ErrorEnvelope {
  error: { code: string; message: string; details?: Record<string, unknown> };
}

export async function getCoverage(kind: CoverageKind): Promise<CoverageResponse> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE_URL}/api/v1/research/coverage/${kind}`);
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
  return data as CoverageResponse;
}
